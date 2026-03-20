"""Web search agent — searches web sources for matching content.

Delegates all computation to the tools layer (web_search_tool, embedding_tool,
similarity_tool). The agent only handles orchestration and interpretation.
"""

from __future__ import annotations

from app.agents.base_agent import BaseAgent
from app.config import settings
from app.models.schemas import AgentInput, AgentOutput, FlaggedPassage
from app.tools.content_extractor_tool import chunk_text
from app.tools.embedding_tool import generate_embeddings
from app.tools.similarity_tool import cosine_similarity_matrix, compute_overall_score
from app.tools.web_search_tool import search_multiple


class WebSearchAgent(BaseAgent):
    """Queries search APIs to find matching content on the web."""

    @property
    def name(self) -> str:
        return "web_search_agent"

    async def _analyze(self, agent_input: AgentInput) -> AgentOutput:
        # Check if Bing API key is configured
        if not settings.bing_api_key:
            self.logger.warning(
                "web_search_skipped",
                document_id=agent_input.document_id,
                reason="BING_API_KEY not configured",
            )
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.0,
                flagged_passages=[],
                details={"status": "skipped", "reason": "BING_API_KEY not configured"},
            )

        # --- 1. Create search queries from text chunks ------------------------
        chunk_result = chunk_text(agent_input.text, chunk_size=200, overlap=0)
        chunks = chunk_result["chunks"]

        # Use first few chunks as search queries (limit to avoid API abuse)
        query_chunks = chunks[:5]
        queries = [c[:150] for c in query_chunks]

        # --- 2. Search the web ------------------------------------------------
        self.logger.info(
            "web_search_started",
            document_id=agent_input.document_id,
            query_count=len(queries),
        )
        search_result = await search_multiple(queries, count_per_query=3)

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

        # --- 3. Compare snippets via embeddings (similarity_tool) -------------
        snippets = [r["snippet"] for r in web_results if r.get("snippet")]
        if not snippets:
            return AgentOutput(
                agent_name=self.name,
                score=0.0,
                confidence=0.3,
                flagged_passages=[],
                details={"status": "no_snippets"},
            )

        doc_embeddings = await generate_embeddings(query_chunks)
        snippet_embeddings = await generate_embeddings(snippets)

        sim_matrix = cosine_similarity_matrix(doc_embeddings, snippet_embeddings)
        score_info = compute_overall_score(
            sim_matrix, threshold=settings.semantic_similarity_threshold,
        )

        # --- 4. Build flagged passages ----------------------------------------
        flagged: list[FlaggedPassage] = []
        import numpy as np

        for i in range(sim_matrix.shape[0]):
            best_j = int(np.argmax(sim_matrix[i]))
            best_sim = float(sim_matrix[i, best_j])
            if best_sim >= settings.semantic_similarity_threshold:
                flagged.append(FlaggedPassage(
                    text=query_chunks[i][:300],
                    similarity_score=best_sim,
                    source=web_results[best_j].get("url", ""),
                    reason=(
                        f"Chunk matches web source with {best_sim:.0%} similarity: "
                        f"{web_results[best_j].get('title', 'Unknown')}"
                    ),
                ))

        confidence = min(len(web_results) / 10, 1.0) * 0.6 + 0.2

        self.logger.info(
            "web_search_complete",
            document_id=agent_input.document_id,
            score=score_info["score"],
            flagged_count=len(flagged),
            web_results=len(web_results),
        )

        return AgentOutput(
            agent_name=self.name,
            score=score_info["score"],
            confidence=round(confidence, 2),
            flagged_passages=flagged,
            details={
                "status": "completed",
                "queries_searched": len(queries),
                "web_results_found": len(web_results),
                "sources": [
                    {"url": r["url"], "title": r["title"], "similarity": 0.0}
                    for r in web_results[:10]
                ],
            },
        )
