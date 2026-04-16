"""Tests for Research Writer arXiv + OpenAlex source enrichment."""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.services.auth_service import create_access_token, signup
from app.services.database import get_db

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _make_png(width=200, height=150, color=(100, 150, 200)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_b64_png(**kwargs) -> str:
    return base64.b64encode(_make_png(**kwargs)).decode()


@pytest.fixture(autouse=True)
def _clean_tables():
    db = get_db()
    for table in ("rw_cache", "rw_embeddings", "rw_versions"):
        try:
            db.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    from app.routes.research_writer import _burst_log
    _burst_log.clear()
    yield


def _create_test_user(email: str = "rw-src@test.com") -> int:
    db = get_db()
    db.execute("DELETE FROM usage_logs")
    try:
        db.execute("DELETE FROM users WHERE email = ?", (email,))
    except Exception:
        pass
    result = signup("RW Source Tester", email, "password123")
    return result["user"]["id"]


def _auth_headers(user_id: int, email: str = "rw-src@test.com") -> dict:
    token = create_access_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


_SAMPLE_ARXIV_RESPONSE = {
    "query": "machine learning",
    "results": [
        {
            "title": "Deep Learning for Image Recognition",
            "authors": ["Smith, J.", "Lee, K."],
            "year": "2023",
            "abstract": "We present a deep learning approach...",
            "venue": "arXiv (cs.CV)",
            "citation_count": 0,
            "url": "http://arxiv.org/abs/2301.12345",
            "arxiv_id": "2301.12345",
            "pdf_url": "http://arxiv.org/pdf/2301.12345",
            "category": "cs.CV",
        },
    ],
    "result_count": 1,
    "elapsed_s": 0.5,
}

_SAMPLE_OPENALEX_RESPONSE = {
    "query": "machine learning",
    "results": [
        {
            "title": "Neural Networks in Practice",
            "authors": ["Brown, A.", "Davis, M.", "Wilson, R."],
            "year": "2022",
            "abstract": "A practical guide to neural networks...",
            "venue": "Nature Machine Intelligence",
            "citation_count": 150,
            "url": "https://doi.org/10.1234/nmi.2022",
        },
    ],
    "result_count": 1,
    "elapsed_s": 0.3,
}


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: find_related_sources
# ═══════════════════════════════════════════════════════════════════════════


class TestFindRelatedSources:
    @pytest.mark.asyncio
    @patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
    @patch("app.tools.arxiv_tool.search_arxiv", new_callable=AsyncMock)
    async def test_combines_arxiv_and_openalex(self, mock_arxiv, mock_openalex):
        from app.tools.research_writer_tool import find_related_sources

        mock_arxiv.return_value = _SAMPLE_ARXIV_RESPONSE
        mock_openalex.return_value = _SAMPLE_OPENALEX_RESPONSE

        result = await find_related_sources("machine learning", max_results=10)

        assert result["source_count"] == 2
        sources = result["sources"]
        # OpenAlex comes first
        assert sources[0]["title"] == "Neural Networks in Practice"
        assert sources[0]["source"] == "openalex"
        assert sources[1]["title"] == "Deep Learning for Image Recognition"
        assert sources[1]["source"] == "arxiv"
        # Both have formatted citations
        for s in sources:
            assert "formatted_citation" in s
            assert len(s["formatted_citation"]) > 10

    @pytest.mark.asyncio
    @patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
    @patch("app.tools.arxiv_tool.search_arxiv", new_callable=AsyncMock)
    async def test_deduplicates_by_title(self, mock_arxiv, mock_openalex):
        from app.tools.research_writer_tool import find_related_sources

        shared_paper = {
            "title": "Shared Paper Title",
            "authors": ["Author A."],
            "year": "2023",
            "abstract": "...",
            "venue": "arXiv",
            "citation_count": 0,
            "url": "http://example.com",
        }
        mock_arxiv.return_value = {"results": [shared_paper]}
        mock_openalex.return_value = {"results": [shared_paper]}

        result = await find_related_sources("test")
        # Should only appear once (from OpenAlex, which comes first)
        assert result["source_count"] == 1

    @pytest.mark.asyncio
    @patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
    @patch("app.tools.arxiv_tool.search_arxiv", new_callable=AsyncMock)
    async def test_handles_arxiv_failure(self, mock_arxiv, mock_openalex):
        from app.tools.research_writer_tool import find_related_sources

        mock_arxiv.side_effect = RuntimeError("arXiv down")
        mock_openalex.return_value = _SAMPLE_OPENALEX_RESPONSE

        result = await find_related_sources("test")
        # Should still return OpenAlex results
        assert result["source_count"] == 1
        assert result["sources"][0]["source"] == "openalex"

    @pytest.mark.asyncio
    @patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
    @patch("app.tools.arxiv_tool.search_arxiv", new_callable=AsyncMock)
    async def test_handles_both_failures(self, mock_arxiv, mock_openalex):
        from app.tools.research_writer_tool import find_related_sources

        mock_arxiv.side_effect = RuntimeError("down")
        mock_openalex.side_effect = RuntimeError("down")

        result = await find_related_sources("test")
        assert result["source_count"] == 0
        assert result["sources"] == []

    @pytest.mark.asyncio
    @patch("app.tools.openalex_tool.search_openalex", new_callable=AsyncMock)
    @patch("app.tools.arxiv_tool.search_arxiv", new_callable=AsyncMock)
    async def test_respects_max_results(self, mock_arxiv, mock_openalex):
        from app.tools.research_writer_tool import find_related_sources

        papers = [
            {"title": f"Paper {i}", "authors": ["A"], "year": "2023",
             "abstract": "...", "venue": "arXiv", "citation_count": 0, "url": ""}
            for i in range(10)
        ]
        mock_arxiv.return_value = {"results": papers[:5]}
        mock_openalex.return_value = {"results": papers[5:]}

        result = await find_related_sources("test", max_results=3)
        assert result["source_count"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: _format_citation
# ═══════════════════════════════════════════════════════════════════════════


class TestFormatCitation:
    def test_apa_single_author(self):
        from app.tools.research_writer_tool import _format_citation

        paper = {"title": "My Paper", "authors": ["Smith, J."], "year": "2023", "venue": "Nature"}
        cite = _format_citation(paper, style="apa")
        assert "Smith, J." in cite
        assert "(2023)" in cite
        assert "My Paper" in cite
        assert "Nature" in cite

    def test_apa_two_authors(self):
        from app.tools.research_writer_tool import _format_citation

        paper = {"title": "Paper", "authors": ["Smith", "Lee"], "year": "2023", "venue": ""}
        cite = _format_citation(paper, style="apa")
        assert "Smith & Lee" in cite

    def test_apa_many_authors(self):
        from app.tools.research_writer_tool import _format_citation

        paper = {"title": "Paper", "authors": ["A", "B", "C", "D"], "year": "2023", "venue": ""}
        cite = _format_citation(paper, style="apa")
        assert "et al." in cite

    def test_mla_format(self):
        from app.tools.research_writer_tool import _format_citation

        paper = {"title": "Test Paper", "authors": ["Brown, A."], "year": "2022", "venue": "Science"}
        cite = _format_citation(paper, style="mla")
        assert '"Test Paper."' in cite
        assert "2022" in cite

    def test_no_authors(self):
        from app.tools.research_writer_tool import _format_citation

        paper = {"title": "Orphan Paper", "authors": [], "year": "2020", "venue": ""}
        cite = _format_citation(paper, style="apa")
        assert "Unknown" in cite


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests: /generate with research_topic
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerateWithSources:
    @patch("app.routes.research_writer.find_related_sources", new_callable=AsyncMock)
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    def test_generate_includes_sources_when_topic_provided(self, mock_vision, mock_sources):
        mock_vision.return_value = json.dumps({
            "paragraph": "The data shows a clear trend.",
            "figure_description": "Line chart.",
            "key_findings": ["Trend observed"],
            "graph_type": "line_chart",
            "graph_type_confidence": 0.9,
            "model_confidence": 0.8,
        })
        mock_sources.return_value = {
            "sources": [
                {
                    "title": "Trend Analysis Paper",
                    "authors": ["Jones, A."],
                    "year": "2023",
                    "formatted_citation": "Jones, A. (2023). Trend Analysis Paper.",
                    "source": "arxiv",
                },
            ],
            "source_count": 1,
        }

        uid = _create_test_user()
        resp = client.post(
            "/api/v1/research-writer/generate",
            headers=_auth_headers(uid),
            data={
                "explanation": "The graph shows revenue increasing over three years",
                "image_base64": _make_b64_png(),
                "research_topic": "revenue trend analysis",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "suggested_sources" in body
        assert len(body["suggested_sources"]) == 1
        assert body["suggested_sources"][0]["title"] == "Trend Analysis Paper"
        mock_sources.assert_called_once()

    @patch("app.routes.research_writer.find_related_sources", new_callable=AsyncMock)
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    def test_generate_uses_explanation_when_no_topic(self, mock_vision, mock_sources):
        mock_vision.return_value = json.dumps({
            "paragraph": "Analysis complete.",
            "figure_description": "Chart.",
            "key_findings": [],
            "graph_type": "bar_chart",
            "graph_type_confidence": 0.8,
            "model_confidence": 0.7,
        })
        mock_sources.return_value = {"sources": [], "source_count": 0}

        uid = _create_test_user()
        resp = client.post(
            "/api/v1/research-writer/generate",
            headers=_auth_headers(uid),
            data={
                "explanation": "The graph shows student performance across subjects",
                "image_base64": _make_b64_png(),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "suggested_sources" in body
        # Should have called find_related_sources with the explanation text
        mock_sources.assert_called_once()
        args = mock_sources.call_args
        assert "student performance" in args[0][0] or "student performance" in str(args)

    @patch("app.routes.research_writer.find_related_sources", new_callable=AsyncMock)
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    def test_generate_survives_source_failure(self, mock_vision, mock_sources):
        mock_vision.return_value = json.dumps({
            "paragraph": "Results paragraph.",
            "figure_description": "Graph.",
            "key_findings": [],
            "graph_type": "other",
            "graph_type_confidence": 0.5,
            "model_confidence": 0.6,
        })
        mock_sources.side_effect = RuntimeError("Source search failed")

        uid = _create_test_user()
        resp = client.post(
            "/api/v1/research-writer/generate",
            headers=_auth_headers(uid),
            data={
                "explanation": "The chart displays temperature changes over decades",
                "image_base64": _make_b64_png(),
            },
        )
        # Should still succeed — sources are best-effort
        assert resp.status_code == 200
        body = resp.json()
        assert body["suggested_sources"] == []
        assert "paragraph" in body


# ═══════════════════════════════════════════════════════════════════════════
# Integration tests: /find-sources endpoint
# ═══════════════════════════════════════════════════════════════════════════


class TestFindSourcesEndpoint:
    @patch("app.routes.research_writer.find_related_sources", new_callable=AsyncMock)
    def test_find_sources_success(self, mock_find):
        mock_find.return_value = {
            "topic": "neural networks",
            "sources": [
                {
                    "title": "NN Paper",
                    "authors": ["Lee, K."],
                    "year": "2024",
                    "formatted_citation": "Lee, K. (2024). NN Paper.",
                    "source": "openalex",
                },
            ],
            "source_count": 1,
            "elapsed_s": 0.4,
        }

        uid = _create_test_user()
        resp = client.post(
            "/api/v1/research-writer/find-sources",
            headers=_auth_headers(uid),
            json={"topic": "neural networks"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_count"] == 1
        assert body["sources"][0]["title"] == "NN Paper"

    def test_find_sources_topic_too_short(self):
        uid = _create_test_user()
        resp = client.post(
            "/api/v1/research-writer/find-sources",
            headers=_auth_headers(uid),
            json={"topic": "ab"},
        )
        assert resp.status_code == 422

    def test_find_sources_requires_auth(self):
        resp = client.post(
            "/api/v1/research-writer/find-sources",
            headers={"Authorization": "Bearer invalid_token"},
            json={"topic": "machine learning algorithms"},
        )
        assert resp.status_code == 401

    @patch("app.routes.research_writer.find_related_sources", new_callable=AsyncMock)
    def test_find_sources_custom_citation_style(self, mock_find):
        mock_find.return_value = {
            "topic": "quantum computing",
            "sources": [],
            "source_count": 0,
            "elapsed_s": 0.1,
        }

        uid = _create_test_user()
        resp = client.post(
            "/api/v1/research-writer/find-sources",
            headers=_auth_headers(uid),
            json={"topic": "quantum computing", "citation_style": "mla", "max_results": 5},
        )
        assert resp.status_code == 200
        mock_find.assert_called_once_with(
            "quantum computing", max_results=5, citation_style="mla",
        )
