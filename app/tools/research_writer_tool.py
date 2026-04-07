"""Research Writer tool — GPT-4o vision-powered academic paragraph generation.

Accepts a graph/chart image + student explanation, generates an original
academic paragraph with hallucination guards, graph type detection, blended
confidence scoring (model + image quality), and figure caption generation.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import re
import time
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageStat

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 2
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
MIN_IMAGE_DIM = 50  # pixels
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "GIF"}
ALLOWED_URL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# ═══════════════════════════════════════════════════════════════════════════
# Image handling
# ═══════════════════════════════════════════════════════════════════════════


def _compute_image_quality(img: Image.Image) -> float:
    """Compute an objective image quality score (0.0–1.0) using Pillow metrics."""
    w, h = img.size
    pixels = w * h

    # Resolution score
    if pixels < 100_000:
        resolution_score = 0.3
    elif pixels < 500_000:
        resolution_score = 0.6
    elif pixels < 2_000_000:
        resolution_score = 0.8
    else:
        resolution_score = 1.0

    # Contrast score (grayscale stddev, 0–80 range → 0.0–1.0)
    try:
        gray = img.convert("L")
        stddev = ImageStat.Stat(gray).stddev[0]
        contrast_score = min(stddev / 80.0, 1.0)
    except Exception:
        contrast_score = 0.5

    # Aspect ratio penalty (extreme ratios get 0.7x)
    ratio = max(w, h) / max(min(w, h), 1)
    aspect_penalty = 0.7 if ratio > 4.0 else 1.0

    score = (resolution_score * 0.5 + contrast_score * 0.4) * aspect_penalty + 0.1
    return round(min(score, 1.0), 3)


def validate_image(file_bytes: bytes) -> tuple[str, str, float]:
    """Validate image bytes and return (base64_str, mime_type, quality_score).

    Raises ValueError on invalid/corrupt/too-small/junk images.
    """
    if len(file_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds 20 MB limit")

    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
        # Re-open after verify (verify closes the fp)
        img = Image.open(io.BytesIO(file_bytes))
    except Exception:
        raise ValueError("Corrupt or unreadable image file")

    fmt = img.format
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported image format: {fmt}. Use PNG, JPG, WEBP, or GIF.")

    w, h = img.size
    if w < MIN_IMAGE_DIM or h < MIN_IMAGE_DIM:
        raise ValueError("Image too small — must be at least 50×50 pixels")

    quality = _compute_image_quality(img)
    if quality < 0.15:
        raise ValueError("Image does not appear to contain a readable graph")

    mime_map = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
    mime = mime_map.get(fmt, "image/png")
    b64 = base64.b64encode(file_bytes).decode("ascii")

    logger.info("image_validated", format=fmt, width=w, height=h, quality=quality)
    return b64, mime, quality


async def fetch_image_from_url(url: str) -> tuple[str, str, float]:
    """Download an image from a URL and validate it.

    SSRF protection: HTTPS only, no private/localhost IPs, image extensions only.
    Raises ValueError on invalid URLs or failed downloads.
    """
    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme != "https":
        raise ValueError("Only HTTPS image URLs are allowed")

    # Extension check
    path_lower = parsed.path.lower()
    if not any(path_lower.endswith(ext) for ext in ALLOWED_URL_EXTENSIONS):
        raise ValueError("URL must point to an image file (.png, .jpg, .jpeg, .webp, .gif)")

    # Hostname SSRF check — reject private/localhost IPs
    hostname = parsed.hostname or ""
    if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        raise ValueError("URL points to a local address — not allowed")
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved:
            raise ValueError("URL points to a private/reserved address — not allowed")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
        # hostname is a domain name, not an IP — that's fine

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "PlagiarismGuard/1.0"})
        if resp.status_code != 200:
            raise ValueError(f"Failed to fetch image: HTTP {resp.status_code}")
        if len(resp.content) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds 20 MB limit")
    except httpx.TimeoutException:
        raise ValueError("Image URL timed out after 5 seconds")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to fetch image: {e}")

    return validate_image(resp.content)


# ═══════════════════════════════════════════════════════════════════════════
# Azure OpenAI helpers
# ═══════════════════════════════════════════════════════════════════════════


async def _call_openai_vision(
    system_prompt: str,
    user_content: list[dict[str, Any]],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """Call Azure OpenAI with multimodal (vision) content, with retry."""
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    api_key = settings.azure_openai_api_key
    deployment = settings.azure_openai_deployment
    api_version = settings.azure_openai_api_version

    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    headers = {"Content-Type": "application/json", "api-key": api_key}
    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
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
            logger.warning("rw_openai_retry", attempt=attempt, error=str(e))
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError("OpenAI call failed after retries")


async def _call_openai_text(system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
    """Call Azure OpenAI with text-only content."""
    return await _call_openai_vision(
        system_prompt,
        [{"type": "text", "text": user_prompt}],
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Response parsing
# ═══════════════════════════════════════════════════════════════════════════


def _safe_parse(output: str) -> dict[str, Any]:
    """Parse GPT JSON output with fallbacks for markdown fences and malformed output."""
    cleaned = output.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Try regex extraction of JSON object
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    # Ultimate fallback — use raw text as paragraph
    return {
        "paragraph": cleaned,
        "figure_description": "",
        "key_findings": [],
        "suggested_citation_placeholders": [],
        "graph_type": "other",
        "graph_type_confidence": 0.0,
        "model_confidence": 0.5,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Prompts
# ═══════════════════════════════════════════════════════════════════════════

_SECTION_HINTS = {
    "results": (
        "Write a RESULTS section paragraph. Focus on: data trends, statistical patterns, "
        "quantitative observations visible in the graph, and proper figure references (e.g., 'As shown in Figure 1…')."
    ),
    "discussion": (
        "Write a DISCUSSION section paragraph. Focus on: implications of the data, comparison with "
        "expected outcomes, possible explanations for observed trends, limitations, and broader significance."
    ),
    "methodology": (
        "Write a METHODOLOGY section paragraph. Focus on: the experimental or analytical approach "
        "the graph represents, data collection context, variables measured, and how the visualization "
        "supports the research design."
    ),
    "analysis": (
        "Write an ANALYSIS section paragraph. Focus on: deep interpretation of the data, "
        "cause-effect relationships, statistical significance, comparative insights, and the "
        "meaning of patterns observed."
    ),
}

_LEVEL_HINTS = {
    "undergraduate": "Use clear, straightforward sentences with basic vocabulary. Explain concepts explicitly.",
    "masters": "Use moderate complexity with domain-specific terminology and analytical depth.",
    "phd": "Use sophisticated vocabulary, nuanced arguments, critical analysis, and methodological rigor.",
}

_GRAPH_TYPE_HINTS = {
    "line_chart": "trend over time or continuous progression",
    "bar_chart": "comparative analysis across categories",
    "scatter_plot": "correlation or relationship between variables",
    "pie_chart": "distribution or proportion of components",
    "histogram": "frequency distribution of data",
    "heatmap": "intensity or density patterns across two dimensions",
    "box_plot": "statistical distribution and variability",
}

_SYSTEM_PROMPT = """You are an expert academic writing assistant specializing in generating original
research paper paragraphs from graph and chart visualizations.

