"""Unit tests for the shared empty-context refusal helper."""

from constants import RAG_REFUSAL_NO_CONTENT, RAG_REFUSAL_OUT_OF_RANGE
from rag.generation.rag_chain import refusal_for_empty_context


class TestRefusalForEmptyContext:
    def test_no_dates_returns_no_content_refusal(self):
        assert refusal_for_empty_context(None, None) == RAG_REFUSAL_NO_CONTENT

    def test_date_start_only_returns_out_of_range(self):
        assert refusal_for_empty_context("2030-01-01", None) == RAG_REFUSAL_OUT_OF_RANGE

    def test_date_end_only_returns_out_of_range(self):
        assert refusal_for_empty_context(None, "2030-12-31") == RAG_REFUSAL_OUT_OF_RANGE

    def test_both_dates_return_out_of_range(self):
        assert refusal_for_empty_context("2030-01-01", "2030-12-31") == RAG_REFUSAL_OUT_OF_RANGE
