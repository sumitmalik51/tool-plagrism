"""AI detection tool — detects AI-generated text.

Standalone, framework-agnostic tool. Returns structured JSON.
Uses statistical heuristics (perplexity, burstiness) as a baseline.
Can be extended with external API integrations.
"""

from __future__ import annotations

import math
import time
from collections import Counter

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def detect_ai_text(text: str, chunks: list[str] | None = None) -> dict:
    """Analyse text for AI-generated content indicators.

    Uses statistical heuristics:
    - Vocabulary richness (type-token ratio)
    - Sentence length variance (burstiness)
    - Repeated phrase detection

    Args:
        text: Full document text.
        chunks: Optional pre-split chunks.

    Returns:
        Dict with ``score`` (0-100), ``confidence`` (0-1),
        ``indicators``, ``flagged_chunks``, ``elapsed_s``.
    """
    start = time.perf_counter()

    if not text.strip():
        return {
            "score": 0.0,
            "confidence": 0.0,
            "indicators": {},
            "flagged_chunks": [],
            "elapsed_s": 0.0,
        }

    words = text.lower().split()
    sentences = [s.strip() for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]

    # --- Indicator 1: Vocabulary richness (Type-Token Ratio) ------------------
    ttr = len(set(words)) / len(words) if words else 1.0
    # AI text tends to have a "comfortable middle" TTR (0.4–0.65).
    # Very high TTR (rich vocabulary) or very low TTR (repetitive) are
    # more typical of human text.  Signal peaks at 0.52 (typical GPT-4 range).
    ttr_signal = max(0, 1.0 - abs(ttr - 0.52) * 3.5)

    # --- Indicator 2: Sentence length variance (burstiness) -------------------
    if len(sentences) >= 2:
        lengths = [len(s.split()) for s in sentences]
        mean_len = sum(lengths) / len(lengths)
        variance = sum((ln - mean_len) ** 2 for ln in lengths) / len(lengths)
        std_dev = math.sqrt(variance)
        # AI tends to have low std_dev (uniform sentence length).
        # Humans vary more — std_dev of 8-15 is common for humans.
        burstiness_signal = max(0, 1.0 - (std_dev / 12.0))
    else:
        burstiness_signal = 0.5

    # --- Indicator 3: Repeated n-grams ----------------------------------------
    trigrams = [" ".join(words[i:i+3]) for i in range(len(words) - 2)]
    trigram_counts = Counter(trigrams)
    repeated = sum(1 for c in trigram_counts.values() if c > 2)
    repetition_ratio = repeated / max(len(trigram_counts), 1)
    repetition_signal = min(repetition_ratio * 10, 1.0)

    # --- Indicator 4: Average sentence length uniformity ----------------------
    # AI models produce sentences of remarkably consistent length
    if len(sentences) >= 3:
        lengths = [len(s.split()) for s in sentences]
        median_len = sorted(lengths)[len(lengths) // 2]
        # What fraction of sentences are within ±5 words of median?
        near_median = sum(1 for ln in lengths if abs(ln - median_len) <= 5)
        uniformity_signal = near_median / len(lengths)
    else:
        uniformity_signal = 0.5

    # --- Combine signals ------------------------------------------------------
    raw_score = (
        ttr_signal * 0.30
        + burstiness_signal * 0.30
        + repetition_signal * 0.15
        + uniformity_signal * 0.25
    ) * 100

    score = round(min(max(raw_score, 0.0), 100.0), 2)
    confidence = round(min(len(sentences) / 20, 1.0) * 0.6 + 0.1, 2)

    # --- Flag specific chunks -------------------------------------------------
    flagged_chunks: list[dict] = []
    if chunks:
        for i, chunk in enumerate(chunks):
            chunk_words = chunk.lower().split()
            chunk_sentences = [s.strip() for s in chunk.replace("!", ".").replace("?", ".").split(".") if s.strip()]
            if len(chunk_sentences) >= 2:
                c_lengths = [len(s.split()) for s in chunk_sentences]
                c_mean = sum(c_lengths) / len(c_lengths)
                c_var = sum((l - c_mean) ** 2 for l in c_lengths) / len(c_lengths)
                c_std = math.sqrt(c_var)
                if c_std < 3.0:  # very uniform → suspicious
                    flagged_chunks.append({
                        "chunk_index": i,
                        "text": chunk[:500],
                        "reason": f"Low sentence length variance (std={c_std:.1f})",
                    })

    elapsed = round(time.perf_counter() - start, 3)

    indicators = {
        "type_token_ratio": round(ttr, 4),
        "ttr_signal": round(ttr_signal, 4),
        "burstiness_signal": round(burstiness_signal, 4),
        "repetition_signal": round(repetition_signal, 4),
        "uniformity_signal": round(uniformity_signal, 4),
        "sentence_count": len(sentences),
        "word_count": len(words),
    }

    logger.info(
        "ai_detection_complete",
        score=score,
        confidence=confidence,
        sentence_count=len(sentences),
        elapsed_s=elapsed,
    )

    return {
        "score": score,
        "confidence": confidence,
        "indicators": indicators,
        "flagged_chunks": flagged_chunks,
        "elapsed_s": elapsed,
    }