HALLUCINATION GUARDS (CRITICAL):
- Only describe visible trends and patterns in the graph.
- Do NOT invent or assume numeric values unless they are clearly legible in the image.
- If data is ambiguous, use hedging language: "the data suggests…", "approximately…", "a noticeable trend…"
- Do NOT fabricate study names, author names, or citation details.
- If axes or labels are unreadable, state what IS visible and note the limitation.
- Where citations would normally appear, insert placeholder markers like "(Author, Year)" that the student will fill in.

ORIGINALITY REQUIREMENTS:
- Write completely original text — do not reproduce phrases from known sources.
- Vary sentence structure and vocabulary to ensure uniqueness.
- The paragraph should read as if written by a human researcher, not AI.

OUTPUT FORMAT:
Return ONLY a valid JSON object (no markdown fences) with these keys:
{
    "paragraph": "The generated academic paragraph...",
    "figure_description": "What you observe in the graph/chart...",
    "key_findings": ["Finding 1", "Finding 2", ...],
    "suggested_citation_placeholders": ["(Author, Year)", ...],
    "graph_type": "line_chart|bar_chart|scatter_plot|pie_chart|histogram|heatmap|box_plot|other",
    "graph_type_confidence": 0.0 to 1.0,
    "model_confidence": 0.0 to 1.0
}

