"""Allowlist gate tests (api.signup_common.is_email_allowlisted).

Pure-unit: no MongoDB. Builds a Settings with an explicit signup allowlist and
asserts case/space-insensitive membership and rejection.
"""

from __future__ import annotations

import pytest

from api.signup_common import is_email_allowlisted
from config import Settings

pytestmark = [pytest.mark.asyncio]


def _settings_with_allowlist(allowlist: list[str]) -> Settings:
    settings = Settings()
    settings.signup.allowlist = allowlist
    return settings


async def test_allowlisted_exact_match():
    settings = _settings_with_allowlist(["alice@example.com"])
    assert is_email_allowlisted("alice@example.com", settings) is True


async def test_allowlisted_case_and_space_insensitive():
    settings = _settings_with_allowlist(["Alice@Example.com"])
    assert is_email_allowlisted("  ALICE@example.COM ", settings) is True


async def test_not_allowlisted_email_not_listed():
    settings = _settings_with_allowlist(["alice@example.com"])
    assert is_email_allowlisted("bob@example.com", settings) is False


async def test_not_allowlisted_empty_allowlist():
    settings = _settings_with_allowlist([])
    assert is_email_allowlisted("alice@example.com", settings) is False
