"""Tests for language detector — multi-language detection."""

import pytest
from app.tools.language_detector import detect_language, LANGUAGE_NAMES


class TestDetectLanguage:
    """Tests for language detection utility."""

    def test_english_text(self):
        text = "The quick brown fox jumps over the lazy dog. This is a test of the English language detection."
        result = detect_language(text)
        assert result["language"] == "en"
        assert result["language_name"] == "English"
        assert result["confidence"] > 0

    def test_spanish_text(self):
        text = "El rápido zorro marrón salta sobre el perro perezoso. Esta es una prueba de detección del idioma español."
        result = detect_language(text)
        assert result["language"] == "es"
        assert result["language_name"] == "Spanish"

    def test_french_text(self):
        text = "Le renard brun rapide saute par-dessus le chien paresseux. Les résultats des expériences dans le domaine."
        result = detect_language(text)
        assert result["language"] == "fr"
        assert result["language_name"] == "French"

    def test_german_text(self):
        text = "Der schnelle braune Fuchs springt über den faulen Hund. Die Ergebnisse der Experimente in diesem Bereich."
        result = detect_language(text)
        assert result["language"] == "de"
        assert result["language_name"] == "German"

    def test_short_text_defaults_to_english(self):
        text = "Hi"
        result = detect_language(text)
        assert result["language"] == "en"
        assert result["confidence"] == 0.0

    def test_empty_text_defaults_to_english(self):
        result = detect_language("")
        assert result["language"] == "en"

    def test_result_has_required_keys(self):
        result = detect_language("Some English text for testing.")
        assert "language" in result
        assert "language_name" in result
        assert "confidence" in result

    def test_language_names_mapping(self):
        assert "en" in LANGUAGE_NAMES
        assert "es" in LANGUAGE_NAMES
        assert "fr" in LANGUAGE_NAMES
        assert "de" in LANGUAGE_NAMES
        assert "zh" in LANGUAGE_NAMES
        assert "hi" in LANGUAGE_NAMES
