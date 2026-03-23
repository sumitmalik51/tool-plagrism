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


def _is_citation_metadata(text: str) -> bool:
    """Return True if text is primarily citation/bibliographic metadata."""
    return len(_CITATION_RE.findall(text)) >= 2


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

    Keeps up to ``max_passages`` entries, sorted by descending similarity.
    When the same text appears from multiple agents, external sources
    (http URLs) are preferred over internal ones (``internal_chunk_``).
    Filters out:
    - fragments shorter than *min_text_length* / *min_word_count*
    - citation/bibliographic metadata (author blocks, emails, pub dates)
    - leading partial-word artefacts from chunk-boundary splits
    """
    # key → (FlaggedPassage, priority)
    # Priority: 0 = internal_chunk_, 1 = ai_detection, 2 = http source
    best: dict[str, tuple[FlaggedPassage, int]] = {}

    for output in agent_outputs:
        for fp in output.flagged_passages:
            stripped = fp.text.strip()

            # Trim leading partial-word fragment (chunk boundary artefact)
            cleaned = _trim_leading_fragment(stripped)

            # Skip trivially short fragments (after trimming)
            if len(cleaned) < min_text_length or len(cleaned.split()) < min_word_count:
                continue

            # Skip citation / bibliographic metadata blocks
            if _is_citation_metadata(cleaned):
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

            # Determine source priority — prefer external over internal
            if fp.source and fp.source.startswith("http"):
                priority = 2
            elif fp.source == "ai_detection_heuristic":
                priority = 1
            else:
                priority = 0

            existing = best.get(key)
            if existing is None:
                best[key] = (fp, priority)
            else:
                _, existing_prio = existing
                # Replace if new passage has higher priority, or same
                # priority but higher similarity score
                if priority > existing_prio or (
                    priority == existing_prio
                    and fp.similarity_score > existing[0].similarity_score
                ):
                    best[key] = (fp, priority)

    all_passages = [fp for fp, _ in best.values()]
    all_passages.sort(key=lambda p: p.similarity_score, reverse=True)
    return all_passages[:max_passages]
