"""Progress tracking for long-running scan operations.

Provides an in-memory event store keyed by document_id. The orchestrator
publishes progress events; the SSE endpoint streams them to the client.

Events are automatically cleaned up 5 minutes after completion.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProgressEvent:
    """A single progress update."""
    stage: str
    message: str
    percent: int  # 0-100
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class ScanProgress:
    """Progress tracker for a single scan operation."""

    def __init__(self, document_id: str):
        self.document_id = document_id
        self.events: list[ProgressEvent] = []
        self._listeners: list[asyncio.Queue[ProgressEvent | None]] = []
        self._completed = False
        self._created_at = time.time()

    def emit(self, stage: str, message: str, percent: int, **data: Any) -> None:
        """Publish a progress event to all listeners."""
        event = ProgressEvent(stage=stage, message=message, percent=percent, data=data)
        self.events.append(event)

        for q in self._listeners:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if consumer is too slow

        logger.debug(
            "progress_event",
            document_id=self.document_id,
            stage=stage,
            percent=percent,
        )

    def complete(self) -> None:
        """Signal that the scan is done."""
        self._completed = True
        for q in self._listeners:
            try:
                q.put_nowait(None)  # sentinel for "done"
            except asyncio.QueueFull:
                pass

    @property
    def is_completed(self) -> bool:
        return self._completed

    def subscribe(self) -> asyncio.Queue[ProgressEvent | None]:
        """Create a queue that receives progress events. None = done."""
        q: asyncio.Queue[ProgressEvent | None] = asyncio.Queue(maxsize=100)
        # Replay existing events first
        for e in self.events:
            try:
                q.put_nowait(e)
            except asyncio.QueueFull:
                break
        if self._completed:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a listener queue."""
        try:
            self._listeners.remove(q)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

_registry: dict[str, ScanProgress] = {}
_CLEANUP_AGE_S = 300  # 5 minutes


def get_or_create(document_id: str) -> ScanProgress:
    """Get existing or create new progress tracker for a document."""
    _cleanup_stale()
    if document_id not in _registry:
        _registry[document_id] = ScanProgress(document_id)
    return _registry[document_id]


def get(document_id: str) -> ScanProgress | None:
    """Get progress tracker if it exists."""
    return _registry.get(document_id)


def _cleanup_stale() -> None:
    """Remove completed trackers older than 5 minutes."""
    now = time.time()
    stale = [
        doc_id for doc_id, p in _registry.items()
        if p.is_completed and (now - p._created_at) > _CLEANUP_AGE_S
    ]
    for doc_id in stale:
        del _registry[doc_id]
