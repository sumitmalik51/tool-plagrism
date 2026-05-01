"""Tests for the web search agent — uses mocked web search & embeddings."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from app.agents.web_search_agent import WebSearchAgent, _clean_text, _extract_search_queries
from app.models.schemas import AgentInput


def _make_embeddings(n: int, dim: int = 384) -> np.ndarray:
    rng = np.random.default_rng(42)
    vecs = rng.random((n, dim), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norms


# ---------------------------------------------------------------------------
# Text-cleaning helper tests
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_removes_glyph_codes(self) -> None:
        assert _clean_text("word/gid00047other") == "wordother"

    def test_replaces_ligatures(self) -> None:
        assert "fl" in _clean_text("ﬂexible")
        assert "fi" in _clean_text("ﬁnding")
        assert "ff" in _clean_text("e\ufb00ect")

    def test_collapses_whitespace(self) -> None:
        assert _clean_text("hello   world") == "hello world"

    def test_collapses_excessive_newlines(self) -> None:
        result = _clean_text("para1\n\n\n\n\npara2")
        assert result == "para1\n\npara2"


class TestExtractSearchQueries:
    def test_extracts_sentences(self) -> None:
        text = "This is the first sentence. And the second one. Third sentence here."
        queries = _extract_search_queries(text, max_queries=3)
        assert len(queries) >= 1
        # Each query should be a proper sentence
        for q in queries:
            assert len(q) >= 20

    def test_respects_max_queries(self) -> None:
        long_text = "This is a complete sentence with enough words. " * 100
        queries = _extract_search_queries(long_text, max_queries=3)
        assert len(queries) <= 3

    def test_empty_text_returns_empty(self) -> None:
        assert _extract_search_queries("", max_queries=5) == []

    def test_cleans_pdf_artifacts_from_queries(self) -> None:
        text = "This is a sentence/gid00047 about ﬂexible devices. " * 20
        queries = _extract_search_queries(text, max_queries=2)
        for q in queries:
            assert "/gid" not in q
            assert "fl" in q.lower() or "flexible" in q.lower()


# ---------------------------------------------------------------------------
# Agent tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
async def test_web_search_agent_no_results(
    mock_embed: AsyncMock, mock_search: AsyncMock, mock_fetch: AsyncMock,
) -> None:
    """When search returns no results, score should be 0."""
    mock_search.return_value = {"results": [], "queries_searched": 3}
    mock_fetch.return_value = {}

    agent = WebSearchAgent()
    text = "This is a test document with enough content to chunk. " * 20
    result = await agent.run(AgentInput(document_id="doc-1", text=text))

    assert result.agent_name == "web_search_agent"
    assert result.score == 0.0
    assert result.details["status"] == "no_matches"


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
async def test_web_search_agent_with_snippets(
    mock_embed: AsyncMock, mock_search: AsyncMock, mock_fetch: AsyncMock,
) -> None:
    """When search returns snippets, agent should compute similarity."""
    mock_search.return_value = {
        "results": [
            {"url": "https://example.com/1", "title": "Result 1", "snippet": "This is a much longer snippet with enough content."},
            {"url": "https://example.com/2", "title": "Result 2", "snippet": "Another snippet with plenty of meaningful content here."},
        ],
        "queries_searched": 2,
    }
    mock_fetch.return_value = {
        "https://example.com/1": "Full page content from example one with lots of text about documents.",
        "https://example.com/2": "Full page content from example two about plagiarism detection systems.",
    }

    # Determine how many doc_chunks and ref texts the agent will compute
    # Doc chunks will be derived from the cleaned input text
    text = "This is a test document with enough content to chunk. " * 20
    # With chunk_size=500, overlap=50, this ~1060 char text produces ~3 chunks
    # 2 web results with full_text means 2 comparison texts
    mock_embed.side_effect = [
        _make_embeddings(3),  # doc embeddings
        _make_embeddings(2),  # comparison text embeddings
    ]

    agent = WebSearchAgent()
    result = await agent.run(AgentInput(document_id="doc-2", text=text))

    assert result.agent_name == "web_search_agent"
    assert result.score >= 0.0
    assert result.details["status"] == "completed"
    assert result.details["web_results_found"] == 2


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
async def test_web_search_agent_snippet_index_mapping(
    mock_embed: AsyncMock, mock_search: AsyncMock, mock_fetch: AsyncMock,
) -> None:
    """Ensure snippet-to-web_results index mapping is correct when some results lack useful text."""
    mock_search.return_value = {
        "results": [
            {"url": "https://a.com", "title": "No Snippet", "snippet": ""},
            {"url": "https://b.com", "title": "Has Snippet", "snippet": "Matching text here that is long enough to compare."},
        ],
        "queries_searched": 1,
    }
    mock_fetch.return_value = {
        "https://a.com": "",  # failed to fetch
        "https://b.com": "Full page content matching the document text closely.",
    }

    # Create high-similarity embeddings so the chunk matches the snippet
    high_sim = np.ones((1, 384), dtype=np.float32)
    high_sim /= np.linalg.norm(high_sim)

    text = "This is a test document with enough content to properly chunk and compare. " * 20
    # With chunk_size=500, this produces ~3 doc chunks
    # Only 1 comparison text (b.com has content, a.com doesn't)
    mock_embed.side_effect = [
        np.tile(high_sim, (3, 1)),  # doc embeddings
        high_sim,                    # 1 comparison text
    ]

    agent = WebSearchAgent()
    result = await agent.run(AgentInput(document_id="doc-3", text=text))

    # The flagged passage should reference https://b.com (the one WITH content)
    for fp in result.flagged_passages:
        assert fp.source == "https://b.com"


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock)
async def test_web_search_agent_no_snippets(
    mock_search: AsyncMock, mock_fetch: AsyncMock,
) -> None:
    """When results have no usable text, agent returns gracefully."""
    mock_search.return_value = {
        "results": [
            {"url": "https://a.com", "title": "No Snippet", "snippet": ""},
        ],
        "queries_searched": 1,
    }
    mock_fetch.return_value = {"https://a.com": ""}

    agent = WebSearchAgent()
    text = "This is a test document with enough content to chunk. " * 20
    result = await agent.run(AgentInput(document_id="doc-4", text=text))

    assert result.score == 0.0
    assert result.details["status"] == "no_snippets"


@pytest.mark.asyncio
async def test_web_search_agent_short_text() -> None:
    """Very short text that produces no queries should return gracefully."""
    agent = WebSearchAgent()
    result = await agent.run(AgentInput(document_id="doc-5", text="Hi."))

    assert result.score == 0.0


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
async def test_web_search_agent_page_content_used(
    mock_embed: AsyncMock, mock_search: AsyncMock, mock_fetch: AsyncMock,
) -> None:
    """Agent should prefer fetched page content over snippets."""
    mock_search.return_value = {
        "results": [
            {
                "url": "https://example.com/paper",
                "title": "Solar Cell Paper",
                "snippet": "Short snippet about solar panels.",
            },
        ],
        "queries_searched": 1,
    }
    mock_fetch.return_value = {
        "https://example.com/paper": (
            "This is the full text of a research paper about flexible inverted "
            "bulk-heterojunction organic solar cells with ZnO as an electron "
            "transport layer fabricated by sol-gel spin coating method."
        ),
    }

    text = "Research about flexible organic solar cells with ZnO layers. " * 20
    mock_embed.side_effect = [
        _make_embeddings(3),  # doc chunks
        _make_embeddings(1),  # 1 comparison text (full_text preferred)
    ]

    agent = WebSearchAgent()
    result = await agent.run(AgentInput(document_id="doc-6", text=text))

    assert result.details["status"] == "completed"
    assert result.details.get("pages_fetched", 0) >= 1


# ---------------------------------------------------------------------------
# M3: Negative gate test — same topic, different words must NOT be flagged
# Mirrors test_academic_agent_rejects_same_topic_different_words to lock in
# the false-positive fix for the web pipeline.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.agents.web_search_agent.fetch_page_text", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.search_multiple", new_callable=AsyncMock)
@patch("app.agents.web_search_agent.generate_embeddings", new_callable=AsyncMock)
async def test_web_search_agent_rejects_same_topic_different_words(
    mock_embed: AsyncMock, mock_search: AsyncMock, mock_fetch: AsyncMock,
) -> None:
    """High embedding similarity alone must NOT promote a candidate.

    The AND-gate requires lexical evidence: at least one IDF-rare 5-gram
    AND a 8-token verbatim run, OR a fingerprint hit, OR a verbatim-grade
    embedding (sim>=0.95 AND lcs>=15). A same-topic-but-different-words
    page must be rejected even when cosine similarity is forced to 1.0.
    """
    page_full_text = (
        "We present a novel transformer attention mechanism that "
        "outperforms existing baselines on multilingual translation tasks "
        "across diverse low-resource language pairs."
    )
    mock_search.return_value = {
        "results": [
            {
                "url": "https://example.com/paper",
                "title": "Transformer Attention for NMT",
                "snippet": page_full_text[:120],
            },
        ],
        "queries_searched": 1,
    }
    mock_fetch.return_value = {"https://example.com/paper": page_full_text}

    # Force ALL embeddings to be identical (cosine = 1.0)
    def _identical_embeddings(texts):
        n = len(texts) if hasattr(texts, "__len__") else 1
        base = np.ones((1, 384), dtype=np.float32)
        base /= np.linalg.norm(base)
        return np.tile(base, (n, 1))
    mock_embed.side_effect = _identical_embeddings

    # Same topic (NMT / translation) but completely different wording:
    # no shared 5-grams, no 8-token verbatim run with the page.
    chunks = [
        "Cross-lingual sequence models leverage shared embedding spaces "
        "to enable knowledge transfer between source and target languages.",
        "Recent advances in machine translation rely on large-scale "
        "pretraining over diverse parallel corpora and back-translation.",
        "Sparse routing approaches partition computation across language "
        "families, reducing parameter count without sacrificing quality.",
        "Evaluation on low-resource pairs requires careful metric choice "
        "since BLEU underestimates fluency for morphologically rich tongues.",
    ]
    text = " ".join(chunks)

    agent = WebSearchAgent()
    result = await agent.run(AgentInput(document_id="doc-neg-web", text=text))

    # The whole point: gate must reject — no flagged passages, zero score.
    assert result.flagged_passages == []
    assert result.score == 0.0
    # Confidence floor enforced (no evidence => 0)
    assert result.confidence == 0.0
