"""Tests for multi-language support across the pipeline.

Covers: language propagation to agents, web search localisation,
scholar localisation, language override in analyze API, and the
multilingual embedding model configuration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.schemas import AgentInput
from app.tools.language_detector import detect_language, LANGUAGE_NAMES
from app.tools.web_search_tool import (
    _LANG_TO_MARKET,
    _LANG_TO_DDG_REGION,
    _search_bing,
    _search_ddg_sync,
)

client = TestClient(app, raise_server_exceptions=False)


# ═══════════════════════════════════════════════════════════════════════════
# Config — multilingual embedding model
# ═══════════════════════════════════════════════════════════════════════════

class TestMultilingualConfig:
    def test_embedding_model_is_multilingual(self):
        assert "multilingual" in settings.embedding_model.lower()

    def test_embedding_model_name(self):
        assert settings.embedding_model == "paraphrase-multilingual-MiniLM-L12-v2"


# ═══════════════════════════════════════════════════════════════════════════
# AgentInput — language field
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentInputLanguage:
    def test_default_language_is_english(self):
        inp = AgentInput(document_id="doc1", text="Hello world")
        assert inp.language == "en"

    def test_language_field_accepted(self):
        inp = AgentInput(document_id="doc1", text="Hola mundo", language="es")
        assert inp.language == "es"


# ═══════════════════════════════════════════════════════════════════════════
# Web search localisation
# ═══════════════════════════════════════════════════════════════════════════

class TestWebSearchLocalisation:
    def test_market_mappings_cover_all_languages(self):
        for lang in LANGUAGE_NAMES:
            if lang == "unknown":
                continue
            assert lang in _LANG_TO_MARKET, f"Missing Bing market for {lang}"

    def test_ddg_region_mappings_cover_all_languages(self):
        for lang in LANGUAGE_NAMES:
            if lang == "unknown":
                continue
            assert lang in _LANG_TO_DDG_REGION, f"Missing DDG region for {lang}"

    @pytest.mark.asyncio
    async def test_bing_uses_language_market(self):
        """When calling Bing with language='es', the mkt param should be es-ES."""
        with patch("app.tools.web_search_tool.settings") as mock_settings:
            mock_settings.bing_api_key = "test-key"
            with patch("app.tools.web_search_tool.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"webPages": {"value": []}}
                mock_resp.raise_for_status = MagicMock()
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await _search_bing("consulta de búsqueda", 5, language="es")

                call_args = mock_client.get.call_args
                params = call_args.kwargs.get("params", call_args[1].get("params", {}))
                assert params["mkt"] == "es-ES"

    def test_ddg_sync_region_param(self):
        """DDG search should use the correct region for the language."""
        # Just verify the mapping resolves correctly
        assert _LANG_TO_DDG_REGION["fr"] == "fr-fr"
        assert _LANG_TO_DDG_REGION["hi"] == "in-en"
        assert _LANG_TO_DDG_REGION["zh"] == "cn-zh"


# ═══════════════════════════════════════════════════════════════════════════
# Scholar localisation
# ═══════════════════════════════════════════════════════════════════════════

class TestScholarLocalisation:
    @pytest.mark.asyncio
    async def test_scholar_uses_language_hl(self):
        """Scholar search should set hl param to the detected language."""
        with patch("app.tools.scholar_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body></body></html>"
            mock_resp.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from app.tools.scholar_tool import _fetch_scholar
            await _fetch_scholar("recherche académique", 5, language="fr")

            call_args = mock_client.get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["hl"] == "fr"

    @pytest.mark.asyncio
    async def test_scholar_chinese_maps_to_zh_cn(self):
        with patch("app.tools.scholar_tool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body></body></html>"
            mock_resp.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            from app.tools.scholar_tool import _fetch_scholar
            await _fetch_scholar("学术搜索", 5, language="zh")

            call_args = mock_client.get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["hl"] == "zh-CN"


# ═══════════════════════════════════════════════════════════════════════════
# Analyze API — language override
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalyzeLanguageOverride:
    def test_language_field_accepted_in_request(self):
        """The /analyze-agent endpoint should accept a language field."""
        # We mock run_pipeline so it doesn't actually execute
        with patch("app.routes.analyze.run_pipeline", new_callable=AsyncMock) as mock_pipeline:
            from app.models.schemas import PlagiarismReport, RiskLevel
            mock_pipeline.return_value = PlagiarismReport(
                document_id="test123",
                plagiarism_score=10.0,
                confidence_score=0.8,
                risk_level=RiskLevel.LOW,
                language="es",
                language_name="Spanish",
            )

            res = client.post(
                "/api/v1/analyze-agent",
                json={
                    "text": "Este es un texto de prueba para el análisis de plagio en español.",
                    "language": "es",
                },
            )

            assert res.status_code == 200
            # Verify run_pipeline was called with language_override="es"
            call_kwargs = mock_pipeline.call_args.kwargs
            assert call_kwargs.get("language_override") == "es"

    def test_language_field_optional(self):
        """Omitting language should auto-detect."""
        with patch("app.routes.analyze.run_pipeline", new_callable=AsyncMock) as mock_pipeline:
            from app.models.schemas import PlagiarismReport, RiskLevel
            mock_pipeline.return_value = PlagiarismReport(
                document_id="test123",
                plagiarism_score=5.0,
                confidence_score=0.9,
                risk_level=RiskLevel.LOW,
            )

            res = client.post(
                "/api/v1/analyze-agent",
                json={"text": "The quick brown fox jumps over the lazy dog."},
            )

            assert res.status_code == 200
            call_kwargs = mock_pipeline.call_args.kwargs
            assert call_kwargs.get("language_override") is None


# ═══════════════════════════════════════════════════════════════════════════
# Language detector — additional multilingual tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLanguageDetectorMultilingual:
    def test_hindi_text(self):
        text = "यह एक परीक्षण है। भारत में हिन्दी सबसे अधिक बोली जाने वाली भाषा है। यह एक बहुत ही महत्वपूर्ण भाषा है।"
        result = detect_language(text)
        assert result["language"] == "hi"
        assert result["language_name"] == "Hindi"

    def test_chinese_text(self):
        text = "这是一个测试。中国是一个拥有悠久历史和文化的国家。这篇文章讨论了人工智能在教育领域的应用。"
        result = detect_language(text)
        assert result["language"] == "zh"
        assert result["language_name"] == "Chinese"

    def test_arabic_text(self):
        text = "هذا اختبار. المملكة العربية السعودية هي أكبر دولة في شبه الجزيرة العربية. هذا المقال يناقش تطبيقات الذكاء الاصطناعي."
        result = detect_language(text)
        assert result["language"] == "ar"
        assert result["language_name"] == "Arabic"

    def test_korean_text(self):
        text = "이것은 테스트입니다. 한국은 동아시아에 위치한 나라입니다. 이 논문은 인공지능의 교육 분야 응용에 대해 논의합니다."
        result = detect_language(text)
        assert result["language"] == "ko"
        assert result["language_name"] == "Korean"

    def test_portuguese_text(self):
        text = "Este é um teste de detecção de língua portuguesa. O Brasil é o maior país da América do Sul e tem uma rica cultura."
        result = detect_language(text)
        assert result["language"] == "pt"
        assert result["language_name"] == "Portuguese"

    def test_italian_text(self):
        text = "Questo è un test di rilevamento della lingua italiana. L'Italia è un paese con una lunga storia e cultura ricca."
        result = detect_language(text)
        assert result["language"] == "it"
        assert result["language_name"] == "Italian"

    def test_all_languages_have_names(self):
        supported = ["en", "es", "fr", "de", "pt", "it", "hi", "zh", "ja", "ar", "ko"]
        for lang in supported:
            assert lang in LANGUAGE_NAMES
            assert isinstance(LANGUAGE_NAMES[lang], str)
            assert len(LANGUAGE_NAMES[lang]) > 0
