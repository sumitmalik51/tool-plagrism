"""Language detection utility — detect document language for multi-language support.

Uses a lightweight heuristic approach (character-set analysis + common word
frequency) to detect the primary language of a document. Falls back to
``langdetect`` if installed.
"""

from __future__ import annotations

import re
from collections import Counter
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Common words per language (top 20 function words)
_LANGUAGE_WORDS: dict[str, set[str]] = {
    "en": {"the", "and", "is", "in", "to", "of", "a", "that", "it", "for",
            "was", "on", "are", "with", "as", "this", "be", "have", "from", "not"},
    "es": {"de", "la", "que", "el", "en", "y", "los", "se", "del", "las",
            "un", "por", "con", "no", "una", "su", "para", "es", "al", "lo"},
    "fr": {"de", "la", "le", "et", "les", "des", "en", "un", "une", "du",
            "est", "que", "dans", "qui", "au", "pas", "sur", "ne", "par", "ce"},
    "de": {"der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich",
            "des", "auf", "für", "ist", "im", "dem", "nicht", "ein", "eine", "als"},
    "pt": {"de", "que", "e", "do", "da", "em", "um", "para", "com", "não",
            "uma", "os", "no", "se", "na", "por", "mais", "as", "dos", "como"},
    "it": {"di", "che", "è", "la", "il", "un", "in", "una", "del", "per",
            "non", "si", "da", "le", "dei", "con", "sono", "alla", "questo", "anche"},
    "hi": {"के", "है", "में", "की", "का", "और", "को", "से", "पर", "ने",
            "एक", "हैं", "कि", "यह", "इस", "था", "भी", "नहीं", "जो", "हो"},
    "zh": {"的", "了", "在", "是", "我", "不", "人", "他", "有", "这",
            "个", "上", "们", "来", "到", "时", "大", "地", "为", "子"},
    "ja": {"の", "に", "は", "を", "た", "が", "で", "て", "と", "し",
            "れ", "さ", "ある", "いる", "も", "する", "から", "な", "こと", "として"},
    "ar": {"في", "من", "على", "أن", "إلى", "هذا", "التي", "الذي", "عن", "هو",
            "كان", "لا", "بين", "ما", "بعد", "كل", "قد", "كما", "أو", "ذلك"},
    "ko": {"의", "이", "은", "는", "에", "를", "을", "로", "와", "가",
            "한", "다", "그", "하", "것", "도", "수", "이다", "서", "지"},
}

# Language display names
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "hi": "Hindi",
    "zh": "Chinese",
    "ja": "Japanese",
    "ar": "Arabic",
    "ko": "Korean",
    "unknown": "Unknown",
}


def detect_language(text: str) -> dict[str, str | float]:
    """Detect the primary language of the given text.

    Returns:
        Dict with ``language`` (ISO code), ``language_name``, and ``confidence``.
    """
    if not text or len(text.strip()) < 20:
        return {"language": "en", "language_name": "English", "confidence": 0.0}

    # Try langdetect first if available
    try:
        from langdetect import detect_langs
        results = detect_langs(text[:5000])
        if results:
            best = results[0]
            lang_code = best.lang.split("-")[0]  # e.g. "zh-cn" → "zh"
            return {
                "language": lang_code,
                "language_name": LANGUAGE_NAMES.get(lang_code, lang_code.upper()),
                "confidence": round(best.prob, 3),
            }
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: word-frequency heuristic
    # Tokenise into words (handle CJK by checking character ranges)
    sample = text[:5000].lower()

    # Check for CJK-dominant text
    cjk_count = len(re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]", sample))
    total_chars = len(re.findall(r"\S", sample))

    if total_chars > 0 and cjk_count / total_chars > 0.3:
        # CJK-dominant
        zh_count = len(re.findall(r"[\u4e00-\u9fff]", sample))
        ja_count = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", sample))
        ko_count = len(re.findall(r"[\uac00-\ud7af]", sample))
        if ja_count > zh_count and ja_count > ko_count:
            return {"language": "ja", "language_name": "Japanese", "confidence": 0.7}
        if ko_count > zh_count:
            return {"language": "ko", "language_name": "Korean", "confidence": 0.7}
        return {"language": "zh", "language_name": "Chinese", "confidence": 0.7}

    # Arabic script
    arabic_count = len(re.findall(r"[\u0600-\u06ff]", sample))
    if total_chars > 0 and arabic_count / total_chars > 0.3:
        return {"language": "ar", "language_name": "Arabic", "confidence": 0.7}

    # Devanagari (Hindi)
    hindi_count = len(re.findall(r"[\u0900-\u097f]", sample))
    if total_chars > 0 and hindi_count / total_chars > 0.3:
        return {"language": "hi", "language_name": "Hindi", "confidence": 0.7}

    # Latin-script languages: use word frequency
    words = re.findall(r"\b[a-zà-öø-ÿ]{2,}\b", sample)
    if not words:
        return {"language": "en", "language_name": "English", "confidence": 0.3}

    word_set = set(words)
    word_counts = Counter(words)
    total_words = len(words)

    scores: dict[str, float] = {}
    for lang, common_words in _LANGUAGE_WORDS.items():
        if lang in ("zh", "ja", "ko", "ar", "hi"):
            continue  # Already handled above
        matches = word_set & common_words
        # Weight by frequency
        weighted = sum(word_counts.get(w, 0) for w in matches)
        scores[lang] = weighted / total_words if total_words > 0 else 0

    if not scores:
        return {"language": "en", "language_name": "English", "confidence": 0.3}

    best_lang = max(scores, key=scores.get)
    confidence = min(scores[best_lang] * 5, 1.0)  # Scale up

    return {
        "language": best_lang,
        "language_name": LANGUAGE_NAMES.get(best_lang, best_lang.upper()),
        "confidence": round(confidence, 3),
    }
