"""Tests for the agent metrics & observability service."""

from __future__ import annotations

from app.services.agent_metrics import AgentMetrics


# ---------------------------------------------------------------------------
# AgentMetrics
# ---------------------------------------------------------------------------

def test_agent_metrics_singleton() -> None:
    m1 = AgentMetrics.instance()
    m2 = AgentMetrics.instance()
    assert m1 is m2


def test_agent_metrics_record_success() -> None:
    metrics = AgentMetrics()
    metrics.record("test_agent", duration_s=1.5, success=True, score=42.0)

    summary = metrics.summary()
    agent = summary["agents"]["test_agent"]
    assert agent["total_runs"] == 1
    assert agent["successes"] == 1
    assert agent["failures"] == 0
    assert agent["avg_duration_s"] == 1.5
    assert agent["avg_score"] == 42.0
    assert agent["success_rate"] == 1.0


def test_agent_metrics_record_failure() -> None:
    metrics = AgentMetrics()
    metrics.record("fail_agent", duration_s=0.5, success=False)

    summary = metrics.summary()
    agent = summary["agents"]["fail_agent"]
    assert agent["total_runs"] == 1
    assert agent["successes"] == 0
    assert agent["failures"] == 1
    assert agent["success_rate"] == 0.0
    assert agent["avg_score"] is None


def test_agent_metrics_multiple_runs() -> None:
    metrics = AgentMetrics()
    metrics.record("multi_agent", duration_s=1.0, success=True, score=30.0)
    metrics.record("multi_agent", duration_s=2.0, success=True, score=50.0)
    metrics.record("multi_agent", duration_s=3.0, success=False, score=None)

    summary = metrics.summary()
    agent = summary["agents"]["multi_agent"]
    assert agent["total_runs"] == 3
    assert agent["successes"] == 2
    assert agent["failures"] == 1
    assert agent["avg_duration_s"] == 2.0
    assert agent["min_duration_s"] == 1.0
    assert agent["max_duration_s"] == 3.0
    assert agent["avg_score"] == 40.0  # (30 + 50) / 2
    assert round(agent["success_rate"], 3) == 0.667


def test_agent_metrics_multiple_agents() -> None:
    metrics = AgentMetrics()
    metrics.record("agent_a", duration_s=1.0, success=True, score=10.0)
    metrics.record("agent_b", duration_s=2.0, success=True, score=20.0)

    summary = metrics.summary()
    assert "agent_a" in summary["agents"]
    assert "agent_b" in summary["agents"]
    assert summary["total_runs"] == 2
    assert summary["total_failures"] == 0


def test_agent_metrics_summary_uptime() -> None:
    metrics = AgentMetrics()
    summary = metrics.summary()
    assert "uptime_s" in summary
    assert summary["uptime_s"] >= 0


def test_agent_metrics_reset() -> None:
    metrics = AgentMetrics()
    metrics.record("reset_agent", duration_s=1.0, success=True)
    metrics.reset()

    summary = metrics.summary()
    assert summary["total_runs"] == 0
    assert len(summary["agents"]) == 0


def test_agent_metrics_empty_summary() -> None:
    metrics = AgentMetrics()
    summary = metrics.summary()
    assert summary["total_runs"] == 0
    assert summary["total_failures"] == 0
    assert summary["agents"] == {}


def test_agent_metrics_last_run_at() -> None:
    import time

    metrics = AgentMetrics()
    before = time.time()
    metrics.record("timed_agent", duration_s=0.1, success=True)

    summary = metrics.summary()
    last_run = summary["agents"]["timed_agent"]["last_run_at"]
    assert last_run >= before
    assert last_run <= time.time()
