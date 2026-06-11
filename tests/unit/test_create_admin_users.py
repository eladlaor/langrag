"""Unit tests for the admin-provisioning CLI (scripts/create_admin_users.py).

These tests mock the UsersRepository entirely; no live MongoDB is required.
They prove the three contractual behaviours of provision_admins:

  (a) a brand-new email creates a user document with role=admin and a stored
      password_hash that is NOT plaintext and that verify_password accepts;
  (b) re-running against an already-existing email is a no-op (skip), not a
      crash, and never calls create_user;
  (c) dry-run writes nothing (create_user is never invoked).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from custom_types.db_schemas import UserRole
from rag.auth.passwords import verify_password
from scripts.create_admin_users import AdminSpec, load_admin_specs, provision_admins


def _make_repo(existing_emails: set[str] | None = None) -> AsyncMock:
    """Build a mock UsersRepository.

    find_by_email returns a sentinel doc for any email in existing_emails, else
    None. create_user returns a fake user_id and records its call args.
    """
    existing = {e.lower() for e in (existing_emails or set())}
    repo = AsyncMock()

    async def _find_by_email(email: str):
        return {"user_id": "existing-id"} if email.strip().lower() in existing else None

    repo.find_by_email.side_effect = _find_by_email
    repo.create_user.return_value = "new-user-id"
    return repo


async def test_new_admin_is_created_with_admin_role_and_hashed_password():
    repo = _make_repo()
    plaintext = "S3cure-Initial-Pass!"
    specs = [AdminSpec(email="alice@example.com", password=plaintext)]

    summary = await provision_admins(repo, specs, dry_run=False)

    assert summary.created == 1
    assert summary.skipped == 0
    repo.create_user.assert_awaited_once()
    _, kwargs = repo.create_user.call_args
    assert kwargs["role"] is UserRole.ADMIN
    stored_hash = kwargs["password_hash"]
    # The stored value must not be the plaintext, and must verify against it.
    assert stored_hash != plaintext
    assert verify_password(plaintext, stored_hash) is True


async def test_existing_admin_is_skipped_no_create():
    repo = _make_repo(existing_emails={"bob@example.com"})
    specs = [AdminSpec(email="Bob@Example.com", password="whatever-pass")]

    summary = await provision_admins(repo, specs, dry_run=False)

    assert summary.created == 0
    assert summary.skipped == 1
    repo.create_user.assert_not_awaited()


async def test_dry_run_writes_nothing():
    repo = _make_repo()
    specs = [
        AdminSpec(email="carol@example.com", password="pass-a"),
        AdminSpec(email="dave@example.com", password="pass-b"),
    ]

    summary = await provision_admins(repo, specs, dry_run=True)

    assert summary.would_create == 2
    assert summary.created == 0
    repo.create_user.assert_not_awaited()


# ---- Email-format validation (same standard as the EmailStr login path) ----


def _write_json_seed(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    seed = tmp_path / "admins.json"
    seed.write_text(json.dumps(rows), encoding="utf-8")
    return seed


def test_bare_username_email_is_rejected_before_any_db_write(tmp_path: Path):
    """A bare username ('alice') is not a valid login identifier and must abort
    the whole run at load time, before any spec is produced or any DB call.
    """
    seed = _write_json_seed(tmp_path, [{"email": "alice", "password": "pw"}])

    with pytest.raises(ValueError) as exc:
        load_admin_specs(seed)

    # Error must name the offending email and its record position.
    assert "alice" in str(exc.value)
    assert "0" in str(exc.value)


def test_non_public_tld_email_is_rejected(tmp_path: Path):
    """A syntactically address-shaped value with a non-public TLD ('x@y.local')
    is what EmailStr (and therefore the login path) rejects; the loader must too.
    """
    seed = _write_json_seed(
        tmp_path,
        [
            {"email": "ok@langrag.ai", "password": "pw"},
            {"email": "x@y.local", "password": "pw"},
        ],
    )

    with pytest.raises(ValueError) as exc:
        load_admin_specs(seed)

    assert "x@y.local" in str(exc.value)
    assert "1" in str(exc.value)


def test_valid_public_tld_email_passes_through_to_create(tmp_path: Path):
    """A valid public-TLD email loads cleanly and reaches create_user."""
    seed = _write_json_seed(tmp_path, [{"email": "admin@langrag.ai", "password": "pw"}])

    specs = load_admin_specs(seed)

    assert len(specs) == 1
    assert specs[0].email == "admin@langrag.ai"


async def test_valid_email_reaches_create_user(tmp_path: Path):
    """End-to-end at the spec level: a valid loaded spec is created."""
    seed = _write_json_seed(tmp_path, [{"email": "admin@langrag.ai", "password": "pw"}])
    specs = load_admin_specs(seed)
    repo = _make_repo()

    summary = await provision_admins(repo, specs, dry_run=False)

    assert summary.created == 1
    repo.create_user.assert_awaited_once()
    _, kwargs = repo.create_user.call_args
    assert kwargs["email"] == "admin@langrag.ai"
