"""Tests for the Research Writer tool and endpoints."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
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
    """Create a minimal valid PNG image in memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_b64_png(**kwargs) -> str:
    return base64.b64encode(_make_png(**kwargs)).decode()


@pytest.fixture(autouse=True)
def _clean_rw_tables():
    """Clean research-writer tables between tests."""
    db = get_db()
    for table in ("rw_cache", "rw_embeddings", "rw_versions"):
        try:
            db.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    # Clear burst throttle
    from app.routes.research_writer import _burst_log
    _burst_log.clear()
    yield


def _create_test_user(email: str = "rw@test.com") -> int:
    """Create a test user and return user_id."""
    db = get_db()
    db.execute("DELETE FROM usage_logs")
    try:
        db.execute("DELETE FROM users WHERE email = ?", (email,))
    except Exception:
        pass
    result = signup("RW Tester", email, "password123")
    return result["user"]["id"]


def _auth_headers(user_id: int, email: str = "rw@test.com") -> dict:
    token = create_access_token(user_id, email)
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: validate_image
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateImage:
    def test_valid_png(self) -> None:
        from app.tools.research_writer_tool import validate_image
        b64, mime, quality = validate_image(_make_png())
        assert mime == "image/png"
        assert 0 < quality <= 1.0
        assert len(b64) > 0

    def test_too_large(self) -> None:
        from app.tools.research_writer_tool import validate_image
        with pytest.raises(ValueError, match="20 MB"):
            validate_image(b"\x00" * (21 * 1024 * 1024))

    def test_corrupt_image(self) -> None:
        from app.tools.research_writer_tool import validate_image
        with pytest.raises(ValueError, match="Corrupt"):
            validate_image(b"not-an-image-at-all")

    def test_too_small_dimensions(self) -> None:
        from app.tools.research_writer_tool import validate_image
        tiny = _make_png(width=10, height=10)
        with pytest.raises(ValueError, match="too small"):
            validate_image(tiny)

    def test_junk_image_low_quality(self) -> None:
        """An all-black tiny image near the threshold still passes but with low quality."""
        from app.tools.research_writer_tool import validate_image
        # 100x100 all-black → quality should be low but above rejection threshold
        black_png = _make_png(width=100, height=100, color=(0, 0, 0))
        _, _, quality = validate_image(black_png)
        assert quality < 0.5  # Low but not rejected


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: fetch_image_from_url
# ═══════════════════════════════════════════════════════════════════════════


class TestFetchImageFromUrl:
    @pytest.mark.asyncio
    async def test_rejects_non_https(self) -> None:
        from app.tools.research_writer_tool import fetch_image_from_url
        with pytest.raises(ValueError, match="HTTPS"):
            await fetch_image_from_url("http://example.com/chart.png")

    @pytest.mark.asyncio
    async def test_rejects_private_ip(self) -> None:
        from app.tools.research_writer_tool import fetch_image_from_url
        with pytest.raises(ValueError, match="private"):
            await fetch_image_from_url("https://192.168.1.1/chart.png")


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: compute_image_quality
# ═══════════════════════════════════════════════════════════════════════════


class TestImageQuality:
    def test_high_res_image(self) -> None:
        from app.tools.research_writer_tool import _compute_image_quality
        img = Image.new("RGB", (1920, 1080), (128, 64, 200))
        score = _compute_image_quality(img)
        assert score > 0.5

    def test_low_res_image(self) -> None:
        from app.tools.research_writer_tool import _compute_image_quality
        img = Image.new("RGB", (80, 60), (128, 128, 128))
        score = _compute_image_quality(img)
        assert score < 0.7


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: hash_request
# ═══════════════════════════════════════════════════════════════════════════


