"""Scoring service — weighted aggregation of agent outputs.

Keeps all scoring math in a standalone, testable service.
The aggregation_agent delegates to this module so that
business logic stays out of the agent class itself (per AGENT_RULES).
"""

from __future__ import annotations

import re

from app.config import settings
from app.models.schemas import AgentOutput, FlaggedPassage
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Map agent names → config weight attribute names
_WEIGHT_MAP: dict[str, str] = {
    "semantic_agent": "weight_semantic",
    "web_search_agent": "weight_web_search",
    "academic_agent": "weight_academic",
    "ai_detection_agent": "weight_ai_detection",
}


def get_agent_weight(agent_name: str) -> float:
    """Return the configured weight for an agent (0.0 if unknown)."""
    attr = _WEIGHT_MAP.get(agent_name)
    if attr is None:
        return 0.0
    return getattr(settings, attr, 0.0)


def compute_weighted_score(agent_outputs: list[AgentOutput]) -> float:
    """Compute a single plagiarism score from multiple agent outputs.

    Each agent's score (0-100) is multiplied by its configured weight.
    If an agent produced an error (score == 0 and confidence == 0),
    its weight is redistributed proportionally among the remaining agents.

    Returns:
        A score in [0, 100].
    """
    if not agent_outputs:
        return 0.0

    # Separate healthy results from errored ones
    healthy: list[tuple[AgentOutput, float]] = []
    for output in agent_outputs:
        w = get_agent_weight(output.agent_name)
        if w <= 0:
            continue
        is_error = output.confidence == 0.0 and "error" in output.details
        if not is_error:
            healthy.append((output, w))

    if not healthy:
        return 0.0

    # Normalise weights so they sum to 1.0
    total_weight = sum(w for _, w in healthy)
    if total_weight <= 0:
        return 0.0

    score = sum(output.score * (w / total_weight) for output, w in healthy)
    score = round(min(max(score, 0.0), 100.0), 2)

    logger.info(
        "weighted_score_computed",
        score=score,
        agents_used=[o.agent_name for o, _ in healthy],
        total_weight=round(total_weight, 4),
    )
    return score


# ---------------------------------------------------------------------------
# Helpers for cleaning / filtering flagged passages
# ---------------------------------------------------------------------------

# Matches citation metadata markers (emails, publication dates, correspondence)
_CITATION_RE = re.compile(
    r'(?:'
    r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'          # email
    r'|(?:Received|Accepted|Published|Submitted):\s*\d'          # pub dates
    r'|\*\s*Correspondence:'                                     # corresp
    r')',
    re.IGNORECASE,
)

# Leading lowercase fragment left by a mid-word chunk split (e.g. "rticle ")
# Only matches when followed by an uppercase letter (the real sentence start).
_LEADING_FRAGMENT_RE = re.compile(r'^[a-z]{1,10}\s+(?=[A-Z])')

# Matches URLs (http/https/ftp or naked domain patterns like "pubs.acs.org/...")
_URL_RE = re.compile(
    r'https?://[^\s]+|ftp://[^\s]+|(?:[a-z0-9-]+\.)+(?:com|org|net|edu|gov|io|co)\b[/\S]*',
    re.IGNORECASE,
)

# DOI patterns
_DOI_RE = re.compile(r'10\.\d{4,}/[^\s]+', re.IGNORECASE)

# Reference list markers: "[1] ...", "1. Author (2020)", etc.
_REF_MARKER_RE = re.compile(r'^\s*\[?\d{1,3}\]?[\s.)\-]')


def _is_citation_metadata(text: str) -> bool:
    """Return True if text is primarily citation/bibliographic metadata."""
    return len(_CITATION_RE.findall(text)) >= 2


