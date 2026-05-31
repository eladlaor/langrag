"""Auth + ACL + user-context propagation for the agentic chatbot layer.

The runtime invariant: every agent tool sees a `UserContext` injected by
the route handler via a `contextvars.ContextVar`. The LLM is NEVER given
access to this context — tool schemas exclude it — so a malicious or
hallucinating model cannot pretend to be a different user.
"""
