"""
Unit tests for observability decorators.
"""

import pytest
from unittest.mock import MagicMock, patch

from observability.decorators import with_trace_span


class TestWithTraceSpan:
    """Tests for with_trace_span decorator."""

    @pytest.mark.asyncio
    async def test_async_function_decorated(self):
        """Async function can be decorated."""
        @with_trace_span()
        async def async_node(state, config=None, _span=None):
            return {"result": "async_success"}

        state = {"chat_name": "Test Chat"}

        with patch('observability.decorators.extract_trace_context') as mock_ctx:
            mock_ctx.return_value = MagicMock(trace_id="trace_123", parent_span_id=None)
            with patch('observability.decorators.langfuse_span') as mock_span:
                mock_span.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span.return_value.__exit__ = MagicMock(return_value=False)

                result = await async_node(state)

        assert result == {"result": "async_success"}

    def test_sync_function_decorated(self):
        """Sync function can be decorated."""
        @with_trace_span()
        def sync_node(state, config=None, _span=None):
            return {"result": "sync_success"}

        state = {"chat_name": "Test Chat"}

        with patch('observability.decorators.extract_trace_context') as mock_ctx:
            mock_ctx.return_value = MagicMock(trace_id="trace_456", parent_span_id=None)
            with patch('observability.decorators.langfuse_span') as mock_span:
                mock_span.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span.return_value.__exit__ = MagicMock(return_value=False)

                result = sync_node(state)

        assert result == {"result": "sync_success"}

    def test_custom_span_name(self):
        """Custom span name is used when provided."""
        @with_trace_span(span_name="custom_operation")
        def custom_node(state, config=None, _span=None):
            return {"done": True}

        state = {"chat_name": "Test"}

        with patch('observability.decorators.extract_trace_context') as mock_ctx:
            mock_ctx.return_value = MagicMock(trace_id="t1", parent_span_id=None)
            with patch('observability.decorators.langfuse_span') as mock_span:
                mock_span.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span.return_value.__exit__ = MagicMock(return_value=False)

                custom_node(state)

                # Verify span was called with custom name
                mock_span.assert_called_once()
                call_kwargs = mock_span.call_args[1]
                assert call_kwargs['name'] == 'custom_operation'

    def test_include_state_keys(self):
        """Specified state keys are included in span input."""
        @with_trace_span(include_state_keys=["chat_name", "start_date"])
        def node_with_keys(state, config=None, _span=None):
            return {}

        state = {
            "chat_name": "LangTalks",
            "start_date": "2025-01-01",
            "other_key": "ignored"
        }

        with patch('observability.decorators.extract_trace_context') as mock_ctx:
            mock_ctx.return_value = MagicMock(trace_id="t2", parent_span_id=None)
            with patch('observability.decorators.langfuse_span') as mock_span:
                mock_span.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span.return_value.__exit__ = MagicMock(return_value=False)

                node_with_keys(state)

                call_kwargs = mock_span.call_args[1]
                input_data = call_kwargs['input_data']

                assert "chat_name" in input_data
                assert "start_date" in input_data
                assert "other_key" not in input_data

    def test_default_include_keys(self):
        """Default includes only chat_name."""
        @with_trace_span()
        def default_node(state, config=None, _span=None):
            return {}

        state = {
            "chat_name": "Test",
            "extra": "not_included"
        }

        with patch('observability.decorators.extract_trace_context') as mock_ctx:
            mock_ctx.return_value = MagicMock(trace_id="t3", parent_span_id=None)
            with patch('observability.decorators.langfuse_span') as mock_span:
                mock_span.return_value.__enter__ = MagicMock(return_value=MagicMock())
                mock_span.return_value.__exit__ = MagicMock(return_value=False)

                default_node(state)

                call_kwargs = mock_span.call_args[1]
                input_data = call_kwargs['input_data']

                assert "chat_name" in input_data
                assert len(input_data) == 1
