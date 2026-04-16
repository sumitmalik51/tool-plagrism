"""Agent metrics & observability — tracks per-agent performance statistics.

Collects execution time, success/failure counts, and score distributions
for each detection agent. Provides a summary for admin dashboards and
operational monitoring.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _AgentStats:
    """Mutable stats bucket for one agent."""
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_s: float = 0.0
    min_duration_s: float = float("inf")
    max_duration_s: float = 0.0
    score_sum: float = 0.0
    score_count: int = 0
    last_run_at: float = 0.0  # epoch


class AgentMetrics:
    """Thread-safe singleton for tracking agent execution metrics.

    Usage::

        metrics = AgentMetrics.instance()
        metrics.record("academic_agent", duration_s=2.3, success=True, score=42.5)
        summary = metrics.summary()
    """

    _instance: "AgentMetrics | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._data: dict[str, _AgentStats] = defaultdict(_AgentStats)
        self._data_lock = threading.Lock()
        self._start_time = time.time()

    @classmethod
    def instance(cls) -> "AgentMetrics":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def record(
        self,
        agent_name: str,
        duration_s: float,
        success: bool,
        score: float | None = None,
    ) -> None:
        """Record a single agent execution."""
        with self._data_lock:
            stats = self._data[agent_name]
            stats.total_runs += 1
            if success:
                stats.successes += 1
            else:
                stats.failures += 1
            stats.total_duration_s += duration_s
            stats.min_duration_s = min(stats.min_duration_s, duration_s)
            stats.max_duration_s = max(stats.max_duration_s, duration_s)
            if score is not None:
                stats.score_sum += score
                stats.score_count += 1
            stats.last_run_at = time.time()

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of all agent metrics."""
        with self._data_lock:
            agents: dict[str, Any] = {}
            for name, stats in self._data.items():
                avg_duration = (
                    round(stats.total_duration_s / stats.total_runs, 3)
                    if stats.total_runs > 0
                    else 0.0
                )
                avg_score = (
                    round(stats.score_sum / stats.score_count, 1)
                    if stats.score_count > 0
                    else None
                )
                agents[name] = {
                    "total_runs": stats.total_runs,
                    "successes": stats.successes,
                    "failures": stats.failures,
                    "success_rate": round(stats.successes / stats.total_runs, 3) if stats.total_runs else 0,
                    "avg_duration_s": avg_duration,
                    "min_duration_s": round(stats.min_duration_s, 3) if stats.min_duration_s != float("inf") else 0,
                    "max_duration_s": round(stats.max_duration_s, 3),
                    "avg_score": avg_score,
                    "last_run_at": stats.last_run_at,
                }

            uptime_s = round(time.time() - self._start_time, 1)

            return {
                "uptime_s": uptime_s,
                "agents": agents,
                "total_runs": sum(s.total_runs for s in self._data.values()),
                "total_failures": sum(s.failures for s in self._data.values()),
            }

    def reset(self) -> None:
        """Reset all metrics (mainly for testing)."""
        with self._data_lock:
            self._data.clear()
            self._start_time = time.time()
