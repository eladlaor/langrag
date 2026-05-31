"""Tests for the agent-layer Prometheus counters.

We verify each counter has the expected label set and increments
under the recorder helpers. The metrics registry is reset between
tests so the second instantiation doesn't hit 'Duplicated timeseries'.
"""

from __future__ import annotations

import pytest

from observability.metrics import agent_metrics


@pytest.fixture(autouse=True)
def _reset_metrics():
    agent_metrics.reset_for_tests()
    yield
    agent_metrics.reset_for_tests()


def _sample_value(counter, **labels):
    """Helper: read the current value of a labelled counter."""
    return counter.labels(**labels)._value.get()


def test_record_tool_call_increments_counter():
    m = agent_metrics._get()
    agent_metrics.record_tool_call("list_my_communities", "success")
    agent_metrics.record_tool_call("list_my_communities", "success")
    agent_metrics.record_tool_call("delete_schedule", "error")
    assert (
        _sample_value(m.tool_calls_total, tool="list_my_communities", status="success")
        == 2
    )
    assert (
        _sample_value(m.tool_calls_total, tool="delete_schedule", status="error") == 1
    )


def test_record_memory_write_per_namespace():
    m = agent_metrics._get()
    agent_metrics.record_memory_write("semantic")
    agent_metrics.record_memory_write("semantic")
    agent_metrics.record_memory_write("episodic")
    assert _sample_value(m.memory_writes_total, namespace="semantic") == 2
    assert _sample_value(m.memory_writes_total, namespace="episodic") == 1


def test_record_budget_halt_records_reason():
    m = agent_metrics._get()
    agent_metrics.record_budget_halt("max_tool_calls_per_turn")
    assert (
        _sample_value(m.budget_halts_total, reason="max_tool_calls_per_turn") == 1
    )


def test_record_acl_denial_records_tool_and_community():
    m = agent_metrics._get()
    agent_metrics.record_acl_denial("describe_community", "langtalks")
    agent_metrics.record_acl_denial("describe_community", "langtalks")
    agent_metrics.record_acl_denial("generate_newsletter", "ail")
    assert (
        _sample_value(
            m.acl_denials_total, tool="describe_community", community="langtalks"
        )
        == 2
    )
    assert (
        _sample_value(
            m.acl_denials_total, tool="generate_newsletter", community="ail"
        )
        == 1
    )


def test_track_session_duration_observes_a_value():
    m = agent_metrics._get()
    before = m.session_duration_seconds._sum.get()
    with agent_metrics.track_session_duration():
        pass
    after = m.session_duration_seconds._sum.get()
    assert after >= before


def test_label_sets_match_plan_section_i():
    """Lock in the label vocabulary documented in §I of the plan so a
    rename here surfaces in CI."""
    m = agent_metrics._get()
    # Counters expose _labelnames for introspection.
    assert tuple(m.tool_calls_total._labelnames) == ("tool", "status")
    assert tuple(m.memory_writes_total._labelnames) == ("namespace",)
    assert tuple(m.budget_halts_total._labelnames) == ("reason",)
    assert tuple(m.acl_denials_total._labelnames) == ("tool", "community")
