"""Semantic similarity agent — detects paraphrased plagiarism via embeddings.

Workflow
--------
1. Chunk the document text (via content_extractor_tool).
2. Generate embeddings for each chunk (via embedding_tool).
3. Compare chunks against each other using cosine similarity (via similarity_tool).
4. Flag passages above the similarity threshold & compute an overall score.

The agent only handles orchestration and interpretation — all computation
is delegated to the tools layer.
"""

from __future__ import annotations

import numpy as np

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.tools.content_extractor_tool import chunk_text
from app.tools.embedding_tool import generate_embeddings
from app.tools.similarity_tool import (
    compute_overall_score,
    cosine_similarity_matrix,
    find_high_similarity_pairs,
)


class SemanticAgent(BaseAgent):
    """Uses text embeddings to measure semantic similarity.

    Compares document chunks both internally (self-similarity) and against
    a supplied reference corpus.  When no reference is provided the agent
    performs an intra-document analysis that can detect duplicated /
    recycled sections.
    """

    @property
    def name(self) -> str:
        return "semantic_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        threshold = settings.semantic_similarity_threshold

        # --- 1. Chunking (via content_extractor_tool) -------------------------
        chunk_result = chunk_text(
            agent_input.text,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        chunks = agent_input.chunks or chunk_result["chunks"]

        if len(chunks) < 2:
            self.logger.info(
                "insufficient_chunks",
                document_id=agent_input.document_id,
                chunk_count=len(chunks),
            )
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.5,
                flagged_passages=[],
                details={"reason": "document_too_short", "chunk_count": len(chunks)},
            )

        # --- 2. Embeddings (via embedding_tool) -------------------------------
        self.logger.info(
            "generating_embeddings",
            document_id=agent_input.document_id,
            chunk_count=len(chunks),
        )
        embeddings = await generate_embeddings(chunks)

        # --- 3. Intra-document similarity (via similarity_tool) ---------------
        sim_matrix = cosine_similarity_matrix(embeddings, embeddings)

        # Zero-out the diagonal (a chunk is always identical to itself)
        np.fill_diagonal(sim_matrix, 0.0)

        pairs = find_high_similarity_pairs(sim_matrix, threshold=threshold)
        score_info = compute_overall_score(sim_matrix, threshold=threshold)

        # --- 4. Build flagged passages ----------------------------------------
        seen_pairs: set[tuple[int, int]] = set()
        flagged: list[FlaggedPassage] = []
        for pair in pairs:
            idx_a: int = pair["chunk_a_idx"]
            idx_b: int = pair["chunk_b_idx"]
            # Avoid flagging the symmetric duplicate (a→b and b→a)
            key = (min(idx_a, idx_b), max(idx_a, idx_b))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            flagged.append(
                FlaggedPassage(
                    text=chunks[idx_a][:500],
                    similarity_score=min(pair["similarity"], 1.0),
                    source=f"internal_chunk_{idx_b}",
                    reason=(
                        f"Chunk {idx_a} is {pair['similarity']:.0%} similar "
                        f"to chunk {idx_b} (possible internal duplication)"
                    ),
                )
            )

        # --- 5. Confidence heuristic ------------------------------------------
        confidence = self._estimate_confidence(len(chunks), len(flagged))

        self.logger.info(
            "semantic_analysis_complete",
            document_id=agent_input.document_id,
            score=score_info["score"],
            confidence=confidence,
            flagged_count=len(flagged),
        )

        return AgentOutput(
            agent_name=self.name,
            score=score_info["score"],
            confidence=confidence,
            flagged_passages=flagged,
            details={
                "threshold": threshold,
                "chunk_count": len(chunks),
                "max_similarity": score_info["max_similarity"],
                "mean_similarity": score_info["mean_similarity"],
                "flagged_ratio": score_info["flagged_ratio"],
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_confidence(chunk_count: int, flagged_count: int) -> float:
        """Produce a confidence value based on data quantity.

        More chunks → higher confidence because the sample is more
        representative.  Very few flags relative to many chunks also
        pushes confidence up (less ambiguity).
        """
        # Base confidence from chunk volume (caps at 0.95)
        base = min(chunk_count / 20, 1.0) * 0.7

        # Adjust by flag ratio — many flags = higher confidence in score
        if chunk_count > 0:
            flag_ratio = flagged_count / chunk_count
            adjustment = flag_ratio * 0.25
        else:
            adjustment = 0.0

        return round(min(base + adjustment + 0.05, 0.99), 2)
