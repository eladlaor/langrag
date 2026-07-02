"""
Email canonicalization for the podcast-consumer anti-abuse bucket.

`normalize_email` (in users.py) only lowercases + strips, which is the right
identity for STORAGE and DELIVERY. It is NOT enough for a rate-limit / dedup
bucket: `user+1@x.com`, `user+2@x.com`, and `u.ser@gmail.com` all deliver to the
same human but normalize to three distinct strings, so a naive per-email cap is
trivially bypassed (email-bombing a victim, or minting keys past the cap).

`canonicalize_email_for_dedup` collapses those aliases into a single bucket:
  - strip everything from the first `+` in the local part (sub-addressing), and
  - for gmail / googlemail, remove dots in the local part (Gmail ignores them).

This canonical form is used ONLY as the cap/dedup key. The real address the user
typed (normalized for case) is what we store and email — never the canonical
form.
"""

from constants import EMAIL_DOT_IGNORING_DOMAINS, EMAIL_PLUS_TAG_SEPARATOR
from db.repositories.users import normalize_email


def canonicalize_email_for_dedup(email: str) -> str:
    """Return the anti-abuse bucket key for an email (NOT the delivery address).

    Idempotent and case-insensitive (builds on normalize_email). A value with no
    local/domain split (no `@`) is returned normalized unchanged rather than
    raising: bucketing must never fail-open by throwing on malformed input that
    upstream validation already rejected.
    """
    normalized = normalize_email(email)
    local, sep, domain = normalized.partition("@")
    if not sep:
        return normalized

    # Sub-addressing: everything from the first '+' is a per-message tag.
    local = local.split(EMAIL_PLUS_TAG_SEPARATOR, 1)[0]

    # Gmail (and its googlemail alias) treat dots in the local part as absent.
    if domain in EMAIL_DOT_IGNORING_DOMAINS:
        local = local.replace(".", "")

    return f"{local}@{domain}"