The "model_confidence" should reflect how clearly you can read the graph:
- 1.0 = perfectly clear labels, data points, and axes
- 0.5 = partially readable, some ambiguity
- 0.0 = very unclear, mostly guessing
"""

_CAPTION_SYSTEM = """You are an academic figure caption generator. Given a graph/chart image and
a brief description, generate a concise academic figure caption in the format:
"Figure N: [Description of what the figure shows, including key variables and timeframe if visible]."

Keep it to 1-2 sentences. Be factual — only describe what is visible.
Return ONLY the caption text, nothing else."""

_IMPROVE_SYSTEM = """You are an academic writing coach. The student has provided a brief description
of their graph/chart. Your job is to improve and expand their description to be more precise,
specific, and academically useful. Include:
- What type of graph it appears to be
- The variables shown (if mentioned)
- Key trends they should highlight
- Suggested context or framing

Return ONLY the improved description text (2-4 sentences), nothing else."""

_EXPAND_SYSTEM = """You are an expert academic writing assistant. Your task is to expand a single
paragraph into a complete section of a research paper.

CRITICAL ANTI-DRIFT RULES:
- Expand ONLY based on the information in the given paragraph.
- Do NOT introduce new data points, statistics, or claims not present in the original.
- Do NOT reference studies, papers, or sources not mentioned in the original.
- Maintain consistency with the original findings — add depth, transitions, and context only.
- If the paragraph mentions approximate values, keep them approximate — do not fabricate precision.
- Add transitions between paragraphs for smooth flow.
- If citation placeholders exist (e.g., "(Author, Year)"), keep them but do not invent new ones.

