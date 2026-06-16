"""Access-request endpoint tests: public POST (generic ack) + admin GET."""

from __future__ import annotations

import uuid

import pytest

from starlette.requests import Request

from custom_types.api_schemas import AccessRequestCreate
from custom_types.db_schemas import AccessRequestStatus
from custom_types.field_keys import AccessRequestKeys
from db.repositories.access_requests import AccessRequestsRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


def _Req() -> Request:
    """A minimal real Starlette Request.

    slowapi's @limiter.limit validates the request argument is a genuine
    starlette.requests.Request, so a duck-typed stand-in is not enough. The
    limiter is also disabled here (no app.state.limiter is wired in a direct
    function call), so the per-IP cap never trips across repeated calls.
    """
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/access-requests",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "query_string": b"",
    }
    return Request(scope)


async def _cleanup(db, email: str):
    repo = AccessRequestsRepository(db)
    docs = await repo.find_many({AccessRequestKeys.EMAIL: email.strip().lower()})
    for d in docs:
        await repo.delete_one({AccessRequestKeys.REQUEST_ID: d[AccessRequestKeys.REQUEST_ID]})


async def test_create_access_request_returns_generic_ack(db):
    from api.auth import create_access_request

    email = f"req-{uuid.uuid4().hex[:10]}@example.com"
    try:
        ack = await create_access_request(_Req(), AccessRequestCreate(email=email, name="X", message="hi"))
        assert ack.received is True
        repo = AccessRequestsRepository(db)
        docs = await repo.find_many({AccessRequestKeys.EMAIL: email})
        assert len(docs) == 1
    finally:
        await _cleanup(db, email)


async def test_create_access_request_duplicate_same_ack(db):
    from api.auth import create_access_request

    email = f"req-{uuid.uuid4().hex[:10]}@example.com"
    try:
        ack1 = await create_access_request(_Req(), AccessRequestCreate(email=email))
        ack2 = await create_access_request(_Req(), AccessRequestCreate(email=email))
        assert ack1.received is ack2.received is True
        assert ack1.message == ack2.message
    finally:
        await _cleanup(db, email)


async def test_admin_list_access_requests_returns_pending(db):
    from api.admin_users import list_access_requests

    repo = AccessRequestsRepository(db)
    email = f"req-{uuid.uuid4().hex[:10]}@example.com"
    request_id = await repo.create_request(email=email)
    try:
        views = await list_access_requests(status=str(AccessRequestStatus.PENDING), _=None)
        ids = [v.request_id for v in views]
        assert request_id in ids
    finally:
        await repo.delete_one({AccessRequestKeys.REQUEST_ID: request_id})
