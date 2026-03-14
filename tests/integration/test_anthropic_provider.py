"""
Integration test for Anthropic LLM provider.

Verifies that the Anthropic API key from .env works and the provider
can make a real API call. This test uses real API credits.

Run:
    pytest tests/integration/test_anthropic_provider.py -v
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env before any src imports
load_dotenv(Path(__file__).parent.parent.parent / ".env")

# Ensure src is on path
src_path = Path(__file__).parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set in .env",
)


class TestAnthropicProviderSimpleCall:
    """Test that the Anthropic provider can make a real API call."""

    def test_call_simple_returns_text(self):
        """Make a minimal call_simple to verify API key and connectivity."""
        from utils.llm.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()
        result = provider.call_simple(
            purpose="integration_test",
            prompt="Reply with exactly: HELLO",
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
        )

        assert isinstance(result, str)
        assert len(result) > 0
        assert "HELLO" in result.upper()

    def test_call_with_structured_output_generic(self):
        """Make a structured output call to verify tool_use works."""
        from pydantic import BaseModel
        from utils.llm.anthropic_provider import AnthropicProvider

        class TestSchema(BaseModel):
            greeting: str
            number: int

        provider = AnthropicProvider()
        result = provider.call_with_structured_output_generic(
            messages=[
                {"role": "user", "content": "Return a greeting of 'hello' and the number 42."}
            ],
            response_schema=TestSchema,
            purpose="integration_test_structured",
            model="claude-haiku-4-5-20251001",
            temperature=0.0,
        )

        assert isinstance(result, dict)
        assert "greeting" in result
        assert "number" in result
        assert result["number"] == 42