def _is_reference_line(text: str) -> bool:
    """Return True if text looks like a bibliography/reference entry or URL-only snippet.

    Catches:
    - Text that's mostly URLs, DOIs, or domain names
    - Short text with a reference-list prefix ("[1]", "2.")
    - Short passages that are source titles/headers with no real sentence structure
    """
    stripped = text.strip()
    words = stripped.split()
    word_count = len(words)

    # Strip all URLs and DOIs from the text
    no_urls = _URL_RE.sub(" ", stripped)
    no_urls = _DOI_RE.sub(" ", no_urls)
    no_urls = re.sub(r'\s+', ' ', no_urls).strip()

    remaining_words = len(no_urls.split()) if no_urls else 0

    # If removing URLs/DOIs leaves very little, it's a reference line
    if word_count > 0 and remaining_words <= 3:
        return True

    # Short passages (≤ 15 words total): check for sentence structure
    # Real prose contains function words (articles, verbs, conjunctions)
    # Source titles / headers are mostly proper nouns and labels
    if word_count <= 15 and remaining_words <= 10:
        has_sentence_structure = bool(
            re.search(
                r'\b(?:is|are|was|were|has|have|had|been|be|being|'
                r'the|this|these|those|which|that|who|whom|whose|'
                r'can|could|may|might|shall|should|will|would|must|'
                r'because|although|however|therefore|moreover|furthermore|'
                r'with|from|into|between|through|during|before|after|'
                r'if|when|where|while|since|until|unless)\b',
                no_urls,
                re.IGNORECASE,
            )
        )
        if not has_sentence_structure:
            return True

    # Reference marker prefix: "[1] ...", "2. Author..."
    if word_count <= 15 and _REF_MARKER_RE.match(stripped):
        if len(no_urls) < 60:
            return True

    return False


def _trim_leading_fragment(text: str) -> str:
    """Trim a partial-word artefact from the start of text.

    Example: ``"rticle Stability of..."`` → ``"Stability of..."``.
    Only trims when the text starts with a short lowercase run (≤10 chars)
    followed by whitespace *and* an uppercase letter — a strong indicator
    of a mid-word chunk split followed by the real sentence.
    """
    m = _LEADING_FRAGMENT_RE.match(text)
    if m:
        return text[m.end():]
    return text


def merge_flagged_passages(
    agent_outputs: list[AgentOutput],
    max_passages: int = 50,
    min_text_length: int = 30,
    min_word_count: int = 3,
) -> list[FlaggedPassage]:
    """Collect and deduplicate flagged passages from all agents.

    Keeps up to ``max_passages`` entries.

    Internal-duplication passages (``internal_chunk_`` sources) are
    excluded because self-similarity within a document is not plagiarism.

    When the same text appears from multiple agents, the entry with the
    higher similarity score is kept.

    Filters out:
    - internal-duplication passages (``internal_chunk_`` sources)
    - fragments shorter than *min_text_length* / *min_word_count*
    - citation/bibliographic metadata (author blocks, emails, pub dates)
    - leading partial-word artefacts from chunk-boundary splits
    """
    best: dict[str, FlaggedPassage] = {}

    for output in agent_outputs:
        for fp in output.flagged_passages:
            # Skip internal-duplication passages (self-similarity)
            if fp.source and fp.source.startswith("internal_chunk_"):
                continue

            stripped = fp.text.strip()

            # Trim leading partial-word fragment (chunk boundary artefact)
            cleaned = _trim_leading_fragment(stripped)

            # Skip trivially short fragments (after trimming)
            if len(cleaned) < min_text_length or len(cleaned.split()) < min_word_count:
                continue

            # Skip citation / bibliographic metadata blocks
            if _is_citation_metadata(cleaned):
                continue

            # Skip reference lines (URLs, DOIs, journal headers)
            if _is_reference_line(cleaned):
                continue

            # Build a possibly-cleaned FlaggedPassage
            if cleaned != stripped:
                fp = FlaggedPassage(
                    text=cleaned,
                    similarity_score=fp.similarity_score,
                    source=fp.source,
                    reason=fp.reason,
                )

            key = fp.text[:100]  # deduplicate on first 100 chars

            existing = best.get(key)
            if existing is None or fp.similarity_score > existing.similarity_score:
                best[key] = fp

    all_passages = sorted(
        best.values(), key=lambda p: p.similarity_score, reverse=True
    )
    return list(all_passages[:max_passages])
