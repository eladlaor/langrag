"""Verification-email link builder tests (pure logic, no Docker, no send)."""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

from constants import PODCAST_CONSUMER_TOKEN_QUERY_PARAM
from core.delivery.podcast_consumer_email import build_verification_link


def test_link_appends_token_query_param():
    link = build_verification_link("https://langrag.ai/podcasts", "tok-123")
    assert link == f"https://langrag.ai/podcasts?{PODCAST_CONSUMER_TOKEN_QUERY_PARAM}=tok-123"


def test_link_uses_ampersand_when_base_already_has_query():
    link = build_verification_link("https://langrag.ai/podcasts?ref=email", "tok-123")
    assert link == f"https://langrag.ai/podcasts?ref=email&{PODCAST_CONSUMER_TOKEN_QUERY_PARAM}=tok-123"


def test_link_url_encodes_token():
    link = build_verification_link("https://langrag.ai/podcasts", "a b/c+d")
    # Space, slash, and plus are percent-encoded by urlencode.
    assert " " not in link
    assert f"{PODCAST_CONSUMER_TOKEN_QUERY_PARAM}=a+b%2Fc%2Bd" in link
