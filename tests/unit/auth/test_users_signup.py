"""Self-signup repo tests (UsersRepository.create_self_signup_user et al.).

Validates the VIEWER-only invariant, the v3 schema fields, the google_sub
round-trip, the link flow, and that duplicate email / duplicate google_sub both
raise (exercising the sparse-unique index).
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from pymongo.errors import DuplicateKeyError

from constants import CURRENT_SCHEMA_VERSION_USER, SCHEMA_VERSION_FIELD
from custom_types.db_schemas import AuthProvider, UserRole
from custom_types.field_keys import UserKeys
from db.repositories.users import UsersRepository
from rag.auth.passwords import hash_password
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_self_signup_user_is_viewer_with_no_communities(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_self_signup_user(
        email=unique_email,
        auth_provider=AuthProvider.PASSWORD,
        password_hash=hash_password("pw"),
    )
    try:
        user = await repo.find_by_user_id(user_id)
        assert user[UserKeys.ROLE] == str(UserRole.VIEWER)
        assert user[UserKeys.COMMUNITIES] == []
        assert user[UserKeys.AUTH_PROVIDER] == str(AuthProvider.PASSWORD)
        assert user[SCHEMA_VERSION_FIELD] == CURRENT_SCHEMA_VERSION_USER
    finally:
        await repo.delete_user(user_id)


@pytest.mark.asyncio(loop_scope=None)
async def test_self_signup_cannot_mint_admin_no_role_param():
    """The signature must not expose a role/communities argument so the
    self-signup path is structurally incapable of minting an ADMIN."""
    params = inspect.signature(UsersRepository.create_self_signup_user).parameters
    assert "role" not in params
    assert "communities" not in params


async def test_find_by_google_sub_round_trip(db, unique_email):
    repo = UsersRepository(db)
    google_sub = f"sub-{uuid.uuid4().hex}"
    user_id = await repo.create_self_signup_user(
        email=unique_email,
        auth_provider=AuthProvider.GOOGLE,
        google_sub=google_sub,
    )
    try:
        found = await repo.find_by_google_sub(google_sub)
        assert found is not None
        assert found[UserKeys.USER_ID] == user_id
        assert found[UserKeys.AUTH_PROVIDER] == str(AuthProvider.GOOGLE)
    finally:
        await repo.delete_user(user_id)


async def test_link_google_identity_flips_provider(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_self_signup_user(
        email=unique_email,
        auth_provider=AuthProvider.PASSWORD,
        password_hash=hash_password("pw"),
    )
    try:
        google_sub = f"sub-{uuid.uuid4().hex}"
        await repo.link_google_identity(user_id, google_sub)
        user = await repo.find_by_user_id(user_id)
        assert user[UserKeys.GOOGLE_SUB] == google_sub
        assert user[UserKeys.AUTH_PROVIDER] == str(AuthProvider.PASSWORD_AND_GOOGLE)
    finally:
        await repo.delete_user(user_id)


async def test_duplicate_email_raises(db, unique_email):
    repo = UsersRepository(db)
    user_id = await repo.create_self_signup_user(email=unique_email, auth_provider=AuthProvider.PASSWORD, password_hash=hash_password("pw"))
    try:
        with pytest.raises(DuplicateKeyError):
            await repo.create_self_signup_user(email=unique_email, auth_provider=AuthProvider.PASSWORD, password_hash=hash_password("pw2"))
    finally:
        await repo.delete_user(user_id)


async def test_duplicate_google_sub_raises(db, unique_email):
    repo = UsersRepository(db)
    google_sub = f"sub-{uuid.uuid4().hex}"
    first = await repo.create_self_signup_user(email=unique_email, auth_provider=AuthProvider.GOOGLE, google_sub=google_sub)
    second_email = f"second-{uuid.uuid4().hex[:12]}@example.com"
    second = None
    try:
        with pytest.raises(DuplicateKeyError):
            second = await repo.create_self_signup_user(email=second_email, auth_provider=AuthProvider.GOOGLE, google_sub=google_sub)
    finally:
        await repo.delete_user(first)
        if second:
            await repo.delete_user(second)