Return ONLY a valid JSON object:
{"expanded_text": "Full expanded section text...", "paragraph_count": N, "word_count": N}
"""

# ═══════════════════════════════════════════════════════════════════════════
# Core functions
# ═══════════════════════════════════════════════════════════════════════════


def hash_request(
    image_base64: str,
    explanation: str,
    section_type: str,
    level: str,
    tone: str,
    citation_style: str,
) -> str:
    """SHA-256 hash of all inputs for caching."""
    raw = f"{image_base64[:200]}|{explanation}|{section_type}|{level}|{tone}|{citation_style}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def generate_paragraph(
    image_base64: str,
    mime_type: str,
    explanation: str,
    section_type: Literal["results", "discussion", "methodology", "analysis"] = "results",
    citation_style: str = "apa",
    tone: Literal["academic", "professional"] = "academic",
    level: Literal["undergraduate", "masters", "phd"] = "undergraduate",
    image_quality_score: float = 0.5,
) -> dict[str, Any]:
    """Generate an academic paragraph from graph image + explanation.

    Returns dict with paragraph, figure_caption, confidence scores, etc.
    Falls back to text-only generation if vision fails.
    """
    start = time.perf_counter()
    image_used = True

    section_hint = _SECTION_HINTS.get(section_type, _SECTION_HINTS["results"])
    level_hint = _LEVEL_HINTS.get(level, _LEVEL_HINTS["undergraduate"])

    user_text = (
        f"Section type: {section_type}\n"
        f"Academic level: {level}\n"
        f"Tone: {tone}\n"
        f"Citation style: {citation_style}\n\n"
        f"Student's explanation of the graph:\n{explanation}\n\n"
        f"Instructions:\n{section_hint}\n{level_hint}\n"
    )

    # Try vision call first
    try:
        user_content = [
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
            {"type": "text", "text": user_text},
        ]
        raw = await _call_openai_vision(_SYSTEM_PROMPT, user_content)
    except Exception as vision_err:
        logger.warning("rw_vision_fallback", error=str(vision_err))
        image_used = False
        # Fallback to text-only
        fallback_text = (
            f"[NOTE: Image analysis was unavailable. Generate based on the description only.]\n\n"
            f"{user_text}"
        )
        raw = await _call_openai_text(_SYSTEM_PROMPT, fallback_text)

    parsed = _safe_parse(raw)

    # Blend confidence
    model_conf = float(parsed.get("model_confidence", 0.5))
    model_conf = max(0.0, min(1.0, model_conf))
    if image_used:
        confidence = round(model_conf * 0.7 + image_quality_score * 0.3, 3)
    else:
        confidence = round(model_conf * 0.7, 3)

    # Graph type warning
    graph_type_conf = float(parsed.get("graph_type_confidence", 0.0))
    graph_type_warning = None
    if graph_type_conf < 0.6:
        graph_type_warning = "Detected graph type may be inaccurate"

    # Tailor paragraph style hint based on detected graph type (if applicable)
    graph_type = parsed.get("graph_type", "other")
    if graph_type in _GRAPH_TYPE_HINTS:
        style_context = _GRAPH_TYPE_HINTS[graph_type]
        logger.debug("rw_graph_style", type=graph_type, style=style_context)

    # Generate figure caption in parallel (lightweight call)
    try:
        caption = await generate_figure_caption(image_base64, mime_type, explanation)
    except Exception:
        caption = ""

    elapsed = round(time.perf_counter() - start, 2)

    result = {
        "paragraph": parsed.get("paragraph", ""),
        "figure_caption": caption,
        "figure_description": parsed.get("figure_description", ""),
        "key_findings": parsed.get("key_findings", []),
        "suggested_citation_placeholders": parsed.get("suggested_citation_placeholders", []),
        "graph_type": graph_type,
        "graph_type_confidence": round(graph_type_conf, 3),
        "graph_type_warning": graph_type_warning,
        "model_confidence": round(model_conf, 3),
        "image_quality_score": image_quality_score,
        "confidence": confidence,
        "image_used": image_used,
        "level": level,
        "section_type": section_type,
        "elapsed_s": elapsed,
    }
    logger.info(
        "rw_paragraph_generated",
        section_type=section_type,
        level=level,
        image_used=image_used,
        confidence=confidence,
        graph_type=graph_type,
        elapsed_s=elapsed,
    )
    return result


async def generate_figure_caption(
    image_base64: str,
    mime_type: str,
    explanation: str,
) -> str:
    """Generate a concise academic figure caption from the graph image."""
    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
        {"type": "text", "text": f"Student's description: {explanation}"},
    ]
    return await _call_openai_vision(
        _CAPTION_SYSTEM, user_content, max_tokens=150, temperature=0.3,
    )


async def improve_explanation(
    explanation: str,
    image_base64: str,
    mime_type: str,
) -> str:
    """Improve a student's graph explanation to be more precise and academic."""
    user_content = [
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
        {"type": "text", "text": f"Student's original description:\n{explanation}"},
    ]
    return await _call_openai_vision(
        _IMPROVE_SYSTEM, user_content, max_tokens=300, temperature=0.5,
    )


async def expand_section(
    paragraph: str,
    section_type: str = "results",
    target_length: Literal["medium", "full"] = "medium",
    level: str = "undergraduate",
) -> dict[str, Any]:
    """Expand a single paragraph into a multi-paragraph section."""
    start = time.perf_counter()
    length_hint = "3 paragraphs" if target_length == "medium" else "4-5 paragraphs"
    level_hint = _LEVEL_HINTS.get(level, _LEVEL_HINTS["undergraduate"])

    user_prompt = (
        f"Section type: {section_type}\n"
        f"Target length: {length_hint}\n"
        f"Academic level: {level}  ({level_hint})\n\n"
        f"Original paragraph to expand:\n{paragraph}"
    )

    raw = await _call_openai_text(_EXPAND_SYSTEM, user_prompt, max_tokens=4096, temperature=0.7)
    parsed = _safe_parse(raw)

    expanded = parsed.get("expanded_text", raw)
    word_count = len(expanded.split())
    # Count paragraphs by double newlines
    para_count = len([p for p in expanded.split("\n\n") if p.strip()]) or 1

    elapsed = round(time.perf_counter() - start, 2)
    return {
        "expanded_text": expanded,
        "paragraph_count": int(parsed.get("paragraph_count", para_count)),
        "word_count": int(parsed.get("word_count", word_count)),
        "elapsed_s": elapsed,
    }
