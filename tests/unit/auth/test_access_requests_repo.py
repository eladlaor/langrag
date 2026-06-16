"""AccessRequestsRepository tests: normalized email + PENDING + newest-first."""

from __future__ import annotations

import uuid

import pytest

from custom_types.db_schemas import AccessRequestStatus
from custom_types.field_keys import AccessRequestKeys
from db.repositories.access_requests import AccessRequestsRepository
from tests._helpers.mongo import requires_mongodb

pytestmark = [requires_mongodb, pytest.mark.asyncio]


async def test_create_request_normalizes_and_defaults_pending(db):
    repo = AccessRequestsRepository(db)
    raw_email = f"  Req-{uuid.uuid4().hex[:10]}@Example.COM "
    request_id = await repo.create_request(email=raw_email, name="Req", message="please")
    try:
        doc = await repo.find_one({AccessRequestKeys.REQUEST_ID: request_id})
        assert doc is not None
        assert doc[AccessRequestKeys.EMAIL] == raw_email.strip().lower()
        assert doc[AccessRequestKeys.STATUS] == str(AccessRequestStatus.PENDING)
        assert doc[AccessRequestKeys.REQUEST_ID] == request_id
    finally:
        await repo.delete_one({AccessRequestKeys.REQUEST_ID: request_id})


async def test_list_requests_newest_first(db):
    repo = AccessRequestsRepository(db)
    e1 = f"a-{uuid.uuid4().hex[:10]}@example.com"
    e2 = f"b-{uuid.uuid4().hex[:10]}@example.com"
    id1 = await repo.create_request(email=e1)
    id2 = await repo.create_request(email=e2)
    try:
        requests = await repo.list_requests(status=AccessRequestStatus.PENDING)
        ids = [r[AccessRequestKeys.REQUEST_ID] for r in requests]
        # id2 created after id1, so it must appear earlier (newest-first).
        assert ids.index(id2) < ids.index(id1)
    finally:
        await repo.delete_one({AccessRequestKeys.REQUEST_ID: id1})
        await repo.delete_one({AccessRequestKeys.REQUEST_ID: id2})
