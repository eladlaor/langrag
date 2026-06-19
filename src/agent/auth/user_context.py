"""The per-turn `UserContext` and the `ContextVar` that carries it.

Tools read the active context via `current_user_context()`. The route
handler sets it via `set_user_context()` at the start of each turn, and
clears it when the turn ends. Because `ContextVar` is async-task-local,
concurrent agent turns under the same FastAPI worker do NOT see each
other's context.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from collections.abc import Iterator


@dataclass(frozen=True)
class UserContext:
    """The authenticated principal for one agent turn.

    Frozen so a tool cannot mutate it; ACL checks are read-only.

    Attributes:
        user_id: Application-level user id (uuid4 string).
        email: User's email, for logging + ownership messaging.
        role: User role ("admin" today; future tiers add "viewer").
        communities: Communities this user is authorized to act on.
        quota_remaining: Pre-computed remaining quotas for this UTC day.
            Keys mirror the four `UserQuotas` fields.
    """

    user_id: str
    email: str
    role: str
    communities: tuple[str, ...]
    quota_remaining: dict[str, int] = field(default_factory=dict)

    def owns(self, community_key: str) -> bool:
        """True iff this user is authorized for `community_key`."""
        return community_key in self.communities


# Async-task-local context. `default=None` lets us distinguish "no context
# set" (raise) from "context explicitly cleared" (also raise).
_current: ContextVar[UserContext | None] = ContextVar("current_user_context", default=None)


class NoUserContextError(RuntimeError):
    """Raised when a tool tries to read the user context outside of a turn.

    A tool calling `current_user_context()` without a binding is almost
    certainly a bug: tests forgetting to set one, or a code path being
    reached outside an agent turn. Fail loud rather than fall back.
    """


def current_user_context() -> UserContext:
    """Return the active `UserContext` or raise if none is set."""
    ctx = _current.get()
    if ctx is None:
        raise NoUserContextError(
            "current_user_context() called outside an agent turn; set one "
            "via set_user_context(...) before invoking tools."
        )
    return ctx


def set_user_context(ctx: UserContext) -> Token[UserContext | None]:
    """Bind a `UserContext` for the current async task.

    Returns the `Token` so the caller can reset it later — typically via
    the `user_context(...)` context manager below.
    """
    return _current.set(ctx)


def reset_user_context(token: Token[UserContext | None]) -> None:
    """Restore the previous binding (or clear if there was none)."""
    _current.reset(token)


@contextmanager
def user_context(ctx: UserContext) -> Iterator[UserContext]:
    """Context manager that sets and then unsets the user context.

    Idiomatic usage in the route handler:

        with user_context(ctx):
            await graph.ainvoke(...)
    """
    token = set_user_context(ctx)
    try:
        yield ctx
    finally:
        reset_user_context(token)
