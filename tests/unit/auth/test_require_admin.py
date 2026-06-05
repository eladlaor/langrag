"""Tests for the require_admin dependency (api.auth.require_admin)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from constants import HTTP_STATUS_FORBIDDEN
from custom_types.api_schemas import CurrentUser
from custom_types.db_schemas import UserRole

pytestmark = pytest.mark.asyncio


async def test_admin_passes():
    from api.auth import require_admin

    admin = CurrentUser(user_id="u-1", email="a@x.test", role=UserRole.ADMIN, communities=[])
    result = await require_admin(current=admin)
    assert result is admin


async def test_viewer_forbidden():
    from api.auth import require_admin

    viewer = CurrentUser(user_id="u-2", email="v@x.test", role=UserRole.VIEWER, communities=[])
    with pytest.raises(HTTPException) as exc:
        await require_admin(current=viewer)
    assert exc.value.status_code == HTTP_STATUS_FORBIDDEN
