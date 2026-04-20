"""Backend mirror of the frontend's stable passage hash.

Mirrors ``passageKey`` in ``frontend/src/lib/stores/dismissals-store.ts``
so dismissals stored from the browser line up with passages re-derived on
the server (used by the PDF export and the dismissals API).

Contract (must match the JS exactly):

    input    = f"{text}\\u0001{source}"
    h        = 5381  (int32, wraps with each step)
    for ch in input:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF   # JS ``| 0`` truncation
    excerpt  = re.sub(r"\\s+", "_", text[:16])
    key      = f"{h:in_base36}_{excerpt}"           # h is unsigned 32-bit
"""

from __future__ import annotations

import re
from typing import Any


_INT32_MASK = 0xFFFFFFFF
_WS = re.compile(r"\s+")


def _to_int32(n: int) -> int:
    """Mirror JS ``x | 0`` — truncate to signed 32-bit."""
    n &= _INT32_MASK
    return n - 0x100000000 if n & 0x80000000 else n


def _base36(n: int) -> str:
    """Match JS ``(n).toString(36)`` for non-negative integers."""
    if n == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = []
    while n > 0:
        n, r = divmod(n, 36)
        out.append(digits[r])
    return "".join(reversed(out))


def passage_key(text: str, source: str | None = None) -> str:
    """Compute the stable hash key for a flagged passage.

    Must produce the *exact* same string as the JS ``passageKey({text, source})``.
    """
    text = text or ""
    source = source or ""
    payload = f"{text}\u0001{source}"
    h = 5381
    for ch in payload:
        h = _to_int32((h << 5) + h + ord(ch))
    unsigned = h & _INT32_MASK  # JS ``h >>> 0``
    excerpt = _WS.sub("_", text[:16])
    return f"{_base36(unsigned)}_{excerpt}"


def passage_key_for(passage: dict[str, Any]) -> str:
    """Convenience wrapper for the typical dict shape used by the report."""
    return passage_key(passage.get("text") or "", passage.get("source"))


def adjusted_score(
    original_score: float,
    passages: list[dict[str, Any]],
    dismissals: dict[str, Any] | None,
) -> float:
    """Mirror of ``adjustedScore`` in the dismissals store.

    Scales ``original_score`` by ``1 - dismissed_weight / total_weight`` using
    each passage's ``similarity_score`` as its weight.
    """
    if not dismissals:
        return original_score
    if not passages:
        return original_score
    total = 0.0
    dismissed = 0.0
    for p in passages:
        try:
            w = float(p.get("similarity_score") or 0)
        except (TypeError, ValueError):
            w = 0.0
        total += w
        if passage_key_for(p) in dismissals:
            dismissed += w
    if total <= 0:
        return original_score
    remaining = max(0.0, 1.0 - dismissed / total)
    return round(original_score * remaining * 10) / 10
