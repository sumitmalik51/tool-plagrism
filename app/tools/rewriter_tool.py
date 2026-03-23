"""AI Rewriter tool — rewrites text using Azure OpenAI to eliminate plagiarism.

Standalone, framework-agnostic tool. Accepts clear inputs, returns structured JSON.
Supports two modes:
  1. **Paragraph**: Rewrites a single flagged passage.
  2. **Document**: Rewrites an entire document, focusing on flagged sections.
"""

from __future__ import annotations

import asyncio
import time
from typing import Literal

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PARAGRAPH_SYSTEM = """You are an expert academic writing assistant. Your task is to rewrite the given paragraph to eliminate plagiarism while:
1. Preserving the original meaning and key information accurately.
2. Using completely different sentence structures and word choices.
3. Maintaining an academic/professional tone appropriate for the context.
4. Ensuring the rewritten text is natural, fluent, and human-like.
5. NOT adding new information that wasn't in the original.
6. NOT removing critical data, facts, or citations from the original.

Return ONLY the rewritten text — no explanations, no preamble."""

_DOCUMENT_SYSTEM = """You are an expert academic writing assistant. You will receive a full document with specific passages marked as [FLAGGED] that were detected as potentially plagiarised.

Your task:
1. Rewrite ONLY the [FLAGGED] sections to eliminate plagiarism.
2. Leave unflagged sections UNCHANGED (copy them verbatim).
3. For each flagged section, use completely different sentence structures and word choices.
4. Preserve all meaning, facts, data, and citations.
5. Maintain consistent tone and style throughout.
6. Ensure smooth transitions between rewritten and unchanged sections.

Return the COMPLETE document with the rewrites applied — no explanations, no markers."""


# ---------------------------------------------------------------------------
# Azure OpenAI client helper
# ---------------------------------------------------------------------------

async def _call_azure_openai(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """Call Azure OpenAI Chat Completions API.

    Raises:
        ValueError: If Azure OpenAI is not configured.
        RuntimeError: If API call fails.
    """
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    api_key = settings.azure_openai_api_key
    deployment = settings.azure_openai_deployment
    api_version = settings.azure_openai_api_version

    if not endpoint or not api_key:
        raise ValueError(
            "Azure OpenAI is not configured. "
            "Set PG_AZURE_OPENAI_ENDPOINT and PG_AZURE_OPENAI_API_KEY."
        )

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
        "max_tokens": max_tokens or settings.rewriter_max_tokens,
        "temperature": temperature if temperature is not None else settings.rewriter_temperature,
        "model": deployment,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=body, headers=headers)

        if response.status_code != 200:
            error_detail = response.text[:500]
            logger.error(
                "azure_openai_error",
                status=response.status_code,
                detail=error_detail,
            )
            raise RuntimeError(
                f"Azure OpenAI returned {response.status_code}: {error_detail}"
            )

        data = response.json()

    choice = data.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")

    if not content:
        raise RuntimeError("Azure OpenAI returned empty content")

    return content.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def rewrite_paragraph(
    text: str,
    context: str = "",
    tone: str = "academic",
) -> dict:
    """Rewrite a single paragraph to eliminate plagiarism.

    Args:
        text: The flagged paragraph to rewrite.
        context: Optional surrounding context for better rewrites.
        tone: Writing tone — 'academic', 'professional', or 'casual'.

    Returns:
        Dict with ``original``, ``rewritten``, ``tone``, ``elapsed_s``.
    """
    start = time.perf_counter()

    user_prompt = f"Tone: {tone}\n\n"
    if context:
        user_prompt += f"Context (surrounding text, for reference only — do NOT rewrite this):\n{context}\n\n"
    user_prompt += f"Paragraph to rewrite:\n{text}"

    logger.info("rewrite_paragraph_started", text_length=len(text), tone=tone)

    rewritten = await _call_azure_openai(
        system_prompt=_PARAGRAPH_SYSTEM,
        user_prompt=user_prompt,
    )

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "rewrite_paragraph_complete",
        original_length=len(text),
        rewritten_length=len(rewritten),
        elapsed_s=elapsed,
    )

    return {
        "original": text,
        "rewritten": rewritten,
        "tone": tone,
        "elapsed_s": elapsed,
    }


