"""
AI Rewriter tool — PRODUCTION VERSION

Combines:
- Robust document handling
- Anti-plagiarism optimized rewriting
- Multi-variant outputs
- Retry + fallback safety
"""

from __future__ import annotations

import time
import json
import asyncio
from typing import Literal

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_REWRITE_LENGTH = 30
MIN_REWRITE_WORDS = 3
MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PARAGRAPH_SYSTEM = """You are an expert academic rewriting engine specialized in plagiarism removal.

STRICT REQUIREMENTS:
1. Preserve EXACT meaning, facts, numbers, intent.
2. Use different sentence structures (not synonyms only).
3. Avoid copying phrases longer than 3 words.
4. Ensure output is plagiarism-safe.
5. Do NOT add or remove information.
6. Maintain requested tone.
7. Keep similar length (±15%).
8. Ensure natural human fluency.

REWRITE STRENGTH:
- LOW: minimal change
- MEDIUM: moderate
- HIGH: aggressive restructuring

QUALITY CHECK:
- Would plagiarism still trigger? If yes, rewrite.
- Did meaning change? Fix it.

OUTPUT:
Return ONLY a JSON array of 3 rewritten strings. Example:
["First rewrite here.", "Second rewrite here.", "Third rewrite here."]
Do NOT wrap in objects or add keys — just plain text strings in a JSON array.
"""

_DOCUMENT_SYSTEM = """You are an expert rewriting engine.

Rules:
1. Rewrite ONLY [FLAGGED] sections.
2. Keep everything else unchanged.
3. Ensure plagiarism-safe rewriting.
4. Preserve meaning exactly.
5. Maintain tone consistency.

Return full document only.
"""

# ---------------------------------------------------------------------------
# Azure OpenAI call with retry
# ---------------------------------------------------------------------------

async def _call_azure_openai(system_prompt, user_prompt):

    endpoint = settings.azure_openai_endpoint.rstrip("/")
    api_key = settings.azure_openai_api_key
    deployment = settings.azure_openai_deployment
    api_version = settings.azure_openai_api_version

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"

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
        "temperature": settings.rewriter_temperature,
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

        except Exception as e:
            logger.warning("openai_retry", attempt=attempt, error=str(e))
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_parse_rewrites(output: str) -> list[str]:
    try:
        parsed = json.loads(output)
        if isinstance(parsed, list):
            # Ensure each element is a plain string
            result = []
            for item in parsed[:3]:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    # AI sometimes returns {"text": "...", ...}
                    result.append(
                        item.get("text")
                        or item.get("rewrite")
                        or item.get("rewritten")
                        or item.get("content")
                        or str(item)
                    )
                else:
                    result.append(str(item))
            return result if result else [output]
        elif isinstance(parsed, str):
            return [parsed]
    except Exception:
        pass

    # fallback: strip markdown code fences if present
    cleaned = output.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return _safe_parse_rewrites(cleaned)

    return [cleaned]

# ---------------------------------------------------------------------------
# Paragraph Rewrite
# ---------------------------------------------------------------------------

async def rewrite_paragraph(
    text: str,
    context: str = "",
    tone: Literal["academic", "professional", "casual"] = "academic",
    strength: Literal["low", "medium", "high"] = "medium",
) -> dict:

    start = time.perf_counter()

    stripped = text.strip()
    if len(stripped) < MIN_REWRITE_LENGTH or len(stripped.split()) < MIN_REWRITE_WORDS:
        return {
            "original": text,
            "rewrites": [text],
            "skipped": True,
        }

    user_prompt = f"""
Tone: {tone}
Rewrite Strength: {strength}

{f"Context (reference only): {context}" if context else ""}

Rewrite this paragraph:

{text}
"""

    raw = await _call_azure_openai(_PARAGRAPH_SYSTEM, user_prompt)
    rewrites = _safe_parse_rewrites(raw)

    return {
        "original": text,
        "rewrites": rewrites,
        "tone": tone,
        "strength": strength,
        "elapsed_s": round(time.perf_counter() - start, 3),
    }

# ---------------------------------------------------------------------------
# Document Rewrite
# ---------------------------------------------------------------------------

async def rewrite_document(
    document_text: str,
    flagged_passages: list[str],
    tone: str = "academic",
) -> dict:

    start = time.perf_counter()
    marked_doc = document_text
    passages_found = 0

    # filter short
    flagged_passages = [
        p for p in flagged_passages
        if len(p.strip()) >= MIN_REWRITE_LENGTH
    ]

    for passage in flagged_passages:
        if passage in marked_doc:
            marked_doc = marked_doc.replace(
                passage, f"[FLAGGED]{passage}[/FLAGGED]", 1
            )
            passages_found += 1
        else:
            snippet = passage[:80]
            idx = marked_doc.find(snippet)
            if idx != -1:
                end = marked_doc.find("\n", idx + len(snippet))
                if end == -1:
                    end = idx + len(snippet) + 100
                section = marked_doc[idx:end]
                marked_doc = (
                    marked_doc[:idx]
                    + f"[FLAGGED]{section}[/FLAGGED]"
                    + marked_doc[end:]
                )
                passages_found += 1

    if passages_found == 0:
        user_prompt = f"""
Tone: {tone}

Rewrite entire document:

{document_text}
"""
    else:
        user_prompt = f"""
Tone: {tone}

Document:
{marked_doc}
"""

    # chunk if large
    if len(user_prompt) > 15000:
        rewritten = await _rewrite_long_document(marked_doc, tone)
    else:
        rewritten = await _call_azure_openai(_DOCUMENT_SYSTEM, user_prompt)

    return {
        "original": document_text,
        "rewritten": rewritten,
        "passages_rewritten": passages_found,
        "elapsed_s": round(time.perf_counter() - start, 3),
    }

# ---------------------------------------------------------------------------
# Long document chunking
# ---------------------------------------------------------------------------

async def _rewrite_long_document(marked_doc: str, tone: str):

    paragraphs = marked_doc.split("\n\n")
    chunks = []
    current = []
    length = 0

    for p in paragraphs:
        if length + len(p) > 8000 and current:
            chunks.append(current)
            current = []
            length = 0
        current.append(p)
        length += len(p)

    if current:
        chunks.append(current)

    results = []

    for chunk in chunks:
        text = "\n\n".join(chunk)

        if "[FLAGGED]" in text:
            prompt = f"Tone: {tone}\n\n{text}"
            rewritten = await _call_azure_openai(_DOCUMENT_SYSTEM, prompt)
            results.append(rewritten)
        else:
            results.append(text)

    return "\n\n".join(results)