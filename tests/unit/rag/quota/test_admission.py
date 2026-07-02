"""Unit tests for search-path admission (COST-1 + COST-2 orchestration).

No Docker: the quota repo is a mock; settings are patched. Verifies rate limit
runs first, quota second, and that either rejection raises QueryAdmissionError
with the right reason.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from rag.quota import admission


def _patch_settings(monkeypatch, *, rate=60, quota=500):
    rag = SimpleNamespace(mcp_query_rate_per_min=rate, mcp_max_queries_per_key_per_day=quota)
    monkeypatch.setattr(admission, "get_settings", lambda: SimpleNamespace(rag=rag))


@pytest.fixture(autouse=True)
def _reset():
    admission._reset_for_tests()
    yield
    admission._reset_for_tests()


class TestEnforceQueryAdmission:
    async def test_admits_within_limits(self, monkeypatch):
        _patch_settings(monkeypatch)
        repo = SimpleNamespace(check_and_increment_key=AsyncMock(return_value=True))
        await admission.enforce_query_admission("k", quota_repo=repo)
        repo.check_and_increment_key.assert_awaited_once()

    async def test_rate_limit_rejects_before_quota(self, monkeypatch):
        _patch_settings(monkeypatch, rate=1)
        repo = SimpleNamespace(check_and_increment_key=AsyncMock(return_value=True))
        await admission.enforce_query_admission("k", quota_repo=repo)  # first ok
        with pytest.raises(admission.QueryAdmissionError) as exc:
            await admission.enforce_query_admission("k", quota_repo=repo)  # second shed by rate
        assert exc.value.reason == admission.ADMISSION_REASON_RATE_LIMIT
        # Quota repo touched only for the admitted first call, never the shed one.
        assert repo.check_and_increment_key.await_count == 1

    async def test_over_quota_rejects(self, monkeypatch):
        _patch_settings(monkeypatch)
        repo = SimpleNamespace(check_and_increment_key=AsyncMock(return_value=False))
        with pytest.raises(admission.QueryAdmissionError) as exc:
            await admission.enforce_query_admission("k", quota_repo=repo)
        assert exc.value.reason == admission.ADMISSION_REASON_DAILY_QUOTA
