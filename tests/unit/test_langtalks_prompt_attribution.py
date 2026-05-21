"""
Regression tests for the LangTalks newsletter prompt's attribution rule.

The pipeline anonymizes WhatsApp senders to `user_<N>` identifiers and
hands those identifiers to the LLM as part of the discussion JSON. The
model is allowed (and expected) to *reason* with them, but it must
never quote them in the rendered newsletter.

These tests pin two invariants:
  1. The system prompt explicitly instructs the model not to surface
     `user_<number>` identifiers and tells it what neutral attribution
     phrases to use instead.
  2. The user message payload STILL contains the `sender_id` field —
     i.e., we did not "fix" the problem by hiding context from the
     model. That would degrade summary quality.
"""

import json
import re

from custom_types.newsletter_formats.langtalks.format import LangTalksFormat


_USER_ID_PATTERN = re.compile(r"user_\d+")


def _make_discussion(disc_id: str, sender_ids: list[str]) -> dict:
    """Build a minimal discussion dict that mirrors the real shape."""
    return {
        "discussion_id": disc_id,
        "discussion_title": "Some topic",
        "nutshell": "A short summary.",
        "first_message_timestamp": 1_700_000_000,
        "chat_name": "LangTalks Community",
        "num_unique_participants": len(set(sender_ids)),
        "messages": [
            {
                "timestamp": 1_700_000_000 + i,
                "sender_id": sender_ids[i],
                "text": f"message {i}",
            }
            for i in range(len(sender_ids))
        ],
    }


def _get_system_prompt(fmt: LangTalksFormat, desired_language: str = "hebrew") -> str:
    return fmt.get_system_prompt(
        brief_mention_items=None,
        non_featured_discussions=None,
        featured_discussions=[],
        desired_language=desired_language,
    )


def _get_user_message_content(fmt: LangTalksFormat, discussions: list[dict], desired_language: str = "hebrew") -> str:
    messages = fmt.build_messages(discussions=discussions, desired_language=desired_language)
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert user_msgs, "build_messages must produce at least one user message"
    return user_msgs[-1]["content"]


class TestAttributionRuleInSystemPrompt:
    def test_system_prompt_mentions_user_id_pattern(self):
        prompt = _get_system_prompt(LangTalksFormat())
        assert "user_<number>" in prompt or "user_" in prompt, "Prompt must explicitly call out the `user_<number>` pattern so the model knows what not to surface."

    def test_system_prompt_forbids_surfacing_ids(self):
        prompt = _get_system_prompt(LangTalksFormat()).upper()
        assert "NEVER" in prompt, "Prompt must use a strong directive (NEVER) about not surfacing IDs."

    def test_system_prompt_provides_hebrew_attribution_phrase(self):
        prompt = _get_system_prompt(LangTalksFormat(), desired_language="hebrew")
        assert "אחד החברים בקהילה" in prompt, "Prompt must give a concrete Hebrew attribution example."

    def test_system_prompt_provides_english_attribution_phrase(self):
        prompt = _get_system_prompt(LangTalksFormat(), desired_language="english")
        assert "community member" in prompt.lower(), "Prompt must give a concrete English attribution example."

    def test_attribution_rule_applies_across_languages(self):
        for lang in ("hebrew", "english", "spanish"):
            prompt = _get_system_prompt(LangTalksFormat(), desired_language=lang)
            assert "user_" in prompt, f"Attribution rule must be present regardless of desired_language={lang!r}"


class TestPayloadStillContainsSenderIds:
    """
    Lock in the design decision: we do NOT strip `sender_id` from the
    payload. The model needs it to distinguish a Q&A from a monologue.
    """

    def test_user_message_contains_sender_id_field(self):
        fmt = LangTalksFormat()
        discussions = [_make_discussion("d1", ["user_7", "user_12", "user_27"])]
        content = _get_user_message_content(fmt, discussions)
        assert '"sender_id"' in content, "sender_id MUST remain in the LLM payload — stripping it degrades reasoning quality."

    def test_user_message_contains_specific_user_ids(self):
        fmt = LangTalksFormat()
        discussions = [_make_discussion("d1", ["user_7", "user_12", "user_27"])]
        content = _get_user_message_content(fmt, discussions)
        found = set(_USER_ID_PATTERN.findall(content))
        assert {"user_7", "user_12", "user_27"} <= found, f"Expected all sender IDs to pass through to the LLM payload, found: {found}"

    def test_payload_is_valid_json_chunk(self):
        fmt = LangTalksFormat()
        discussions = [_make_discussion("d1", ["user_1", "user_2"])]
        content = _get_user_message_content(fmt, discussions)
        match = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
        assert match, "User message should contain a JSON-serialized discussions array"
        parsed = json.loads(match.group(0))
        assert parsed[0]["messages"][0]["sender_id"] == "user_1"