class TestHashRequest:
    def test_deterministic(self) -> None:
        from app.tools.research_writer_tool import hash_request
        h1 = hash_request("img_b64", "explanation", "results", "undergraduate", "academic", "apa")
        h2 = hash_request("img_b64", "explanation", "results", "undergraduate", "academic", "apa")
        assert h1 == h2

    def test_citation_style_changes_hash(self) -> None:
        from app.tools.research_writer_tool import hash_request
        h1 = hash_request("img", "exp", "results", "ug", "acad", "apa")
        h2 = hash_request("img", "exp", "results", "ug", "acad", "mla")
        assert h1 != h2


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: generate_paragraph (mocked OpenAI)
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerateParagraph:
    @pytest.mark.asyncio
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    async def test_success(self, mock_vision: AsyncMock) -> None:
        from app.tools.research_writer_tool import generate_paragraph
        mock_vision.return_value = json.dumps({
            "paragraph": "The bar chart demonstrates a steady increase in revenue.",
            "figure_description": "Bar chart showing revenue growth.",
            "key_findings": ["Revenue increased 20%"],
            "graph_type": "bar_chart",
            "graph_type_confidence": 0.92,
            "model_confidence": 0.85,
        })
        result = await generate_paragraph(
            image_base64=_make_b64_png(),
            mime_type="image/png",
            explanation="Revenue went up over three years",
            section_type="results",
            citation_style="apa",
            tone="academic",
            level="undergraduate",
            image_quality_score=0.7,
        )
        assert "paragraph" in result
        assert result["graph_type"] == "bar_chart"
        assert 0 < result["confidence"] <= 1.0
        assert result["image_used"] is True

    @pytest.mark.asyncio
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    @patch("app.tools.research_writer_tool._call_openai_text", new_callable=AsyncMock)
    async def test_vision_failure_falls_back_to_text(
        self, mock_text: AsyncMock, mock_vision: AsyncMock,
    ) -> None:
        from app.tools.research_writer_tool import generate_paragraph
        mock_vision.side_effect = Exception("Vision API error")
        mock_text.return_value = json.dumps({
            "paragraph": "Based on the description, revenue increased.",
            "figure_description": "Revenue chart.",
            "key_findings": ["Revenue growth noted"],
            "graph_type": "unknown",
            "graph_type_confidence": 0.3,
            "model_confidence": 0.5,
        })
        result = await generate_paragraph(
            image_base64=_make_b64_png(),
            mime_type="image/png",
            explanation="Revenue went up over three years in the chart",
            section_type="results",
            citation_style="apa",
            tone="academic",
            level="undergraduate",
            image_quality_score=0.7,
        )
        assert result["image_used"] is False

    @pytest.mark.asyncio
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    async def test_blended_confidence(self, mock_vision: AsyncMock) -> None:
        from app.tools.research_writer_tool import generate_paragraph
        mock_vision.return_value = json.dumps({
            "paragraph": "The line graph shows a clear upward trend.",
            "figure_description": "Line graph.",
            "key_findings": ["Upward trend"],
            "graph_type": "line_chart",
            "graph_type_confidence": 0.9,
            "model_confidence": 0.8,
        })
        result = await generate_paragraph(
            image_base64=_make_b64_png(),
            mime_type="image/png",
            explanation="This line chart shows an upward trend in temperature over time",
            section_type="results",
            citation_style="apa",
            tone="academic",
            level="undergraduate",
            image_quality_score=0.6,
        )
        # Blended = model * 0.7 + quality * 0.3 = 0.8 * 0.7 + 0.6 * 0.3 = 0.74
        expected = round(0.8 * 0.7 + 0.6 * 0.3, 3)
        assert abs(result["confidence"] - expected) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: expand_section
# ═══════════════════════════════════════════════════════════════════════════


