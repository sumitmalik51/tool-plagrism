"""AI detection tool — detects AI-generated text.

Standalone, framework-agnostic tool. Returns structured JSON.

Two modes:
1. **Heuristic** (default) — statistical signals: TTR, burstiness, repetition.
   Fast, free, no API call. Always runs as a baseline.
2. **GPT-powered** — uses Azure OpenAI to classify text passages.
   More accurate, but uses API credits. Opt-in via ``use_gpt=True``.
"""

from __future__ import annotations

import math
import time
from collections import Counter

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# GPT-based AI detection
# ---------------------------------------------------------------------------

_GPT_SYSTEM_PROMPT = """You are an expert AI-generated text detector for academic documents.
Analyze each text passage and classify it as HUMAN or AI-GENERATED.

For each passage, return a JSON object with:
- "label": "human" or "ai"
- "confidence": 0.0 to 1.0
- "reason": brief explanation (max 30 words)

Look for these AI signals:
- Unnaturally uniform sentence length and rhythm
- Generic hedging ("It is important to note that...")
- Lack of specific personal insight or novel argument
- Formulaic transitions ("Furthermore", "Moreover", "In conclusion")
- Perfect grammar with no colloquialisms or stylistic personality
- Lists of generic points without deep analysis

Look for these HUMAN signals:
- Variable sentence length and complexity
- Specific domain expertise with novel insights
- Stylistic quirks, informal asides, or strong opinions
- Imperfect but natural phrasing
- Complex reasoning chains with original analogies

Return ONLY a JSON array, one object per passage. No markdown, no explanation outside JSON."""


async def _gpt_classify_chunks(chunks: list[str]) -> list[dict]:
    """Classify chunks as human/AI using Azure OpenAI GPT-4o.

    Returns a list of ``{"label": "human"|"ai", "confidence": float, "reason": str}``
    aligned to the input chunks.
    """
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
        return []

    # Batch chunks (max 10 per call to stay within token limits)
    batch_size = 10
    results: list[dict] = []

    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start : batch_start + batch_size]
        user_msg = "\n\n---\n\n".join(
            f"[Passage {i+1}]\n{chunk[:1500]}" for i, chunk in enumerate(batch)
        )

        url = (
            f"{settings.azure_openai_endpoint.rstrip('/')}"
            f"/openai/deployments/{settings.azure_openai_deployment}"
            f"/chat/completions?api-version={settings.azure_openai_api_version}"
        )
        headers = {
            "Content-Type": "application/json",
            "api-key": settings.azure_openai_api_key,
        }
        payload = {
            "messages": [
                {"role": "system", "content": _GPT_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.1,
            "max_tokens": 1500,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            content = data["choices"][0]["message"]["content"].strip()
            # Parse JSON array from response
            import json
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(content)
            if isinstance(parsed, list):
                results.extend(parsed[:len(batch)])
            else:
                results.extend([{"label": "unknown", "confidence": 0.0, "reason": "Parse error"}] * len(batch))
        except Exception as exc:
            logger.warning("gpt_ai_detection_failed", error=str(exc))
            results.extend([{"label": "unknown", "confidence": 0.0, "reason": "API error"}] * len(batch))

    return results


async def detect_ai_text(
    text: str,
    chunks: list[str] | None = None,
    *,
    use_gpt: bool = False,
) -> dict:
    """Analyse text for AI-generated content indicators.

    Args:
        text: Full document text.
        chunks: Optional pre-split chunks.
        use_gpt: If True, also run GPT-based classification for higher accuracy.

    Returns:
        Dict with ``score`` (0-100), ``confidence`` (0-1),
        ``indicators``, ``flagged_chunks``, ``elapsed_s``,
        and ``gpt_results`` (if use_gpt=True).
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

    # --- GPT-based classification (optional, higher accuracy) ----------------
    gpt_results: list[dict] = []
    gpt_score: float | None = None
    if use_gpt and chunks:
        # Send a sample of chunks (up to 20) for GPT classification
        sample = chunks[:20]
        gpt_results = await _gpt_classify_chunks(sample)
        if gpt_results:
            ai_count = sum(1 for r in gpt_results if r.get("label") == "ai")
            gpt_ratio = ai_count / len(gpt_results)
            gpt_score = round(gpt_ratio * 100, 2)
            # Blend heuristic and GPT scores (GPT weighted 70%, heuristic 30%)
            score = round(gpt_score * 0.70 + score * 0.30, 2)
            confidence = min(confidence + 0.25, 0.95)
            # Add GPT-flagged chunks
            for i, r in enumerate(gpt_results):
                if r.get("label") == "ai" and r.get("confidence", 0) >= 0.6 and i < len(sample):
                    flagged_chunks.append({
                        "chunk_index": i,
                        "text": sample[i][:500],
                        "reason": f"GPT classifier: {r.get('reason', 'AI-generated')} (confidence: {r.get('confidence', 0):.0%})",
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
        "gpt_enabled": use_gpt,
        "gpt_score": gpt_score,
    }

    logger.info(
        "ai_detection_complete",
        score=score,
        confidence=confidence,
        sentence_count=len(sentences),
        gpt_enabled=use_gpt,
        gpt_score=gpt_score,
        elapsed_s=elapsed,
    )

    return {
        "score": score,
        "confidence": confidence,
        "indicators": indicators,
        "flagged_chunks": flagged_chunks,
        "gpt_results": gpt_results,
        "elapsed_s": elapsed,
    }
