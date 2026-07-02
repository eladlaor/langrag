"""Verification-token helper tests (pure logic, no Docker).

Covers generation, hashing, and the constant-time match for the public
podcast-consumer key issuance flow.
"""

import os

os.environ.setdefault("RAG_API_KEY_PEPPER", "test-pepper-do-not-use-in-prod")

from rag.auth.consumer_tokens import (
    generate_verification_token,
    hash_verification_token,
    verify_token_matches,
)


def test_generated_tokens_are_unique_and_prefixed():
    a = generate_verification_token()
    b = generate_verification_token()
    assert a != b
    assert a.startswith("lrag_vt_")
    assert len(a) > 20


def test_hash_is_deterministic_and_not_plaintext():
    token = generate_verification_token()
    h1 = hash_verification_token(token)
    h2 = hash_verification_token(token)
    assert h1 == h2
    assert token not in h1
    assert len(h1) == 64  # sha256 hex digest


def test_verify_token_matches_true_for_correct_token():
    token = generate_verification_token()
    stored = hash_verification_token(token)
    assert verify_token_matches(token, stored) is True


def test_verify_token_matches_false_for_wrong_token():
    token = generate_verification_token()
    stored = hash_verification_token(token)
    assert verify_token_matches(generate_verification_token(), stored) is False


def test_verify_token_matches_false_for_empty_stored():
    assert verify_token_matches(generate_verification_token(), "") is False
