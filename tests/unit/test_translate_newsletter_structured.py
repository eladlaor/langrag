"""Foundation contract tests for the structured newsletter-translation operation.

Scope: prove the A1 structured-translate FOUNDATION (schema + operation + input
builder + generator method), NOT the graph/email/pipeline wiring (owned by other
phases). The LLM is stubbed; no network calls, no full pipeline.
"""

import json

import pytest

from constants import (
    ContentGenerationOperations,
    DataSources,
    LlmInputPurposes,
    SummaryFormats,
    OUTPUT_FILENAME_FINAL_NEWSLETTER_JSON,
    OUTPUT_FILENAME_FINAL_NEWSLETTER_MD,
    OUTPUT_FILENAME_FINAL_NEWSLETTER_HTML,
    DIR_NAME_FINAL_NEWSLETTER,
)
from custom_types.newsletter_formats import get_format
from custom_types.translated_newsletter_schemas import get_translated_newsletter_schema
from core.generation.generators.newsletter_generator import NewsletterContentGenerator


def _langtalks_enriched_dict() -> dict:
    """Minimal enriched-shape dict for the LangTalks format, with a URL to preserve."""
    return {
        "primary_discussion": {
            "title": "Agent frameworks compared",
            "bullet_points": [
                {"label": "Tooling", "content": "See https://example.com/agents for the benchmark."},
            ],
            "first_message_timestamp": 1000,
            "last_message_timestamp": 2000,
            "ranking_of_relevance_to_gen_ai_engineering": 9,
            "number_of_messages": 12,
            "number_of_unique_participants": 4,
            "chat_name": "LangTalks Community",
        },
        "secondary_discussions": [],
        "worth_mentioning": ["one", "two", "three"],
    }


def test_operation_and_purpose_enums_exist():
    assert ContentGenerationOperations.TRANSLATE_NEWSLETTER_STRUCTURED == "translate_newsletter_structured"
    assert LlmInputPurposes.TRANSLATE_NEWSLETTER_STRUCTURED == "translate_newsletter_structured"


def test_final_newsletter_constants_defined():
    assert DIR_NAME_FINAL_NEWSLETTER == "final_newsletter"
    assert OUTPUT_FILENAME_FINAL_NEWSLETTER_JSON == "final_newsletter.json"
    assert OUTPUT_FILENAME_FINAL_NEWSLETTER_MD == "final_newsletter.md"
    assert OUTPUT_FILENAME_FINAL_NEWSLETTER_HTML == "final_newsletter.html"


def test_translated_schema_resolves_to_format_generation_schema():
    for fmt in (SummaryFormats.LANGTALKS_FORMAT, SummaryFormats.MCP_ISRAEL_FORMAT):
        assert get_translated_newsletter_schema(fmt) is get_format(fmt).get_response_schema()


@pytest.mark.asyncio
async def test_structured_translate_returns_renderable_dict(monkeypatch):
    """The op returns a same-shaped dict that the format renders to md/html/json."""
    enriched = _langtalks_enriched_dict()

    class _StubCaller:
        async def call_with_structured_output(self, purpose, response_schema, **kwargs):
            assert purpose == LlmInputPurposes.TRANSLATE_NEWSLETTER_STRUCTURED
            # Simulate a translation: keys/URLs preserved, text values changed.
            translated = json.loads(json.dumps(kwargs["input_to_translate"]))
            translated["primary_discussion"]["title"] = "מסגרות סוכנים בהשוואה"
            return translated

    monkeypatch.setattr("core.generation.generators.newsletter_generator.get_llm_caller", lambda: _StubCaller())

    generator = NewsletterContentGenerator(format_name=SummaryFormats.LANGTALKS_FORMAT)
    translated = await generator.generate_content(
        operation=ContentGenerationOperations.TRANSLATE_NEWSLETTER_STRUCTURED,
        data_source_type=DataSources.WHATSAPP_GROUP_CHAT_MESSAGES,
        data_source_path="/unused/path.json",
        newsletter_dict=enriched,
        desired_language_for_summary="hebrew",
    )

    # Same shape, translated text, URL preserved verbatim.
    assert set(translated.keys()) == set(enriched.keys())
    assert translated["primary_discussion"]["title"] == "מסגרות סוכנים בהשוואה"
    assert "https://example.com/agents" in translated["primary_discussion"]["bullet_points"][0]["content"]

    # Renderable by the format plugin (md/html/json).
    fmt = get_format(SummaryFormats.LANGTALKS_FORMAT)
    md = fmt.render_markdown(translated, desired_language="hebrew")
    html = fmt.render_html(translated, desired_language="hebrew")
    rendered_json = json.dumps(translated, ensure_ascii=False)
    assert "https://example.com/agents" in md
    assert "https://example.com/agents" in html
    assert "https://example.com/agents" in rendered_json
