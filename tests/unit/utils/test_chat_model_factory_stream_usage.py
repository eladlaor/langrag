"""Unit tests: _create_openai_model defaults stream_usage=True (top-level kwarg)
so streamed responses carry token usage -> Langfuse cost. Anthropic is untouched."""

from unittest.mock import MagicMock, patch


class TestOpenAIStreamUsage:
    def test_openai_model_defaults_stream_usage_true(self):
        from utils.llm import chat_model_factory

        fake_ctor = MagicMock()
        with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=fake_ctor)}):
            chat_model_factory.create_chat_model(model="gpt-4.1", provider="openai")

        _, kwargs = fake_ctor.call_args
        assert kwargs.get("stream_usage") is True
        # It must be a top-level kwarg, NOT nested in model_kwargs.
        assert "stream_usage" not in kwargs.get("model_kwargs", {})

    def test_explicit_stream_usage_false_is_respected(self):
        from utils.llm import chat_model_factory

        fake_ctor = MagicMock()
        with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=fake_ctor)}):
            chat_model_factory.create_chat_model(model="gpt-4.1", provider="openai", stream_usage=False)

        _, kwargs = fake_ctor.call_args
        assert kwargs.get("stream_usage") is False

    def test_anthropic_model_gets_no_stream_usage(self):
        from utils.llm import chat_model_factory

        fake_ctor = MagicMock()
        with (
            patch.dict("sys.modules", {"langchain_anthropic": MagicMock(ChatAnthropic=fake_ctor)}),
            patch.object(chat_model_factory, "get_settings", return_value=MagicMock()),
        ):
            chat_model_factory.create_chat_model(model="claude-sonnet-4-20250514", provider="anthropic")

        _, kwargs = fake_ctor.call_args
        assert "stream_usage" not in kwargs
