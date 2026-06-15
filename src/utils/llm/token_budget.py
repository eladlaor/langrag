"""
Token-budget estimation and pre-flight guard for LLM prompts.

Used to fail fast *before* an over-large prompt is sent to a provider, rather
than letting it hit the model's context-length limit at call time and then burn
the entire retry budget on a request that can never succeed.

Estimation uses ``tiktoken`` when available (cl100k_base is a good cross-model
proxy) and falls back to a conservative chars/4 heuristic otherwise. The goal is
a safety ceiling, not exact accounting, so an approximate count is sufficient.
"""

import logging
from functools import lru_cache

from custom_types.exceptions import LLMContextLengthError

logger = logging.getLogger(__name__)

# Conservative fallback when tiktoken is unavailable: ~4 chars per token is the
# widely-used rule of thumb for English; non-English text trends to fewer chars
# per token, so this under-counts slightly (safe direction for a ceiling check
# would be over-counting, so we deliberately keep the divisor small).
_FALLBACK_CHARS_PER_TOKEN = 3.0


@lru_cache(maxsize=1)
def _get_encoder():
    """Return a cached tiktoken encoder, or None if tiktoken is unavailable."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # ImportError or any tiktoken init failure
        logger.warning(f"tiktoken unavailable ({e}); falling back to chars/{_FALLBACK_CHARS_PER_TOKEN} token estimate")
        return None


# Above this character length, skip the (relatively expensive) tiktoken encode
# and use the cheap chars-based estimate directly. The smallest real token is
# ~1 char, so chars/1 is a safe upper bound — any text this long is already far
# past any sane prompt budget, and the only consumer is a ceiling check.
_TIKTOKEN_SKIP_CHARS = 1_000_000


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in ``text``.

    For very large strings, skips tiktoken (which is O(n) but with meaningful
    constant overhead) and returns the cheap chars-based estimate — the only
    caller is a budget ceiling check, where an exact count of an already-oversized
    input adds no value and costs real time.

    Args:
        text: The string to measure.

    Returns:
        Estimated token count (>= 0).
    """
    if not text:
        return 0
    if len(text) >= _TIKTOKEN_SKIP_CHARS:
        return int(len(text) / _FALLBACK_CHARS_PER_TOKEN)
    encoder = _get_encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    return int(len(text) / _FALLBACK_CHARS_PER_TOKEN)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate the total input tokens for a list of chat messages.

    Sums the estimated tokens of every message ``content`` plus a small
    per-message overhead to approximate role/formatting tokens.

    Args:
        messages: OpenAI-style message dicts with a ``content`` field.

    Returns:
        Estimated total input token count.
    """
    # ~4 tokens of structural overhead per message (role markers, separators).
    per_message_overhead = 4
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content) + per_message_overhead
        else:
            # Non-string content (rare here) — stringify defensively.
            total += estimate_tokens(str(content)) + per_message_overhead
    return total


def enforce_prompt_token_budget(messages: list[dict], max_input_tokens: int, *, context: str = "prompt") -> int:
    """Fail fast if the assembled prompt is estimated to exceed the budget.

    Args:
        messages: OpenAI-style message dicts to be sent to the model.
        max_input_tokens: Ceiling on estimated input tokens.
        context: Short label for the error message (e.g. the format/operation).

    Returns:
        The estimated token count (when within budget).

    Raises:
        LLMContextLengthError: if the estimate exceeds ``max_input_tokens``.
    """
    estimated = estimate_messages_tokens(messages)
    if estimated > max_input_tokens:
        raise LLMContextLengthError(
            f"Estimated prompt size for '{context}' is ~{estimated} input tokens, "
            f"exceeding the configured ceiling of {max_input_tokens}. "
            f"Reduce the number/size of discussions (e.g. lower top_k) or raise "
            f"LLM_MAX_PROMPT_INPUT_TOKENS for a larger-context model."
        )
    return estimated
