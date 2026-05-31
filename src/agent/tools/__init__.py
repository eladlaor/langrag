"""Agent tool registry.

Tools are constructed via factory closures so the `user_context` they
ACL-check against is bound at registry-build time (not exposed in the
LangChain tool schema, which the LLM sees). Each tool's first action is
an ACL assertion — `assert_user_owns_community` for community-scoped
tools, an `assert_admin`-style check for memory-management tools.
"""
