"""
General-purpose AI rewriting tool — standalone writing assistant.

Unlike the plagiarism rewriter (rewriter_tool.py), this tool is a
general writing assistant with multiple modes, tones, and strength
levels.  It produces 3 diverse variations per request.
"""

from __future__ import annotations

import json
import time
import asyncio
from typing import Literal

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TEXT_LENGTH = 10
MIN_WORD_COUNT = 2
MAX_RETRIES = 2

# Rewriting modes
Mode = Literal[
    "paraphrase",
    "simplify",
    "expand",
    "formal",
    "casual",
    "academic",
    "humanize",
]

# Tone presets
Tone = Literal[
    "friendly",
    "professional",
    "confident",
    "persuasive",
    "neutral",
]

# Strength levels
Strength = Literal["low", "medium", "high"]

# ---------------------------------------------------------------------------
# System prompt — intentionally different from plagiarism rewriter
# ---------------------------------------------------------------------------

_REWRITE_SYSTEM = """You are an expert writing assistant.

Your task is to rewrite text based on the user's chosen MODE and TONE.

GUIDELINES:
1. Improve clarity, readability, and flow.
2. Adapt the tone exactly as requested.
3. Preserve the original meaning unless the user asks otherwise.
4. Provide 3 distinct variations — each with a noticeably different style.
5. Ensure natural, human-like writing throughout.
6. Never add new factual claims or remove key information.

MODE DEFINITIONS:
- PARAPHRASE: Reword while keeping the same meaning. Vary sentence structure.
- SIMPLIFY: Use shorter sentences, simpler vocabulary, easier reading level.
- EXPAND: Add detail, examples, or explanation. Make the text richer.
- FORMAL: Elevate register. Use precise language, complex sentences.
- CASUAL: Conversational tone. Contractions, natural rhythm, friendly.
- ACADEMIC: Scholarly register. Objective voice, hedging, citations-ready.
- HUMANIZE: Make AI-sounding text feel genuinely human-written. Add personality, varied rhythm, natural imperfections.

REWRITE STRENGTH:
- LOW: Light polish — fix awkward phrasing, minor improvements only.
- MEDIUM: Moderate transformation — new sentence structures, better flow.
- HIGH: Major rewrite — completely restructured, fresh expression throughout.

OUTPUT FORMAT:
Return ONLY a JSON array of exactly 3 strings — the 3 rewritten variations.
Example: ["variation 1...", "variation 2...", "variation 3..."]

Do NOT include any explanation, markdown, or wrapper text.
"""


# ---------------------------------------------------------------------------
# Mode-specific guidance (injected into user prompt)
# ---------------------------------------------------------------------------

_MODE_HINTS: dict[str, str] = {
    "paraphrase": "Reword the text while keeping exactly the same meaning. Use different sentence structures, synonyms, and phrasing.",
    "simplify": "Make the text simpler. Use shorter sentences, common words, and easy-to-follow structure. Target a general audience.",
    "expand": "Expand the text with more detail, examples, or explanation. Make it richer and more comprehensive while staying on topic.",
    "formal": "Rewrite in a formal, elevated register. Use precise vocabulary, complex sentence structures, and professional language.",
    "casual": "Rewrite in a casual, conversational tone. Use contractions, natural rhythm, and a friendly voice.",
    "academic": "Rewrite in academic/scholarly style. Use objective voice, hedging language, discipline-appropriate terminology.",
    "humanize": "Make this sound naturally human-written. Add personality, vary sentence length, include natural transitions and rhythm.",
}

_TONE_HINTS: dict[str, str] = {
    "friendly": "Use a warm, approachable, and encouraging voice.",
    "professional": "Use a polished, business-appropriate voice.",
    "confident": "Use a bold, assertive, and authoritative voice.",
    "persuasive": "Use a compelling, convincing voice that motivates action.",
    "neutral": "Use a balanced, objective voice without strong emotion.",
}


# ---------------------------------------------------------------------------
# Azure OpenAI call (shared infra with retry)
# ---------------------------------------------------------------------------

async def _call_openai(system_prompt: str, user_prompt: str) -> str:
    """Call Azure OpenAI with retry logic."""
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    api_key = settings.azure_openai_api_key
    deployment = settings.azure_openai_deployment
    api_version = settings.azure_openai_api_version

    url = (
        f"{endpoint}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={api_version}"
    )

    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }

    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": settings.rewriter_max_tokens,
        "temperature": 0.85,  # slightly higher than plagiarism rewriter for variety
        "model": deployment,
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=body, headers=headers)

            if response.status_code != 200:
                raise RuntimeError(response.text[:300])

            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except Exception as exc:
            logger.warning(
                "general_rewrite_retry",
                attempt=attempt,
                error=str(exc),
            )
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))

    # unreachable, but keeps mypy happy
    raise RuntimeError("All retries exhausted")  # pragma: no cover


# ---------------------------------------------------------------------------
# Parse response
# ---------------------------------------------------------------------------

def _parse_variations(raw: str) -> list[str]:
    """Extract the list of rewrite variations from the LLM response."""
    # Try direct JSON parse first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(v, str) for v in parsed):
            return parsed[:3]
    except json.JSONDecodeError:
        pass

    # Try to find JSON array inside markdown code block
    import re
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return [str(v) for v in parsed[:3]]
        except json.JSONDecodeError:
            pass

    # Fallback: return the raw response as a single variation
    return [raw.strip()]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def general_rewrite(
    text: str,
    mode: Mode = "paraphrase",
    tone: Tone = "neutral",
    strength: Strength = "medium",
) -> dict:
    """Rewrite text using the general-purpose writing assistant.

    Returns a dict with: original, variations (list[str]), mode, tone,
    strength, elapsed_s.
    """
    start = time.perf_counter()

    stripped = text.strip()
    if len(stripped) < MIN_TEXT_LENGTH or len(stripped.split()) < MIN_WORD_COUNT:
        return {
            "original": text,
            "variations": [text],
            "mode": mode,
            "tone": tone,
            "strength": strength,
            "skipped": True,
            "skip_reason": "Text too short to rewrite.",
            "elapsed_s": 0.0,
        }

    # Build the user prompt
    mode_hint = _MODE_HINTS.get(mode, "")
    tone_hint = _TONE_HINTS.get(tone, "")

    user_prompt = f"""MODE: {mode.upper()}
TONE: {tone.upper()}
REWRITE STRENGTH: {strength.upper()}

Mode instruction: {mode_hint}
Tone instruction: {tone_hint}

TEXT TO REWRITE:
{stripped}
"""

    logger.info(
        "general_rewrite_started",
        text_length=len(stripped),
        mode=mode,
        tone=tone,
        strength=strength,
    )

    raw = await _call_openai(_REWRITE_SYSTEM, user_prompt)
    variations = _parse_variations(raw)

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "general_rewrite_complete",
        elapsed_s=elapsed,
        original_length=len(stripped),
        variation_count=len(variations),
    )

    return {
        "original": text,
        "variations": variations,
        "mode": mode,
        "tone": tone,
        "strength": strength,
        "skipped": False,
        "elapsed_s": elapsed,
    }
