"""Academic agent — compares text against academic papers on Google Scholar.

Workflow
--------
1. Extract representative queries from the document.
2. Search Google Scholar for matching papers.
3. Compare document chunks against paper abstracts via embeddings.
4. Flag passages with high similarity to known publications.

Delegates all computation to the tools layer.
"""

from __future__ import annotations

import numpy as np

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.tools.content_extractor_tool import chunk_text
from app.tools.embedding_tool import generate_embeddings
from app.tools.scholar_tool import search_scholar_multi
from app.tools.similarity_tool import cosine_similarity_matrix


def _extract_queries(chunks: list[str], max_queries: int = 5) -> list[str]:
    """Pick representative chunks as Scholar search queries.

    Strategy: take evenly-spaced chunks and truncate to ~120 chars so
    they work well as search terms.
    """
    if not chunks:
        return []
    step = max(1, len(chunks) // max_queries)
    queries: list[str] = []
    for i in range(0, len(chunks), step):
        # Take the first meaningful sentence-like fragment
        q = chunks[i][:120].strip()
        if len(q) > 20:
            queries.append(q)
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

        # --- 2. Search Google Scholar -----------------------------------------
        queries = _extract_queries(chunks)
        self.logger.info(
            "scholar_queries_prepared",
            document_id=agent_input.document_id,
            query_count=len(queries),
        )

        scholar_result = await search_scholar_multi(queries, max_per_query=3)
        papers = scholar_result.get("results", [])

        if not papers:
            self.logger.info(
                "no_scholar_results",
                document_id=agent_input.document_id,
            )
            # Fall back to intra-document analysis
            return await self._intra_document_analysis(
                agent_input.document_id, chunks
            )

        # --- 3. Build paper corpus & embed ------------------------------------
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

        threshold = settings.semantic_similarity_threshold
        flagged: list[FlaggedPassage] = []
        flagged_chunk_indices: set[int] = set()

        for i in range(sim_matrix.shape[0]):
            for j in range(sim_matrix.shape[1]):
                sim_val = float(sim_matrix[i, j])
                if sim_val >= threshold:
                    flagged_chunk_indices.add(i)
                    paper = paper_meta[j]
                    authors = paper.get("authors", [])
                    author_str = (
                        ", ".join(authors[:3])
                        if isinstance(authors, list)
                        else str(authors)
                    )
                    year = paper.get("year", "")
                    title = paper.get("title", "Unknown")
                    flagged.append(
                        FlaggedPassage(
                            text=chunks[i][:300],
                            similarity_score=sim_val,
                            source=paper.get("url") or paper.get("scholar_url", ""),
                            reason=(
                                f"{sim_val:.0%} similarity with: \"{title}\" "
                                f"by {author_str} ({year})"
                            ),
                        )
                    )

        # Score = % of chunks that matched a paper
        score = round(
            (len(flagged_chunk_indices) / len(chunks)) * 100, 2
        ) if chunks else 0.0
        confidence = min(len(papers) / 10, 1.0) * 0.6 + 0.2

        self.logger.info(
            "academic_analysis_complete",
            document_id=agent_input.document_id,
            score=score,
            papers_found=len(papers),
            flagged_count=len(flagged),
        )

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=round(confidence, 2),
            flagged_passages=flagged[:20],  # cap to avoid huge responses
            details={
                "status": "completed",
                "chunk_count": len(chunks),
                "scholar_papers_found": len(papers),
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
                sim_val = float(sim_matrix[i, j])
                if sim_val >= threshold:
                    pair = (i, j)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        flagged.append(
                            FlaggedPassage(
                                text=chunks[i][:300],
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