async def rewrite_document(
    document_text: str,
    flagged_passages: list[str],
    tone: str = "academic",
) -> dict:
    """Rewrite flagged passages within a full document.

    Args:
        document_text: The entire document text.
        flagged_passages: List of passages that were flagged as plagiarised.
        tone: Writing tone — 'academic', 'professional', or 'casual'.

    Returns:
        Dict with ``original``, ``rewritten``, ``passages_rewritten``,
        ``tone``, ``elapsed_s``.
    """
    start = time.perf_counter()

    # Mark flagged passages in the document
    marked_doc = document_text
    passages_found = 0

    for passage in flagged_passages:
        # Try exact match first, then fuzzy (first 80 chars)
        if passage in marked_doc:
            marked_doc = marked_doc.replace(
                passage, f"[FLAGGED]{passage}[/FLAGGED]", 1
            )
            passages_found += 1
        else:
            # Try matching by the first 80 chars (handles truncated passages)
            snippet = passage[:80]
            idx = marked_doc.find(snippet)
            if idx != -1:
                # Find the end of the sentence or paragraph
                end = marked_doc.find("\n", idx + len(snippet))
                if end == -1:
                    end = min(idx + len(passage) + 100, len(marked_doc))
                original_section = marked_doc[idx:end]
                marked_doc = (
                    marked_doc[:idx]
                    + f"[FLAGGED]{original_section}[/FLAGGED]"
                    + marked_doc[end:]
                )
                passages_found += 1

    if passages_found == 0:
        # No passages could be located — rewrite the entire document
        logger.warning(
            "no_flagged_passages_located",
            total_flagged=len(flagged_passages),
        )
        user_prompt = (
            f"Tone: {tone}\n\n"
            f"The entire document below was flagged for potential plagiarism. "
            f"Rewrite it completely while preserving all meaning:\n\n{document_text}"
        )
    else:
        user_prompt = (
            f"Tone: {tone}\n\n"
            f"Document with {passages_found} flagged section(s) marked with "
            f"[FLAGGED]...[/FLAGGED] tags:\n\n{marked_doc}"
        )

    logger.info(
        "rewrite_document_started",
        doc_length=len(document_text),
        flagged_count=len(flagged_passages),
        passages_found=passages_found,
        tone=tone,
    )

    # For very long documents, chunk and rewrite in parts
    if len(user_prompt) > 15000:
        rewritten = await _rewrite_long_document(
            marked_doc, passages_found, tone
        )
    else:
        rewritten = await _call_azure_openai(
            system_prompt=_DOCUMENT_SYSTEM,
            user_prompt=user_prompt,
        )

    elapsed = round(time.perf_counter() - start, 3)

    logger.info(
        "rewrite_document_complete",
        original_length=len(document_text),
        rewritten_length=len(rewritten),
        passages_rewritten=passages_found,
        elapsed_s=elapsed,
    )

    return {
        "original": document_text,
        "rewritten": rewritten,
        "passages_rewritten": passages_found,
        "tone": tone,
        "elapsed_s": elapsed,
    }


async def _rewrite_long_document(
    marked_doc: str,
    passages_found: int,
    tone: str,
) -> str:
    """Rewrite a long document by splitting it into sections.

    Each section is sent to the API individually, then reassembled.
    """
    # Split on double-newlines to preserve paragraph boundaries
    paragraphs = marked_doc.split("\n\n")
    chunks: list[list[str]] = []
    current_chunk: list[str] = []
    current_length = 0

    for para in paragraphs:
        if current_length + len(para) > 8000 and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_length = 0
        current_chunk.append(para)
        current_length += len(para) + 2

    if current_chunk:
        chunks.append(current_chunk)

    logger.info("rewrite_long_doc_chunked", chunk_count=len(chunks))

    rewritten_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_text = "\n\n".join(chunk)

        # Only send to API if chunk contains flagged content
        if "[FLAGGED]" in chunk_text:
            user_prompt = (
                f"Tone: {tone}\n\n"
                f"This is section {i + 1} of {len(chunks)} of a longer document. "
                f"Rewrite ONLY the [FLAGGED] sections:\n\n{chunk_text}"
            )
            rewritten = await _call_azure_openai(
                system_prompt=_DOCUMENT_SYSTEM,
                user_prompt=user_prompt,
            )
            rewritten_parts.append(rewritten)
        else:
            # No flagged content — keep as-is
            rewritten_parts.append(chunk_text)

    return "\n\n".join(rewritten_parts)
