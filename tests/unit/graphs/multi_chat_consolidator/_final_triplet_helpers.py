"""
Shared fixtures/helpers for the final-newsletter-triplet TDD tests.

These encode the TARGET behavior from
knowledge/plans/NUMBERED_STAGE_DIRS_AND_FINAL_TRIPLET.md (Part A). They are
imported by the test modules that drive the consolidated translate node and
the email html-resolution helper. Nothing here should be treated as production
API; it only exists to build realistic on-disk fixtures.
"""

from __future__ import annotations

import json
import os
import re

from constants import SummaryFormats
from custom_types.field_keys import NewsletterStructureKeys as NSK
from custom_types.newsletter_formats import get_format

# Anchors that render_html injects unconditionally (footer CTAs). They are NOT
# content links, so link-count assertions must ignore them.
FOOTER_URLS = {
    "https://chat.whatsapp.com/ItqlTc288ulJSGKyWxrIck",
    "https://www.langtalks.ai/",
}

HREF_RE = re.compile(r'href="(https?://[^"]+)"')
MD_LINK_RE = re.compile(r"\]\((https?://[^)]+)\)")

# The enriched (post-link-enrichment) newsletter carries clickable anchors that
# the pre-enrichment generation draft lacks. Six content URLs, mirroring the
# 6-vs-2 defect observed on the live run.
ENRICHED_CONTENT_URLS = [
    "https://www.anthropic.com/news/claude",
    "https://langchain-ai.github.io/langgraph/",
    "https://modelcontextprotocol.io/introduction",
    "https://openai.com/research",
    "https://arxiv.org/abs/2312.11805",
    "https://github.com/langchain-ai/langgraph",
]

# The generation draft only had 2 bare (unclickable) URLs.
DRAFT_CONTENT_URLS = [
    "https://www.anthropic.com/news/claude",
    "https://langchain-ai.github.io/langgraph/",
]


def _bullet(label: str, content: str) -> dict:
    return {NSK.LABEL: label, NSK.CONTENT: content}


def make_enriched_newsletter_dict() -> dict:
    """A structured enriched newsletter dict with 6 clickable content links."""
    return {
        NSK.PRIMARY_DISCUSSION: {
            NSK.TITLE: "Agentic RAG in production",
            NSK.BULLET_POINTS: [
                _bullet("Model", f"Teams compared [Claude]({ENRICHED_CONTENT_URLS[0]}) tradeoffs."),
                _bullet("Framework", f"Most built on [LangGraph]({ENRICHED_CONTENT_URLS[1]})."),
                _bullet("Protocol", f"[MCP]({ENRICHED_CONTENT_URLS[2]}) came up repeatedly."),
            ],
        },
        NSK.SECONDARY_DISCUSSIONS: [
            {
                NSK.TITLE: "Evals",
                NSK.BULLET_POINTS: [
                    _bullet("Research", f"See [OpenAI research]({ENRICHED_CONTENT_URLS[3]})."),
                    _bullet("Paper", f"Referenced [an arXiv paper]({ENRICHED_CONTENT_URLS[4]})."),
                ],
            }
        ],
        NSK.WORTH_MENTIONING: [
            f"**Repo:** the [LangGraph source]({ENRICHED_CONTENT_URLS[5]}) was shared.",
        ],
    }


def make_draft_newsletter_dict() -> dict:
    """The pre-enrichment generation draft: fewer links, no enrichment bullets."""
    return {
        NSK.PRIMARY_DISCUSSION: {
            NSK.TITLE: "Agentic RAG in production",
            NSK.BULLET_POINTS: [
                _bullet("Model", f"Teams discussed {DRAFT_CONTENT_URLS[0]} tradeoffs."),
                _bullet("Framework", f"Most built on {DRAFT_CONTENT_URLS[1]}."),
            ],
        },
        NSK.SECONDARY_DISCUSSIONS: [],
        NSK.WORTH_MENTIONING: [],
    }


def content_hrefs(html: str) -> list[str]:
    """All content anchor URLs in the html, footer CTAs removed."""
    return [u for u in HREF_RE.findall(html) if u not in FOOTER_URLS]


def content_md_links(md: str) -> list[str]:
    return [u for u in MD_LINK_RE.findall(md) if u not in FOOTER_URLS]


def write_enriched_stage(enrichment_dir: str, newsletter_dict: dict) -> tuple[str, str]:
    """Write the enrichment-stage md+json a translate node would consume.

    Returns (enriched_json_path, enriched_md_path). Deliberately writes NO html
    at the enrichment stage (Design Decision: html is a final-stage-only
    concern).
    """
    from constants import (
        OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_JSON,
        OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_MD,
    )

    os.makedirs(enrichment_dir, exist_ok=True)
    fmt = get_format(str(SummaryFormats.LANGTALKS_FORMAT))

    json_path = os.path.join(enrichment_dir, OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_JSON)
    md_path = os.path.join(enrichment_dir, OUTPUT_FILENAME_ENRICHED_CONSOLIDATED_MD)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(newsletter_dict, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(fmt.render_markdown(newsletter_dict, "english"))

    return json_path, md_path
