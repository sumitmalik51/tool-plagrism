"""Readability analyzer tool — text quality metrics.

Computes readability scores, text statistics, and reading time
without any external API calls (pure Python computation).
"""

from __future__ import annotations

import math
import re
import time

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Syllable counting heuristic
# ---------------------------------------------------------------------------

_VOWELS = set("aeiouy")
_SUB_SYLLABLE = re.compile(
    r"(cial|tia|cius|cious|giu|ion|iou|sia$|eous$|[^aeiou]ely$)", re.I
)
_ADD_SYLLABLE = re.compile(
    r"(ia|riet|dien|iu|io|ii|[aeiouym]bl$|[aeiou]{3}|^mc|ism$|"
    r"asm$|thm$|([^aeiouy])\2l$|[^l]lien|^coa[dglx].|"
    r"[^gq]ua[^auieo]|dnt$|uity$|ie(r|st)$)",
    re.I,
)


def _count_syllables(word: str) -> int:
    """Estimate syllable count for a single word."""
    word = word.lower().strip()
    if len(word) <= 3:
        return 1

    # Remove trailing silent-e
    if word.endswith("e"):
        word = word[:-1]

    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in _VOWELS
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel

    # Adjustments
    count -= len(_SUB_SYLLABLE.findall(word))
    count += len(_ADD_SYLLABLE.findall(word))

    return max(count, 1)


# ---------------------------------------------------------------------------
# Sentence / word splitting
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r"[.!?]+\s+|[.!?]+$|\n{2,}")


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    raw = _SENTENCE_RE.split(text)
    return [s.strip() for s in raw if s.strip() and len(s.strip().split()) >= 2]


def _split_words(text: str) -> list[str]:
    """Split text into words."""
    return re.findall(r"[a-zA-Z']+", text)


def _count_complex_words(words: list[str]) -> int:
    """Count words with 3+ syllables (Gunning Fog)."""
    return sum(1 for w in words if _count_syllables(w) >= 3)


# ---------------------------------------------------------------------------
# Readability formulas
# ---------------------------------------------------------------------------

def _flesch_reading_ease(
    total_words: int,
    total_sentences: int,
    total_syllables: int,
) -> float:
    """Flesch Reading Ease score (0-100, higher = easier)."""
    if total_sentences == 0 or total_words == 0:
        return 0.0
    asl = total_words / total_sentences
    asw = total_syllables / total_words
    return round(206.835 - (1.015 * asl) - (84.6 * asw), 1)


def _flesch_kincaid_grade(
    total_words: int,
    total_sentences: int,
    total_syllables: int,
) -> float:
    """Flesch-Kincaid Grade Level."""
    if total_sentences == 0 or total_words == 0:
        return 0.0
    asl = total_words / total_sentences
    asw = total_syllables / total_words
    return round((0.39 * asl) + (11.8 * asw) - 15.59, 1)


def _gunning_fog(
    total_words: int,
    total_sentences: int,
    complex_words: int,
) -> float:
    """Gunning Fog Index."""
    if total_sentences == 0 or total_words == 0:
        return 0.0
    asl = total_words / total_sentences
    pcw = (complex_words / total_words) * 100
    return round(0.4 * (asl + pcw), 1)


def _coleman_liau(
    total_words: int,
    total_sentences: int,
    total_chars: int,
) -> float:
    """Coleman-Liau Index."""
    if total_words == 0:
        return 0.0
    l = (total_chars / total_words) * 100  # avg chars per 100 words
    s = (total_sentences / total_words) * 100  # avg sentences per 100 words
    return round(0.0588 * l - 0.296 * s - 15.8, 1)


def _ari(
    total_words: int,
    total_sentences: int,
    total_chars: int,
) -> float:
    """Automated Readability Index."""
    if total_sentences == 0 or total_words == 0:
        return 0.0
    return round(
        4.71 * (total_chars / total_words)
        + 0.5 * (total_words / total_sentences)
        - 21.43,
        1,
    )


def _smog_index(total_sentences: int, complex_words: int) -> float:
    """SMOG Index (requires ≥30 sentences for accuracy)."""
    if total_sentences < 3:
        return 0.0
    return round(
        1.0430 * math.sqrt(complex_words * (30 / total_sentences)) + 3.1291,
        1,
    )


