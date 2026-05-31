"""The headline ACL safety invariant: NO tool exposes `user_context`.

`user_context` is the principal the tool ACLs against. If it appeared in
any tool's JSON schema, the LLM could fabricate a `user_context` argument
and the ACL check would run against the forged value. This test ensures
that the contextvar-based injection actually works — every tool's
visible-to-LLM args MUST exclude `user_context`.
"""

from __future__ import annotations

from agent.tools.registry import build_tools_for_session


class _StubStore:
    async def aput(self, *a, **kw): ...
    async def asearch(self, *a, **kw): return []
    async def adelete(self, *a, **kw): ...


async def _stub_kickoff(params, ctx):
    return "stub-run-id"


def _all_tools():
    return build_tools_for_session(_StubStore(), _stub_kickoff)


def test_no_tool_exposes_user_context():
    """The big one: no tool's JSON args may carry `user_context`."""
    for tool in _all_tools():
        schema = tool.args_schema.model_json_schema() if tool.args_schema else {}
        props = (schema.get("properties") or {}).keys()
        assert "user_context" not in props, (
            f"Tool {tool.name!r} exposes user_context in its JSON schema. "
            f"This would let the LLM forge the principal."
        )


def test_no_tool_exposes_user_id():
    """Same invariant for `user_id`: the LLM must NOT be able to spoof
    the principal under a different field name either."""
    for tool in _all_tools():
        schema = tool.args_schema.model_json_schema() if tool.args_schema else {}
        props = (schema.get("properties") or {}).keys()
        assert "user_id" not in props, (
            f"Tool {tool.name!r} exposes user_id in its JSON schema."
        )


def test_registry_has_expected_tools():
    """Tool surface is fixed at v1.13.0; an accidental drop should fail loudly."""
    names = sorted(t.name for t in _all_tools())
    expected = sorted(
        [
            "rag_query",
            "rag_search",
            "list_rag_sources",
            "list_my_communities",
            "describe_community",
            "remember",
            "forget",
            "list_memories",
            "generate_newsletter",
            "get_run_status",
            "list_recent_runs",
            "get_newsletter",
            "create_schedule",
            "list_schedules",
            "delete_schedule",
        ]
    )
    assert names == expected


def test_every_tool_has_a_docstring():
    """The LLM picks tools by their description — an empty docstring is
    a silent regression."""
    for tool in _all_tools():
        assert tool.description, f"Tool {tool.name!r} has no description"
