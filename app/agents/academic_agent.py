"""Academic agent — compares text against academic papers.

Workflow
--------
1. Extract representative queries from the document.
2. Search OpenAlex (primary) or Google Scholar (fallback) for papers.
3. Compare document chunks against paper abstracts via embeddings.
4. Flag passages with high similarity to known publications.

Delegates all computation to the tools layer.
"""

from __future__ import annotations

import re

import numpy as np

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.tools.content_extractor_tool import chunk_text
from app.tools.embedding_tool import generate_embeddings
from app.tools.openalex_tool import search_openalex_multi
from app.tools.arxiv_tool import search_arxiv_multi
from app.tools.scholar_tool import search_scholar_multi
from app.tools.similarity_tool import cosine_similarity_matrix
from app.tools.relevance_scorer import score_relevance
from app.tools.fingerprint_tool import (
    idf_filtered_phrase_overlap,
    idf_weighted_phrase_hits,
    build_idf_table,
    longest_common_token_substring,
)


def _extract_queries(chunks: list[str], max_queries: int = 8) -> list[str]:
    """Extract meaningful search queries from document chunks.

    Strategy:
      1. Pick evenly-spaced chunks for diversity.
      2. Extract the first complete sentence (rather than arbitrary 120 chars)
         so Scholar receives coherent search terms.
      3. Strip very short or stop-word-heavy fragments.
    """
    if not chunks:
        return []

    import re

    step = max(1, len(chunks) // max_queries)
    queries: list[str] = []

    for i in range(0, len(chunks), step):
        raw = chunks[i].strip()

        # Extract first complete sentence (ending in . ! or ?)
        sent_match = re.match(r"(.+?[.!?])(?:\s|$)", raw)
        if sent_match:
            q = sent_match.group(1).strip()
        else:
            # No sentence boundary found — take first 100 chars at word boundary
            q = raw[:100].rsplit(" ", 1)[0].strip()

        # Ensure query has enough content to be a useful search term
        if len(q) >= 10:
            queries.append(q[:settings.max_query_length])  # Scholar handles up to ~256 chars
        if len(queries) >= max_queries:
            break

    return queries


class AcademicAgent(BaseAgent):
    """Compares uploaded text against academic papers via Google Scholar."""

    @property
    def name(self) -> str:
        return "academic_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        self.logger.info(
            "academic_analysis_started",
            document_id=agent_input.document_id,
        )

        # --- 1. Chunk the text ------------------------------------------------
        chunk_result = chunk_text(agent_input.text, chunk_size=settings.chunk_size)
        chunks = agent_input.chunks or chunk_result["chunks"]

        if len(chunks) < 2:
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.3,
                flagged_passages=[],
                details={"status": "document_too_short", "chunk_count": len(chunks)},
            )

        # --- 2. Search academic sources ------------------------------------
        max_q = agent_input.max_queries or settings.scholar_max_queries
        queries = _extract_queries(chunks, max_queries=max_q)
        self.logger.info(
            "academic_queries_prepared",
            document_id=agent_input.document_id,
            query_count=len(queries),
        )

        # -- 2a. Try OpenAlex first (free, reliable, no blocking) --
        papers: list[dict] = []
        source_used = "openalex"
        try:
            openalex_result = await search_openalex_multi(
                queries, max_per_query=settings.scholar_results_per_query,
            )
            papers = openalex_result.get("results", [])
            self.logger.info(
                "openalex_search_done",
                document_id=agent_input.document_id,
                papers_found=len(papers),
                elapsed_s=openalex_result.get("elapsed_s"),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "openalex_search_failed",
                document_id=agent_input.document_id,
                error=str(exc),
            )

        # -- 2b. Try arXiv if OpenAlex returned few results --
        if len(papers) < 3:
            try:
                arxiv_result = await search_arxiv_multi(
                    queries, max_per_query=settings.scholar_results_per_query,
                )
                arxiv_papers = arxiv_result.get("results", [])
                if arxiv_papers:
                    # Deduplicate by title against existing papers
                    existing_titles = {p.get("title", "").lower().strip() for p in papers}
                    for ap in arxiv_papers:
                        if ap["title"].lower().strip() not in existing_titles:
                            papers.append(ap)
                            existing_titles.add(ap["title"].lower().strip())
                    if source_used == "openalex":
                        source_used = "openalex+arxiv"
                    else:
                        source_used = "arxiv"
                    self.logger.info(
                        "arxiv_search_done",
                        document_id=agent_input.document_id,
                        papers_added=len(arxiv_papers),
                        total_papers=len(papers),
                    )
            except Exception as exc:
                self.logger.warning(
                    "arxiv_search_failed",
                    document_id=agent_input.document_id,
                    error=str(exc),
                )

        # -- 2c. Fallback to Google Scholar if OpenAlex+arXiv returned nothing --
        if not papers:
            source_used = "scholar"
            self.logger.info(
                "falling_back_to_scholar",
                document_id=agent_input.document_id,
                message="OpenAlex returned 0 results — trying Google Scholar.",
            )
            scholar_result = await search_scholar_multi(
                queries, max_per_query=settings.scholar_results_per_query,
                language=agent_input.language,
            )
            papers = scholar_result.get("results", [])

        # -- 2c. If both sources failed, fall back to intra-doc analysis --
        if not papers:
            self.logger.warning(
                "no_academic_results_falling_back",
                document_id=agent_input.document_id,
                message="Both OpenAlex and Google Scholar returned 0 papers. "
                        "Falling back to intra-document analysis.",
            )
            return await self._intra_document_analysis(
                agent_input.document_id, chunks
            )

        # --- 3. Rank papers by semantic relevance to the document --------
        query_sample = " ".join(chunks[:3])[:1000]
        try:
            papers = await score_relevance(
                query_sample, papers,
                text_key="abstract", fallback_key="title",
                min_score=0.10,
            )
            self.logger.info(
                "relevance_scoring_done",
                document_id=agent_input.document_id,
                papers_after_scoring=len(papers),
            )
        except Exception as exc:
            self.logger.warning(
                "relevance_scoring_failed",
                document_id=agent_input.document_id,
                error=str(exc),
            )

        # --- 4. Build paper corpus & embed ------------------------------------
        paper_texts: list[str] = []
        paper_meta: list[dict] = []
        for p in papers:
            text = p.get("abstract") or p.get("title", "")
            if text.strip():
                paper_texts.append(text)
                paper_meta.append(p)

        if not paper_texts:
            return await self._intra_document_analysis(
                agent_input.document_id, chunks
            )

        # Embed document chunks AND paper abstracts
        all_texts = chunks + paper_texts
        all_embeddings = await generate_embeddings(all_texts)

        doc_embeddings = all_embeddings[: len(chunks)]
        paper_embeddings = all_embeddings[len(chunks) :]

        # --- 4. Cross-similarity (doc chunks vs paper abstracts) --------------
        sim_matrix = cosine_similarity_matrix(doc_embeddings, paper_embeddings)

        # Use the full semantic threshold — do NOT lower it for abstracts.
        cross_threshold = settings.semantic_similarity_threshold
        flagged: list[FlaggedPassage] = []
        flagged_chunk_indices: set[int] = set()

        # Build per-request IDF over the candidate abstracts/titles
        idf_table = build_idf_table(paper_texts) if paper_texts else {}

        # Track per-source dedup (canonicalized DOI / URL)
        _DOI_PREFIX_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.I)
        _OPENALEX_PREFIX_RE = re.compile(r"^https?://openalex\.org/", re.I)

        def _canonical(p: dict) -> str:
            """Canonical key for paper dedup.

            Order of preference:
              1. bare DOI (10.xxxx/...) — most stable cross-provider key
              2. bare OpenAlex Work ID (Wxxxx)
              3. arXiv ID if present
              4. canonicalized URL (lowercase, no query/fragment)
            """
            doi = (p.get("doi") or "").strip()
            if doi:
                bare = _DOI_PREFIX_RE.sub("", doi).lower().rstrip("/")
                if bare:
                    return f"doi:{bare}"

            oa = (p.get("openalex_id") or "").strip()
            if oa:
                bare_oa = _OPENALEX_PREFIX_RE.sub("", oa).lower().rstrip("/")
                if bare_oa:
                    return f"openalex:{bare_oa}"

            arxiv = (p.get("arxiv_id") or "").strip().lower()
            if arxiv:
                return f"arxiv:{arxiv}"

            url = (p.get("url") or p.get("scholar_url") or "").lower()
            return url.split("?", 1)[0].split("#", 1)[0].rstrip("/")

        seen_sources: set[str] = set()

        # Track best evidence for confidence calculation
        best_hits = 0
        best_lcs = 0

        for i in range(sim_matrix.shape[0]):
            for j in range(sim_matrix.shape[1]):
                sim_val = float(min(sim_matrix[i, j], 1.0))  # clamp FP rounding
                if sim_val < cross_threshold:
                    continue

                paper = paper_meta[j]
                abstract = paper.get("abstract") or paper.get("title", "")
                chunk_snippet = chunks[i][:settings.passage_display_length]

                # IDF-weighted phrase overlap (per-request IDF over abstracts)
                hits = idf_weighted_phrase_hits(chunk_snippet, abstract, idf_table)

                # Longest common token substring for verbatim detection
                lcs = longest_common_token_substring(chunk_snippet, abstract)

                # HARD GATE (AND-logic, recalibrated for IDF-weighted hits):
                # IDF-weighted hits are stricter than the old static-list
                # count, so the academic threshold drops accordingly.
                # Strong-embed lane requires very high cosine + long verbatim.
                primary  = hits >= 2 and lcs >= 10
                strong   = sim_val >= 0.95 and lcs >= 15

                if not (primary or strong):
                    continue

                # Per-source dedup
                canon = _canonical(paper)
                if canon and canon in seen_sources:
                    continue

                flagged_chunk_indices.add(i)
                if canon:
                    seen_sources.add(canon)

                if hits > best_hits:
                    best_hits = hits
                if lcs > best_lcs:
                    best_lcs = lcs

                authors = paper.get("authors", [])
                author_str = (
                    ", ".join(authors[:3])
                    if isinstance(authors, list)
                    else str(authors)
                )
                year = paper.get("year", "")
                title = paper.get("title", "Unknown")

                if hits >= 4 and lcs >= 12:
                    match_quality = "Strong"
                elif hits >= 2 and lcs >= 10:
                    match_quality = "Moderate"
                else:
                    match_quality = "Weak"

                flagged.append(
                    FlaggedPassage(
                        text=chunk_snippet,
                        similarity_score=sim_val,
                        source=paper.get("url") or paper.get("openalex_id") or paper.get("scholar_url", ""),
                        reason=(
                            f"{match_quality} match ({sim_val:.0%} semantic, "
                            f"{hits} IDF-rare phrase{'s' if hits != 1 else ''}, "
                            f"LCS {lcs} words, abstract-only) "
                            f"with: \"{title}\" by {author_str} ({year})"
                        ),
                    )
                )

        # Score = % of chunks that matched a paper
        score = round(
            (len(flagged_chunk_indices) / len(chunks)) * 100, 2
        ) if chunks else 0.0

        # Evidence-based confidence (NOT paper-count). NO floor.
        if flagged:
            evidence = (
                min(best_hits / 5.0, 1.0) * 0.5
                + min(best_lcs / 15.0, 1.0) * 0.5
            )
            confidence = round(min(evidence, 1.0), 2)
        else:
            confidence = 0.0

        self.logger.info(
            "academic_analysis_complete",
            document_id=agent_input.document_id,
            score=score,
            source_used=source_used,
            papers_found=len(papers),
            flagged_count=len(flagged),
        )

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=round(confidence, 2),
            flagged_passages=flagged[:settings.flagged_passages_limit],  # cap to avoid huge responses
            details={
                "status": "completed",
                "source_used": source_used,
                "chunk_count": len(chunks),
                "papers_found": len(papers),
                "flagged_chunks": len(flagged_chunk_indices),
                "queries_used": queries,
            },
        )

    # ------------------------------------------------------------------
    # Fallback: intra-document analysis (original behaviour)
    # ------------------------------------------------------------------

    async def _intra_document_analysis(
        self, document_id: str, chunks: list[str]
    ) -> AgentOutput:
        """Detect recycled / repetitive sections within the document itself."""
        embeddings = await generate_embeddings(chunks)
        sim_matrix = cosine_similarity_matrix(embeddings, embeddings)
        np.fill_diagonal(sim_matrix, 0.0)

        threshold = settings.semantic_similarity_threshold
        flagged: list[FlaggedPassage] = []
        seen_pairs: set[tuple[int, int]] = set()

        for i in range(sim_matrix.shape[0]):
            for j in range(i + 1, sim_matrix.shape[1]):
                sim_val = float(min(sim_matrix[i, j], 1.0))  # clamp FP rounding
                if sim_val >= threshold:
                    pair = (i, j)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        flagged.append(
                            FlaggedPassage(
                                text=chunks[i][:500],
                                similarity_score=sim_val,
                                source=f"academic_section_{j}",
                                reason=(
                                    f"Section {i} has {sim_val:.0%} similarity "
                                    f"with section {j} — possible structural "
                                    f"repetition"
                                ),
                            )
                        )

        unique_flagged = len(
            set(idx for pair in seen_pairs for idx in pair)
        )
        score = (
            round((unique_flagged / len(chunks)) * 100, 2) if chunks else 0.0
        )
        confidence = min(len(chunks) / 20, 1.0) * 0.5 + 0.1

        self.logger.info(
            "academic_intra_analysis_complete",
            document_id=document_id,
            score=score,
            flagged_count=len(flagged),
        )

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=round(confidence, 2),
            flagged_passages=flagged,
            details={
                "status": "completed_intra_only",
                "chunk_count": len(chunks),
                "flagged_pairs": len(seen_pairs),
                "note": "No Scholar results — used intra-document analysis",
            },
        )