class TestExpandSection:
    @pytest.mark.asyncio
    @patch("app.tools.research_writer_tool._call_openai_text", new_callable=AsyncMock)
    async def test_expand_returns_text(self, mock_text: AsyncMock) -> None:
        from app.tools.research_writer_tool import expand_section
        mock_text.return_value = json.dumps({
            "expanded_text": "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3.",
            "paragraph_count": 3,
        })
        result = await expand_section(
            "The chart shows a clear trend.", "results", "medium", "undergraduate",
        )
        assert "expanded_text" in result
        assert result["paragraph_count"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests: improve_explanation
# ═══════════════════════════════════════════════════════════════════════════


class TestImproveExplanation:
    @pytest.mark.asyncio
    @patch("app.tools.research_writer_tool._call_openai_vision", new_callable=AsyncMock)
    async def test_returns_improved(self, mock_vision: AsyncMock) -> None:
        from app.tools.research_writer_tool import improve_explanation
        mock_vision.return_value = "The bar chart illustrates revenue growth across three fiscal years."
        result = await improve_explanation("revenue went up", _make_b64_png(), "image/png")
        assert "bar chart" in result.lower() or "revenue" in result.lower()


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint tests: /api/v1/research-writer/generate
# ═══════════════════════════════════════════════════════════════════════════


class TestGenerateEndpoint:
    @patch("app.routes.research_writer.generate_paragraph", new_callable=AsyncMock)
    @patch("app.routes.research_writer.validate_image")
    def test_generate_success(self, mock_validate, mock_gen) -> None:
        uid = _create_test_user("gen@test.com")
        headers = _auth_headers(uid, "gen@test.com")

        mock_validate.return_value = (_make_b64_png(), "image/png", 0.7)
        mock_gen.return_value = {
            "paragraph": "The data shows an upward trend.",
            "graph_type": "line_chart",
            "graph_type_confidence": 0.9,
            "model_confidence": 0.8,
            "confidence": 0.74,
            "image_used": True,
            "figure_caption": "Figure 1: Revenue growth.",
            "key_findings": ["Revenue increased"],
            "image_quality_score": 0.7,
            "elapsed_s": 2.1,
        }

        resp = client.post(
            "/api/v1/research-writer/generate",
            headers=headers,
            data={
                "explanation": "The line chart shows revenue increasing",
                "section_type": "results",
                "citation_style": "apa",
                "tone": "academic",
                "level": "undergraduate",
            },
            files={"image": ("chart.png", _make_png(), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paragraph"] == "The data shows an upward trend."
        assert "session_id" in data
        assert "version_number" in data

    def test_generate_no_auth(self) -> None:
        resp = client.post(
            "/api/v1/research-writer/generate",
            data={"explanation": "some explanation text here of 20 characters minimum"},
            files={"image": ("c.png", _make_png(), "image/png")},
        )
        assert resp.status_code in (401, 403, 422)

    @patch("app.routes.research_writer.validate_image")
    def test_generate_short_explanation(self, mock_validate) -> None:
        uid = _create_test_user("short@test.com")
        headers = _auth_headers(uid, "short@test.com")
        mock_validate.return_value = (_make_b64_png(), "image/png", 0.7)

        resp = client.post(
            "/api/v1/research-writer/generate",
            headers=headers,
            data={"explanation": "too short"},
            files={"image": ("c.png", _make_png(), "image/png")},
        )
        assert resp.status_code == 422

    def test_generate_no_image(self) -> None:
        uid = _create_test_user("noimg@test.com")
        headers = _auth_headers(uid, "noimg@test.com")

        resp = client.post(
            "/api/v1/research-writer/generate",
            headers=headers,
            data={"explanation": "A chart showing temperature rising over time"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint tests: /api/v1/research-writer/check
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckEndpoint:
    @patch("app.tools.web_search_tool.fetch_page_text", new_callable=AsyncMock)
    @patch("app.tools.web_search_tool.search_multiple", new_callable=AsyncMock)
    def test_check_original_text(self, mock_search, mock_fetch) -> None:
        uid = _create_test_user("check@test.com")
        headers = _auth_headers(uid, "check@test.com")
        headers["Content-Type"] = "application/json"

        mock_search.return_value = {"results": []}
        mock_fetch.return_value = {}

        resp = client.post(
            "/api/v1/research-writer/check",
            headers=headers,
            json={"text": "This is an original paragraph about some unique topic that nobody has written about."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
        assert data["verdict"] == "original"
        assert data["similarity_score"] == 0.0

    def test_check_short_text(self) -> None:
        uid = _create_test_user("checkshort@test.com")
        headers = _auth_headers(uid, "checkshort@test.com")
        headers["Content-Type"] = "application/json"

        resp = client.post(
            "/api/v1/research-writer/check",
            headers=headers,
            json={"text": "Too short"},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint tests: /api/v1/research-writer/expand
# ═══════════════════════════════════════════════════════════════════════════


class TestExpandEndpoint:
    @patch("app.routes.research_writer.expand_section", new_callable=AsyncMock)
    def test_expand_success(self, mock_expand) -> None:
        uid = _create_test_user("expand@test.com")
        headers = _auth_headers(uid, "expand@test.com")
        headers["Content-Type"] = "application/json"

        mock_expand.return_value = {
            "expanded_text": "Para 1.\n\nPara 2.\n\nPara 3.",
            "paragraph_count": 3,
            "word_count": 30,
        }

        resp = client.post(
            "/api/v1/research-writer/expand",
            headers=headers,
            json={
                "paragraph": "The chart demonstrates a significant upward trend over three years.",
                "section_type": "results",
                "target_length": "medium",
                "level": "undergraduate",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["paragraph_count"] == 3

    def test_expand_short_paragraph(self) -> None:
        uid = _create_test_user("xshort@test.com")
        headers = _auth_headers(uid, "xshort@test.com")
        headers["Content-Type"] = "application/json"

        resp = client.post(
            "/api/v1/research-writer/expand",
            headers=headers,
            json={"paragraph": "Short."},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint tests: /api/v1/research-writer/improve
# ═══════════════════════════════════════════════════════════════════════════


class TestImproveEndpoint:
    @patch("app.routes.research_writer.improve_explanation", new_callable=AsyncMock)
    @patch("app.routes.research_writer.validate_image")
    def test_improve_success(self, mock_validate, mock_improve) -> None:
        uid = _create_test_user("improve@test.com")
        headers = _auth_headers(uid, "improve@test.com")

        mock_validate.return_value = (_make_b64_png(), "image/png", 0.7)
        mock_improve.return_value = "The bar chart clearly illustrates a 20% increase in revenue."

        resp = client.post(
            "/api/v1/research-writer/improve",
            headers=headers,
            data={"explanation": "rev went up"},
            files={"image": ("c.png", _make_png(), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "improved_explanation" in data


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint tests: /api/v1/research-writer/versions
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionsEndpoint:
    def test_empty_versions(self) -> None:
        uid = _create_test_user("ver@test.com")
        headers = _auth_headers(uid, "ver@test.com")

        resp = client.get(
            "/api/v1/research-writer/versions/nonexistent-session",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["versions"] == []

    def test_versions_after_store(self) -> None:
        uid = _create_test_user("ver2@test.com")
        headers = _auth_headers(uid, "ver2@test.com")

        from app.services.persistence import rw_store_version
        rw_store_version("sess-test-1", uid, 1, "First version.", "results", "undergraduate", "abc123")
        rw_store_version("sess-test-1", uid, 2, "Second version.", "results", "undergraduate", "abc123")

        resp = client.get(
            "/api/v1/research-writer/versions/sess-test-1",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["versions"]) == 2
        assert data["versions"][0]["version_number"] == 1
        assert data["versions"][1]["version_number"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint tests: /api/v1/research-writer/caption
# ═══════════════════════════════════════════════════════════════════════════


class TestCaptionEndpoint:
    @patch("app.routes.research_writer.generate_figure_caption", new_callable=AsyncMock)
    @patch("app.routes.research_writer.validate_image")
    def test_caption_success(self, mock_validate, mock_caption) -> None:
        uid = _create_test_user("caption@test.com")
        headers = _auth_headers(uid, "caption@test.com")

        mock_validate.return_value = (_make_b64_png(), "image/png", 0.7)
        mock_caption.return_value = "Figure 1: Line chart showing annual revenue."

        resp = client.post(
            "/api/v1/research-writer/caption",
            headers=headers,
            data={"explanation": "revenue chart"},
            files={"image": ("chart.png", _make_png(), "image/png")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "caption" in data
        assert "Figure 1" in data["caption"]


# ═══════════════════════════════════════════════════════════════════════════
# Burst throttle
# ═══════════════════════════════════════════════════════════════════════════


class TestBurstThrottle:
    def test_burst_limit_rejects(self) -> None:
        from app.routes.research_writer import _check_burst, _burst_log
        _burst_log.clear()
        # First 3 should pass
        for _ in range(3):
            _check_burst(999)
        # Fourth should fail
        with pytest.raises(Exception):
            _check_burst(999)


# ═══════════════════════════════════════════════════════════════════════════
# Persistence CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestPersistenceCRUD:
    def test_cache_set_and_get(self) -> None:
        from app.services.persistence import rw_cache_set, rw_cache_get
        rw_cache_set("hash123", 1, '{"paragraph": "test"}')
        cached = rw_cache_get("hash123")
        assert cached is not None
        assert cached["paragraph"] == "test"

    def test_cache_miss(self) -> None:
        from app.services.persistence import rw_cache_get
        assert rw_cache_get("nonexistent") is None

    def test_version_numbering(self) -> None:
        from app.services.persistence import (
            rw_store_version, rw_get_next_version_number,
        )
        uid = _create_test_user("vnum@test.com")
        assert rw_get_next_version_number("sess1", uid) == 1
        rw_store_version("sess1", uid, 1, "v1 text", "results", "undergraduate", "img1")
        assert rw_get_next_version_number("sess1", uid) == 2

    def test_embeddings_store_and_get(self) -> None:
        from app.services.persistence import rw_store_embedding, rw_get_user_embeddings
        uid = _create_test_user("emb@test.com")
        embedding = np.random.rand(384).astype(np.float32).tobytes()
        rw_store_embedding(uid, "hash_abc", "some paragraph text", embedding)
        rows = rw_get_user_embeddings(uid)
        assert len(rows) >= 1
        assert rows[0]["text_hash"] == "hash_abc"
