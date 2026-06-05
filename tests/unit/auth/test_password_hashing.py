"""Tests for argon2 password hashing helpers (rag.auth.passwords)."""

from __future__ import annotations

from rag.auth.passwords import hash_password, password_needs_rehash, verify_password


def test_hash_password_returns_phc_string():
    digest = hash_password("correct horse battery staple")
    assert digest.startswith("$argon2")
    assert digest != "correct horse battery staple"


def test_hash_password_is_salted_non_deterministic():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_verify_password_accepts_correct():
    digest = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", digest) is True


def test_verify_password_rejects_wrong():
    digest = hash_password("s3cret-pass")
    assert verify_password("wrong-pass", digest) is False


def test_verify_password_handles_garbage_hash_without_raising():
    assert verify_password("anything", "not-a-valid-argon2-hash") is False


def test_verify_password_handles_empty_hash():
    assert verify_password("anything", "") is False


def test_password_needs_rehash_false_for_fresh_hash():
    digest = hash_password("fresh")
    assert password_needs_rehash(digest) is False


def test_password_needs_rehash_true_for_invalid_hash():
    assert password_needs_rehash("garbage") is True
