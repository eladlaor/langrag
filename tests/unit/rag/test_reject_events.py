"""Unit tests for reject observability (OBS-2).

Verifies a reject emits a per-key metric + Langfuse event, tags with key_id (never
the raw key), and degrades to a no-op when Langfuse is disabled.
"""

from unittest.mock import MagicMock, patch

from rag.observability import reject_events


class TestEmitReject:
    def test_records_metric_and_langfuse_event(self):
        with (
            patch.object(reject_events, "is_langfuse_enabled", return_value=True),
            patch.object(reject_events, "get_langfuse_client") as p_client,
            patch.object(reject_events, "record_reject") as p_metric,
        ):
            client = MagicMock()
            p_client.return_value = client
            reject_events.emit_reject(reason="daily_quota_exceeded", key_id="k-123", tool="search_podcasts")

        p_metric.assert_called_once_with("daily_quota_exceeded", "search_podcasts")
        client.event.assert_called_once()
        # key_id is tagged; the raw bearer must never be passed here.
        assert client.event.call_args.kwargs["metadata"]["key_id"] == "k-123"

    def test_noop_when_langfuse_disabled(self):
        with (
            patch.object(reject_events, "is_langfuse_enabled", return_value=False),
            patch.object(reject_events, "get_langfuse_client") as p_client,
            patch.object(reject_events, "record_reject") as p_metric,
        ):
            reject_events.emit_reject(reason="rate_limit_exceeded", key_id="k", tool="search_podcasts")

        # Metric still records; Langfuse client is never touched.
        p_metric.assert_called_once()
        p_client.assert_not_called()

    def test_swallows_langfuse_errors(self):
        with (
            patch.object(reject_events, "is_langfuse_enabled", return_value=True),
            patch.object(reject_events, "get_langfuse_client", side_effect=RuntimeError("boom")),
            patch.object(reject_events, "record_reject"),
        ):
            # Must not raise: reject observability is best-effort.
            reject_events.emit_reject(reason="scope_denied", key_id="k", tool="rag_query")
