"""Grammar & style checker tool — uses Azure OpenAI for analysis.

Identifies grammar issues, style problems, passive voice,
sentence complexity, and suggests fixes.
"""

from __future__ import annotations

import json
import time
import asyncio

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 2
MIN_TEXT_LENGTH = 20

_GRAMMAR_SYSTEM = """You are an expert grammar and style checker.

Analyze the given text for:
1. Grammar errors (subject-verb agreement, tense, articles, punctuation)
2. Spelling mistakes
3. Style issues (passive voice, wordiness, clichés, redundancy)
4. Sentence complexity (overly long or convoluted sentences)
5. Clarity problems (ambiguous or unclear phrasing)

OUTPUT FORMAT:
Return ONLY valid JSON with this structure:
{
  "issues": [
    {
      "type": "grammar|spelling|style|complexity|clarity",
      "severity": "error|warning|suggestion",
      "text": "the problematic text snippet",
      "message": "brief explanation of the issue",
      "suggestion": "corrected version of the text"
    }
  ],
  "corrected_text": "the full text with all corrections applied",
  "summary": {
    "total_issues": 0,
    "errors": 0,
    "warnings": 0,
    "suggestions": 0,
    "overall_quality": "excellent|good|fair|needs_improvement|poor"
  }
}

RULES:
- Be thorough but avoid false positives.
- Preserve the author's voice and meaning.
- Focus on genuine errors, not stylistic preferences.
- Keep suggestions concise and actionable.
- Do NOT wrap the JSON in markdown code blocks.
"""


async def _call_openai(system: str, user: str) -> str:
    """Call Azure OpenAI with retry."""
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    api_key = settings.azure_openai_api_key
    deployment = settings.azure_openai_deployment
    api_version = settings.azure_openai_api_version

    url = (
        f"{endpoint}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={api_version}"
    )

    headers = {"Content-Type": "application/json", "api-key": api_key}

    body = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": settings.rewriter_max_tokens,
        "temperature": 0.3,  # low temp for precise grammar checking
        "model": deployment,
    }

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=body, headers=headers)

            if resp.status_code != 200:
                raise RuntimeError(resp.text[:300])

            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

        except Exception as exc:
            logger.warning("grammar_check_retry", attempt=attempt, error=str(exc))
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))

    raise RuntimeError("All retries exhausted")  # pragma: no cover


def _parse_result(raw: str) -> dict:
    """Parse the LLM response into structured data."""
    # Try direct parse
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "issues" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to find JSON in markdown blocks
    import re
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Fallback
    return {
        "issues": [],
        "corrected_text": "",
        "summary": {
            "total_issues": 0,
            "errors": 0,
            "warnings": 0,
            "suggestions": 0,
            "overall_quality": "unknown",
        },
    }


async def check_grammar(text: str) -> dict:
    """Check text for grammar and style issues.

    Returns dict with issues, corrected_text, summary, elapsed_s.
    """
    start = time.perf_counter()

    stripped = text.strip()
    if len(stripped) < MIN_TEXT_LENGTH:
        return {
            "issues": [],
            "corrected_text": text,
            "summary": {
                "total_issues": 0,
                "errors": 0,
                "warnings": 0,
                "suggestions": 0,
                "overall_quality": "text_too_short",
            },
            "skipped": True,
            "elapsed_s": 0.0,
        }

    user_prompt = f"""Check the following text for grammar, spelling, style, and clarity issues:

{stripped}"""

    raw = await _call_openai(_GRAMMAR_SYSTEM, user_prompt)
    result = _parse_result(raw)

    elapsed = round(time.perf_counter() - start, 3)

    # Ensure summary counts are correct
    issues = result.get("issues", [])
    errors = sum(1 for i in issues if i.get("severity") == "error")
    warnings = sum(1 for i in issues if i.get("severity") == "warning")
    suggestions = sum(1 for i in issues if i.get("severity") == "suggestion")

    result["summary"] = {
        "total_issues": len(issues),
        "errors": errors,
        "warnings": warnings,
        "suggestions": suggestions,
        "overall_quality": result.get("summary", {}).get(
            "overall_quality", _quality_label(errors, warnings, len(stripped))
        ),
    }
    result["elapsed_s"] = elapsed
    result["skipped"] = False

    logger.info(
        "grammar_check_complete",
        total_issues=len(issues),
        errors=errors,
        warnings=warnings,
        elapsed_s=elapsed,
    )

    return result


def _quality_label(errors: int, warnings: int, text_len: int) -> str:
    """Compute quality label from error/warning counts."""
    # Normalize by text length (per 1000 chars)
    per_k = ((errors * 3 + warnings) / max(text_len, 1)) * 1000
    if per_k < 1:
        return "excellent"
    if per_k < 3:
        return "good"
    if per_k < 6:
        return "fair"
    if per_k < 10:
        return "needs_improvement"
    return "poor"
