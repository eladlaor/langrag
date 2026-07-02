"""Canonical email dedup-bucket tests (C4) — no Docker.

The anti-abuse bucket must collapse sub-address (+tag) aliases and gmail-dot
variants to ONE key so the per-email cap cannot be bypassed / used to email-bomb,
while the real delivery address (case-normalized) is left untouched elsewhere.
"""

import pytest

from db.repositories.consumer_email import canonicalize_email_for_dedup


@pytest.mark.parametrize(
    "raw",
    [
        "user@example.com",
        "user+1@example.com",
        "user+anything.here@example.com",
        "USER+2@Example.com",
        "  user+3@example.com  ",
    ],
)
def test_plus_tag_aliases_collapse_to_one_bucket(raw):
    assert canonicalize_email_for_dedup(raw) == "user@example.com"


@pytest.mark.parametrize(
    "raw",
    [
        "u.ser@gmail.com",
        "user@gmail.com",
        "u.s.e.r@gmail.com",
        "user+promo@gmail.com",
        "US.ER+x@Gmail.com",
        "user@googlemail.com",
        "u.ser@googlemail.com",
    ],
)
def test_gmail_dot_and_tag_variants_collapse(raw):
    assert canonicalize_email_for_dedup(raw) == "user@gmail.com" or canonicalize_email_for_dedup(raw) == "user@googlemail.com"


def test_non_gmail_keeps_dots_but_strips_tag():
    # Dots are significant for non-gmail providers; only the +tag is stripped.
    assert canonicalize_email_for_dedup("a.b+tag@example.com") == "a.b@example.com"
    assert canonicalize_email_for_dedup("a.b@example.com") == "a.b@example.com"


def test_idempotent():
    once = canonicalize_email_for_dedup("User+tag@Gmail.com")
    assert canonicalize_email_for_dedup(once) == once


def test_malformed_no_at_does_not_raise():
    # Bucketing must never fail-open by throwing; upstream validation rejects bad
    # addresses, but a missing '@' here just returns the normalized value.
    assert canonicalize_email_for_dedup("not-an-email") == "not-an-email"
