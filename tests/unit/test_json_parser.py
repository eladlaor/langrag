"""
Unit tests for the LLM JSON response parser (utils/llm/json_parser.py).

These tests intentionally load the module by file path rather than via the
``utils.llm`` package, because that package eagerly imports provider modules
(openai, anthropic, ...) that may be absent outside the Docker image. The parser
itself has no third-party dependencies, so isolating it keeps the test fast and
runnable anywhere.

Regression focus: a previous implementation used ``str.find`` + ``str.rfind``
to slice from the first opening bracket to the LAST closing bracket. That
silently corrupted responses with trailing text or braces inside strings. The
current implementation decodes the first *balanced* JSON value via
``json.JSONDecoder.raw_decode``.
"""

import importlib.util
import json
import os

import pytest

_PARSER_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "src", "utils", "llm", "json_parser.py")


def _load_parser():
    spec = importlib.util.spec_from_file_location("json_parser_under_test", _PARSER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_json_response


parse_json_response = _load_parser()


class TestParseJsonResponseHappyPath:
    def test_clean_object(self):
        assert parse_json_response('{"a": 1}') == {"a": 1}

    def test_clean_array(self):
        assert parse_json_response("[1, 2, 3]") == [1, 2, 3]

    def test_nested_object(self):
        assert parse_json_response('{"a": {"b": [1, 2]}}') == {"a": {"b": [1, 2]}}

    def test_markdown_json_fence(self):
        assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}

    def test_markdown_bare_fence(self):
        assert parse_json_response('```\n{"a": 1}\n```') == {"a": 1}

    def test_four_backtick_fence(self):
        assert parse_json_response('````json\n{"a": 1}\n````') == {"a": 1}

    def test_preamble_then_object(self):
        assert parse_json_response('Here is the JSON:\n{"a": {"b": 2}}') == {"a": {"b": 2}}


class TestParseJsonResponseCorruptionRegressions:
    """Cases the old find/rfind slicing silently corrupted."""

    def test_trailing_text_with_brace_after_object(self):
        assert parse_json_response('{"a": 1} some trailing } text') == {"a": 1}

    def test_trailing_text_with_bracket_after_array(self):
        assert parse_json_response("[1, 2, 3] trailing ]") == [1, 2, 3]

    def test_brace_inside_string_value(self):
        assert parse_json_response('{"code": "use {x} here"}') == {"code": "use {x} here"}

    def test_close_brace_inside_string_value(self):
        assert parse_json_response('{"s": "a } b", "n": 2}') == {"s": "a } b", "n": 2}

    def test_leftmost_balanced_value_wins(self):
        assert parse_json_response('text {"a":1} then [9]') == {"a": 1}

    def test_nested_object_with_garbage_braces_after(self):
        assert parse_json_response('{"x": {"y": [1,2]}} garbage {nope}') == {"x": {"y": [1, 2]}}

    def test_fence_body_with_preamble(self):
        # Fence wraps a body that itself has preamble before the object.
        assert parse_json_response('```json\nNote:\n{"a": 1}\n```') == {"a": 1}


class TestParseJsonResponseFailures:
    def test_no_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_json_response("no json here at all")

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_json_response("")
