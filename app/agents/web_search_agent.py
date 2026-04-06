"""Web search agent — searches web sources for matching content.

Delegates all computation to the tools layer (web_search_tool, embedding_tool,
similarity_tool). The agent only handles orchestration and interpretation.

Search backends are handled transparently by the tool layer:
  1. Bing (if PG_BING_API_KEY is set and valid)
  2. DuckDuckGo (free fallback — no key needed)

The agent does NOT gate on ``bing_api_key`` because the tool layer
handles the Bing→DuckDuckGo fallback automatically.
"""

from __future__ import annotations

import re

import numpy as np

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.tools.content_extractor_tool import chunk_text
from app.tools.embedding_tool import generate_embeddings
from app.tools.similarity_tool import cosine_similarity_matrix, compute_overall_score
from app.tools.web_search_tool import search_multiple, fetch_page_text
from app.tools.fingerprint_tool import fingerprint_match_score, fingerprint_chunks


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

_GLYPH_RE = re.compile(r"/gid\d{3,5}")
_MULTI_WS = re.compile(r"[ \t]+")
_MULTI_NL = re.compile(r"\n{3,}")

# Common PDF ligature replacements
_LIGATURES: dict[str, str] = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
}


def _clean_text(text: str) -> str:
    """Remove PDF extraction artefacts and normalise whitespace."""
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)
    text = _GLYPH_RE.sub("", text)
    text = _MULTI_WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