def _reading_level_label(grade: float) -> str:
    """Human-readable reading level from grade score."""
    if grade <= 5:
        return "Elementary"
    if grade <= 8:
        return "Middle School"
    if grade <= 12:
        return "High School"
    if grade <= 16:
        return "College"
    return "Graduate"


def _ease_label(score: float) -> str:
    """Human-readable label for Flesch Reading Ease."""
    if score >= 90:
        return "Very Easy"
    if score >= 80:
        return "Easy"
    if score >= 70:
        return "Fairly Easy"
    if score >= 60:
        return "Standard"
    if score >= 50:
        return "Fairly Difficult"
    if score >= 30:
        return "Difficult"
    return "Very Difficult"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_readability(text: str) -> dict:
    """Compute readability metrics for the given text.

    Returns a dict with all scores, statistics, and reading time.
    """
    start = time.perf_counter()

    if not text or not text.strip():
        return {
            "scores": {},
            "statistics": {},
            "reading_time": {},
            "level": "N/A",
            "elapsed_s": 0.0,
        }

    sentences = _split_sentences(text)
    words = _split_words(text)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    total_sentences = max(len(sentences), 1)
    total_words = len(words)
    total_syllables = sum(_count_syllables(w) for w in words)
    total_chars = sum(len(w) for w in words)  # chars in words only
    complex_words = _count_complex_words(words)

    # Vocabulary diversity
    unique_words = len(set(w.lower() for w in words))
    vocab_diversity = round(unique_words / max(total_words, 1), 3)

    # Sentence length stats
    sent_lengths = [len(s.split()) for s in sentences]
    avg_sent_len = round(sum(sent_lengths) / max(len(sent_lengths), 1), 1)
    max_sent_len = max(sent_lengths) if sent_lengths else 0
    min_sent_len = min(sent_lengths) if sent_lengths else 0

    # Word length stats
    word_lengths = [len(w) for w in words]
    avg_word_len = round(sum(word_lengths) / max(len(word_lengths), 1), 1)

    # Reading time (average 238 wpm reading, 183 wpm speaking)
    reading_minutes = round(total_words / 238, 1)
    speaking_minutes = round(total_words / 183, 1)

    # Compute all readability scores
    fre = _flesch_reading_ease(total_words, total_sentences, total_syllables)
    fkg = _flesch_kincaid_grade(total_words, total_sentences, total_syllables)
    gf = _gunning_fog(total_words, total_sentences, complex_words)
    cli = _coleman_liau(total_words, total_sentences, total_chars)
    ari_score = _ari(total_words, total_sentences, total_chars)
    smog = _smog_index(total_sentences, complex_words)

    # Average grade level from multiple formulas
    grade_scores = [s for s in [fkg, gf, cli, ari_score, smog] if s > 0]
    avg_grade = round(sum(grade_scores) / max(len(grade_scores), 1), 1)

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "readability_analysis_complete",
        words=total_words,
        sentences=total_sentences,
        fre=fre,
        avg_grade=avg_grade,
        elapsed_s=elapsed,
    )

    return {
        "scores": {
            "flesch_reading_ease": fre,
            "flesch_reading_ease_label": _ease_label(fre),
            "flesch_kincaid_grade": fkg,
            "gunning_fog": gf,
            "coleman_liau": cli,
            "automated_readability_index": ari_score,
            "smog_index": smog,
            "average_grade_level": avg_grade,
        },
        "statistics": {
            "word_count": total_words,
            "sentence_count": total_sentences,
            "paragraph_count": len(paragraphs),
            "syllable_count": total_syllables,
            "char_count": total_chars,
            "complex_word_count": complex_words,
            "complex_word_pct": round(
                (complex_words / max(total_words, 1)) * 100, 1
            ),
            "unique_words": unique_words,
            "vocabulary_diversity": vocab_diversity,
            "avg_sentence_length": avg_sent_len,
            "max_sentence_length": max_sent_len,
            "min_sentence_length": min_sent_len,
            "avg_word_length": avg_word_len,
        },
        "reading_time": {
            "minutes": reading_minutes,
            "seconds": round(reading_minutes * 60),
            "speaking_minutes": speaking_minutes,
            "words_per_minute": 238,
        },
        "level": _reading_level_label(avg_grade),
        "elapsed_s": elapsed,
    }
