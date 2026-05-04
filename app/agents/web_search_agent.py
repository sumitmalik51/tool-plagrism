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
from app.tools.fingerprint_tool import (
    fingerprint_match_score,
    fingerprint_chunks,
    idf_filtered_phrase_overlap,
    idf_weighted_phrase_hits,
    build_idf_table,
    longest_common_token_substring,
)


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

_GLYPH_RE = re.compile(r"/gid\d{3,5}")
_MULTI_WS = re.compile(r"[ \t]+")
_MULTI_NL = re.compile(r"\n{3,}")


def _canonical_url(u: str) -> str:
    """Lowercase, strip query/fragment & trailing slash for dedup."""
    if not u:
        return ""
    return u.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()

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
            timed_out = bool(search_result.get("timed_out"))
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.0 if timed_out else 0.3,
                flagged_passages=[],
                details={
                    "status": "timed_out" if timed_out else "no_matches",
                    **({
                        "agent_failed": True,
                        "error": "Web search timed out before returning results.",
                    } if timed_out else {}),
                    "queries_searched": len(queries),
                },
            )

        # --- 3. Fetch actual page content for top URLs ------------------------
        # This dramatically improves similarity by comparing against real
        # page text instead of just short search snippets.
        urls_to_fetch = [r["url"] for r in web_results[:8] if r.get("url")]
        self.logger.info(
            "fetching_page_content",
            document_id=agent_input.document_id,
            url_count=len(urls_to_fetch),
        )
        page_texts = await fetch_page_text(urls_to_fetch, timeout=6.0, max_concurrent=8)

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

        # ═══════════════════════════════════════════════════════════════════
        # MULTI-STAGE SOURCE VALIDATION PIPELINE
        # Stage 1: Embedding retrieval  (candidates — already in sim_matrix)
        # Stage 2: Lexical validation   (hard gate — IDF-filtered phrase overlap + LCS)
        # Stage 3: Fingerprint match    (validate — n-gram Jaccard)
        # Stage 4: Confidence scoring   (AND logic — require lexical evidence)
        # ═══════════════════════════════════════════════════════════════════

        # --- Stage 1: Retrieve embedding candidates --------------------------
        candidates: list[dict] = []
        for i in range(sim_matrix.shape[0]):
            best_j = int(np.argmax(sim_matrix[i]))
            best_sim = float(min(sim_matrix[i, best_j], 1.0))
            if best_sim >= web_threshold:
                orig_idx = snippet_indices[best_j]
                candidates.append({
                    "chunk_idx": i,
                    "ref_idx": orig_idx,
                    "embedding_sim": best_sim,
                    "chunk_text": doc_chunks[i][:settings.passage_display_length],
                    "source_url": web_results[orig_idx].get("url", ""),
                    "source_title": web_results[orig_idx].get("title", "Unknown"),
                })

        # --- Stage 2: Lexical validation (HARD GATE, AND-logic) -------------
        # Real per-request IDF over the candidate corpus + LCS.
        # Rejects candidates that have high embedding similarity but no
        # actual textual overlap (same topic, different text).
        #
        # Build IDF over the small candidate corpus (10-30 docs) — cheap.
        idf_corpus = [
            (r.get("raw_full_text") or r.get("full_text") or "")
            for r in web_results
            if (r.get("raw_full_text") or r.get("full_text"))
        ]
        idf_table = build_idf_table(idf_corpus) if idf_corpus else {}

        for cand in candidates:
            source_full = web_results[cand["ref_idx"]].get("raw_full_text", "") \
                          or web_results[cand["ref_idx"]].get("full_text", "")
            if source_full:
                cand["phrase_hits"] = idf_weighted_phrase_hits(
                    cand["chunk_text"], source_full, idf_table,
                )
                cand["lcs_len"] = longest_common_token_substring(
                    cand["chunk_text"], source_full[:5000],
                )
            else:
                cand["phrase_hits"] = 0
                cand["lcs_len"] = 0

        # --- Stage 3: Document-level fingerprint validation ------------------
        ref_full_texts = []
        _ref_to_web_idx: list[int] = []
        for i, r in enumerate(web_results):
            ft = r.get("raw_full_text", "")
            if ft:
                ref_full_texts.append(ft)
                _ref_to_web_idx.append(i)

        import asyncio as _aio
        _loop = _aio.get_running_loop()
        fp_result = await _loop.run_in_executor(
            None, fingerprint_match_score,
            cleaned_text, ref_full_texts,
        )

        # Build set of source URLs that have document-level fingerprint overlap
        fp_urls_with_overlap: set[str] = set()
        for fm in fp_result.get("matches", []):
            ref_idx = fm["ref_index"]
            if ref_idx < len(_ref_to_web_idx):
                fp_urls_with_overlap.add(
                    web_results[_ref_to_web_idx[ref_idx]].get("url", "")
                )

        # Capture fp_score for downstream logging / response.
        fp_score = fp_result.get("score", 0.0)

        # --- Stage 4: Hard validation gate (AND-logic) -----------------------
        # A candidate is promoted ONLY if it has lexical evidence:
        #   PRIMARY:     phrase_hits >= 1 AND lcs >= 8     (IDF-weighted)
        #   FINGERPRINT: source has document-level Jaccard overlap
        #   STRONG-EMBED: sim >= 0.95 AND lcs >= 15        (verbatim-grade
        #                 alignment that fingerprinting may have missed
        #                 because the fetched page differs slightly from
        #                 the indexed copy)
        # Pure embedding matches with weak lexical evidence are rejected.
        flagged: list[FlaggedPassage] = []
        flagged_canon_urls: set[str] = set()  # canonical URL → de-dup
        promoted_cands: list[dict] = []        # for confidence calc

        for cand in candidates:
            hits = cand["phrase_hits"]
            lcs  = cand["lcs_len"]
            sim  = cand["embedding_sim"]
            has_fp = cand["source_url"] in fp_urls_with_overlap

            primary_lex   = hits >= 1 and lcs >= 8
            strong_embed  = sim >= 0.95 and lcs >= 15

            if not (primary_lex or has_fp or strong_embed):
                continue  # HARD GATE — no attribution without evidence

            # Per-source dedup
            canon = _canonical_url(cand["source_url"])
            if canon in flagged_canon_urls:
                continue

            # Confidence tiers (recalibrated for IDF-weighted hits)
            if hits >= 4 and lcs >= 12 and has_fp:
                match_quality = "strong"
            elif hits >= 2 and lcs >= 10:
                match_quality = "moderate"
            elif primary_lex or has_fp:
                match_quality = "weak"
            else:
                match_quality = "marginal"

            # match_type: kind of overlap (exact / paraphrase / semantic).
            # Drives the chip + icon in the UI separately from severity.
            if has_fp or lcs >= 15:
                match_type = "exact"
            elif hits >= 2 and lcs >= 8:
                match_type = "paraphrase"
            else:
                match_type = "semantic"

            flagged.append(FlaggedPassage(
                text=cand["chunk_text"],
                similarity_score=sim,
                source=cand["source_url"],
                reason=(
                    f"{match_quality.title()} match ({sim:.0%} semantic, "
                    f"{hits} IDF-rare phrase{'s' if hits != 1 else ''}, "
                    f"LCS {lcs} words"
                    f"{', fingerprint' if has_fp else ''}): "
                    f"{cand['source_title']}"
                ),
                match_type=match_type,
            ))
            flagged_canon_urls.add(canon)
            promoted_cands.append(cand)

        # --- Also flag fingerprint-only matches (exact copies) ----------------
        # Track each fp-only match's Jaccard so confidence reflects them
        # even when no Stage-4 candidate was promoted (e.g. fetched page
        # excerpt didn't include the high-Jaccard window).
        fp_only_jaccards: list[float] = []
        for fm in fp_result.get("matches", [])[:5]:
            ref_idx = fm["ref_index"]
            if ref_idx < len(_ref_to_web_idx):
                orig_idx = _ref_to_web_idx[ref_idx]
                src_url = web_results[orig_idx].get("url", "")
                canon = _canonical_url(src_url)
                if canon and canon not in flagged_canon_urls:
                    jac = float(fm["jaccard"])
                    fp_only_jaccards.append(jac)
                    flagged.append(FlaggedPassage(
                        text=f"[Exact-match fingerprint] Jaccard: {jac:.2%}",
                        similarity_score=min(jac * 5, 1.0),
                        source=src_url,
                        reason=(
                            f"Exact text overlap via fingerprinting "
                            f"(Jaccard: {jac:.2%}): "
                            f"{web_results[orig_idx].get('title', 'Unknown')}"
                        ),
                        match_type="exact",
                    ))
                    flagged_canon_urls.add(canon)

        # --- Evidence-based confidence (NOT result-count) --------------------
        # Confidence reflects the strongest evidence collected from
        # *promoted* candidates only — rejected candidates can no longer
        # inflate the confidence score.  Fingerprint-only matches contribute
        # via their Jaccard so a verbatim copy that bypassed Stage-4 still
        # registers high confidence.  No floor: zero evidence => 0.
        if flagged:
            best_hits = max((c["phrase_hits"] for c in promoted_cands), default=0)
            best_lcs  = max((c["lcs_len"]    for c in promoted_cands), default=0)
            cand_evidence = (
                min(best_hits / 5.0, 1.0) * 0.45
                + min(best_lcs / 15.0, 1.0) * 0.45
                + (0.10 if fp_score >= 30.0 else 0.0)
            )
            # Fingerprint-only evidence: Jaccard 0.20 → 0.6, 0.33+ → 1.0
            fp_evidence = min(max(fp_only_jaccards, default=0.0) * 3.0, 1.0)
            confidence = round(min(max(cand_evidence, fp_evidence), 1.0), 2)
        else:
            confidence = 0.0

        # Score: AND logic — only count validated matches.
        # Use canonicalized URL comparison to stay consistent with dedup.
        fp_canon_urls = {_canonical_url(u) for u in fp_urls_with_overlap}
        validated_chunk_idxs = {
            c["chunk_idx"] for c in candidates
            if (c["phrase_hits"] >= 1 and c["lcs_len"] >= 8)
            or _canonical_url(c["source_url"]) in fp_canon_urls
            or (c["embedding_sim"] >= 0.95 and c["lcs_len"] >= 15)
        }
        if doc_chunks:
            validated_score = round(
                (len(validated_chunk_idxs) / len(doc_chunks)) * 100, 2
            )
        else:
            validated_score = 0.0

        # Take the lower of embedding and validated score (AND logic)
        final_score = min(score_info["score"], validated_score) if flagged else 0.0

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

        # Empty-state classification — distinguishes the three trust-critical
        # cases for the UI: nothing found vs. weak-only vs. corpus-uncovered.
        if flagged:
            empty_reason: str | None = None
        elif not candidates:
            empty_reason = "no_corpus"  # retrieval returned no comparable text
        elif any(c["embedding_sim"] >= 0.40 for c in candidates):
            empty_reason = "weak_only"  # candidates existed but failed the gate
        else:
            empty_reason = "no_matches"

        return AgentOutput(
            agent_name=self.name,
            score=final_score,
            confidence=round(confidence, 2),
            flagged_passages=flagged,
            details={
                "status": "completed",
                "empty_reason": empty_reason,
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