def _extract_search_queries(
    text: str,
    max_queries: int = 8,
) -> list[str]:
    """Extract meaningful search queries from document text.

    Strategy:
      1. Chunk text with reasonable size for diverse coverage.
      2. From each sampled chunk, pull the first complete sentence.
      3. Return cleaned, non-trivial queries suitable for web search.
    """
    cleaned = _clean_text(text)
    chunk_result = chunk_text(cleaned, chunk_size=500, overlap=0)
    chunks = chunk_result["chunks"]

    if not chunks:
        return []

    step = max(1, len(chunks) // max_queries)
    queries: list[str] = []

    for i in range(0, len(chunks), step):
        raw = chunks[i].strip()

        # Extract first complete sentence (ending in . ! or ?)
        sent_match = re.match(r"(.+?[.!?])(?:\s|$)", raw, re.DOTALL)
        if sent_match:
            q = sent_match.group(1).strip()
        else:
            # No sentence boundary — take first 120 chars at word boundary
            q = raw[:120].rsplit(" ", 1)[0].strip()

        # Collapse internal newlines to spaces
        q = q.replace("\n", " ").replace("\r", " ")
        q = _MULTI_WS.sub(" ", q).strip()

        # Only keep queries with enough meaningful content
        if len(q) >= 20:
            queries.append(q[:settings.web_query_max_length])
        if len(queries) >= max_queries:
            break

    return queries


class WebSearchAgent(BaseAgent):
    """Queries search APIs to find matching content on the web."""

    @property
    def name(self) -> str:
        return "web_search_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        # --- 1. Create search queries from document text ----------------------
        max_q = agent_input.max_queries or settings.web_search_max_queries
        queries = _extract_search_queries(
            agent_input.text,
            max_queries=max_q,
        )

        if not queries:
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.3,
                flagged_passages=[],
                details={"status": "no_chunks", "reason": "Document too short to search"},
            )

        # Also prepare document chunks for embedding comparison
        cleaned_text = _clean_text(agent_input.text)
        doc_chunk_result = chunk_text(cleaned_text, chunk_size=500, overlap=50)
        doc_chunks = doc_chunk_result["chunks"]

        if not doc_chunks:
            doc_chunks = queries  # fallback

        # --- 2. Search the web ------------------------------------------------
        self.logger.info(
            "web_search_started",
            document_id=agent_input.document_id,
            query_count=len(queries),
        )
        search_result = await search_multiple(
            queries, count_per_query=settings.web_search_results_per_query,
            language=agent_input.language,
        )

        web_results = search_result.get("results", [])
        if not web_results:
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.3,
                flagged_passages=[],
                details={
                    "status": "no_matches",
                    "queries_searched": len(queries),
                },
            )

        # --- 3. Fetch actual page content for top URLs ------------------------
        # This dramatically improves similarity by comparing against real
        # page text instead of just short search snippets.
        urls_to_fetch = [r["url"] for r in web_results[:15] if r.get("url")]
        self.logger.info(
            "fetching_page_content",
            document_id=agent_input.document_id,
            url_count=len(urls_to_fetch),
        )
        page_texts = await fetch_page_text(urls_to_fetch, timeout=10.0)

        # Enrich each web_result with fetched page text
        for r in web_results:
            fetched = page_texts.get(r.get("url", ""), "")
            if fetched and len(fetched) > 100:
                cleaned = _clean_text(fetched)
                # Store full text for fingerprinting (up to 50K)
                r["raw_full_text"] = cleaned[:50000]
                # Truncated version for embedding comparison
                r["full_text"] = cleaned[:settings.page_content_length]
            else:
                r["full_text"] = ""
                r["raw_full_text"] = ""

        # --- 4. Compare content via embeddings --------------------------------
        # Build reference texts: prefer fetched page content, fall back to snippet
        snippet_indices: list[int] = []
        comparison_texts: list[str] = []
        for idx, r in enumerate(web_results):
            ref_text = r.get("full_text") or r.get("snippet", "")
            if ref_text and len(ref_text.strip()) > 20:
                snippet_indices.append(idx)
                comparison_texts.append(ref_text.strip())

        if not comparison_texts:
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.3,
                flagged_passages=[],
                details={"status": "no_snippets"},
            )

        doc_embeddings = await generate_embeddings(doc_chunks)
        ref_embeddings = await generate_embeddings(comparison_texts)

        sim_matrix = cosine_similarity_matrix(doc_embeddings, ref_embeddings)
        web_threshold = settings.web_search_similarity_threshold
        score_info = compute_overall_score(
            sim_matrix, threshold=web_threshold,
        )

        # --- 5. Build flagged passages ----------------------------------------
        flagged: list[FlaggedPassage] = []
        # Track which sources have already been flagged (avoid duplicates)
        seen_sources: set[str] = set()

        for i in range(sim_matrix.shape[0]):
            best_j = int(np.argmax(sim_matrix[i]))
            best_sim = float(min(sim_matrix[i, best_j], 1.0))  # clamp FP rounding
            if best_sim >= web_threshold:
                # Map index back to original web_results index
                orig_idx = snippet_indices[best_j]
                source_url = web_results[orig_idx].get("url", "")

                flagged.append(FlaggedPassage(
                    text=doc_chunks[i][:settings.passage_display_length],
                    similarity_score=best_sim,
                    source=source_url,
                    reason=(
                        f"Chunk matches web source with {best_sim:.0%} similarity: "
                        f"{web_results[orig_idx].get('title', 'Unknown')}"
                    ),
                ))
                seen_sources.add(source_url)

        confidence = min(len(web_results) / 10, 1.0) * 0.6 + 0.2

        # --- 5b. N-gram fingerprint matching (catches exact copies) -----------
        ref_full_texts = []
        _ref_to_web_idx = []  # maps ref_full_texts index → web_results index
        for i, r in enumerate(web_results):
            ft = r.get("raw_full_text", "")
            if ft:
                ref_full_texts.append(ft)
                _ref_to_web_idx.append(i)

        fp_result = fingerprint_match_score(
            cleaned_text, ref_full_texts, threshold=0.04,
        )
        fp_score = fp_result["score"]

        # Boost flagged passages from fingerprint matches
        for fm in fp_result.get("matches", [])[:5]:
            ref_idx = fm["ref_index"]
            if ref_idx < len(_ref_to_web_idx):
                orig_idx = _ref_to_web_idx[ref_idx]
                src_url = web_results[orig_idx].get("url", "")
                if src_url not in seen_sources:
                    flagged.append(FlaggedPassage(
                        text=f"[Exact-match fingerprint] Jaccard: {fm['jaccard']:.2%}",
                        similarity_score=min(fm["jaccard"] * 5, 1.0),
                        source=src_url,
                        reason=(
                            f"Exact text overlap detected via fingerprinting "
                            f"(Jaccard: {fm['jaccard']:.2%}) with: "
                            f"{web_results[orig_idx].get('title', 'Unknown')}"
                        ),
                    ))
                    seen_sources.add(src_url)

        # Combine embedding score and fingerprint score (max wins)
        final_score = max(score_info["score"], fp_score)

        # Build a map from web_results index → column in sim_matrix
        snippet_col: dict[int, int] = {
            orig: col for col, orig in enumerate(snippet_indices)
        }

        self.logger.info(
            "web_search_complete",
            document_id=agent_input.document_id,
            embedding_score=score_info["score"],
            fingerprint_score=fp_score,
            final_score=final_score,
            flagged_count=len(flagged),
            web_results=len(web_results),
        )

        return AgentOutput(
            agent_name=self.name,
            score=final_score,
            confidence=round(confidence, 2),
            flagged_passages=flagged,
            details={
                "status": "completed",
                "queries_searched": len(queries),
                "web_results_found": len(web_results),
                "pages_fetched": sum(1 for r in web_results if r.get("full_text")),
                "embedding_score": score_info["score"],
                "fingerprint_score": fp_score,
                "fingerprint_max_jaccard": fp_result.get("max_jaccard", 0),
                "sources": [
                    {
                        "url": r["url"],
                        "title": r["title"],
                        "similarity": round(
                            float(sim_matrix[:, snippet_col[idx]].max()), 4
                        )
                        if idx in snippet_col
                        else 0.0,
                    }
                    for idx, r in enumerate(web_results[:20])
                ],
            },
        )
