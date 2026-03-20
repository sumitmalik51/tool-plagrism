"""Academic agent — compares text with academic corpus.

Delegates computation to the tools layer. Currently uses embedding-based
similarity for local analysis. Can be extended with academic database APIs
(CrossRef, Semantic Scholar, etc.).
"""

from __future__ import annotations

import numpy as np

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.tools.content_extractor_tool import chunk_text
from app.tools.embedding_tool import generate_embeddings
from app.tools.similarity_tool import cosine_similarity_matrix


class AcademicAgent(BaseAgent):
    """Compares uploaded text against academic paper databases."""

    @property
    def name(self) -> str:
        return "academic_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        self.logger.info(
            "academic_analysis_started",
            document_id=agent_input.document_id,
        )

        # --- 1. Chunk the text (via content_extractor_tool) -------------------
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

        # --- 2. Detect academic-style repetition patterns ---------------------
        # Without external API, detect citation-heavy and formulaic passages
        # using self-similarity as a proxy for template-based writing
        embeddings = await generate_embeddings(chunks)
        sim_matrix = cosine_similarity_matrix(embeddings, embeddings)
        np.fill_diagonal(sim_matrix, 0.0)

        # Look for highly similar sections (potential self-plagiarism / recycled content)
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
                        flagged.append(FlaggedPassage(
                            text=chunks[i][:300],
                            similarity_score=sim_val,
                            source=f"academic_section_{j}",
                            reason=(
                                f"Section {i} has {sim_val:.0%} similarity with "
                                f"section {j} — possible structural repetition"
                            ),
                        ))

        # Score based on ratio of flagged chunks
        unique_flagged = len(set(
            idx for pair in seen_pairs for idx in pair
        ))
        score = round((unique_flagged / len(chunks)) * 100, 2) if chunks else 0.0
        confidence = min(len(chunks) / 20, 1.0) * 0.5 + 0.1

        self.logger.info(
            "academic_analysis_complete",
            document_id=agent_input.document_id,
            score=score,
            flagged_count=len(flagged),
        )

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=round(confidence, 2),
            flagged_passages=flagged,
            details={
                "status": "completed",
                "chunk_count": len(chunks),
                "flagged_pairs": len(seen_pairs),
                "note": "Academic DB integration pending — using embedding analysis",
            },
        )
