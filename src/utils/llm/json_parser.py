"""
LLM JSON Response Parser

Extracts JSON from LLM responses that may contain markdown code fences,
preamble text, or other non-JSON wrapping. Works reliably across all
LLM providers (OpenAI, Anthropic, Gemini).

Usage:
    from utils.llm.json_parser import parse_json_response

    result = parse_json_response(response.content)
"""

import json
import re
from typing import Any


_DECODER = json.JSONDecoder()


def _decode_first_balanced_value(text: str) -> Any:
    """Decode the FIRST complete JSON object/array embedded in ``text``.

    Scans for each candidate opening bracket and uses ``raw_decode`` to parse a
    single, balanced JSON value starting there — ``raw_decode`` stops at the end
    of that value and ignores any trailing garbage, so a noisy response like
    ``{"a": 1} some trailing } text`` yields exactly ``{"a": 1}`` rather than a
    corrupted slice. Candidate positions are tried in left-to-right order so the
    first valid value wins.

    Raises:
        json.JSONDecodeError: if no balanced JSON value can be decoded.
    """
    candidates = sorted(idx for idx in (text.find("{"), text.find("[")) if idx != -1)
    for start_idx in candidates:
        try:
            value, _end = _DECODER.raw_decode(text, start_idx)
            return value
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("No valid JSON found in LLM response", text, 0)


def parse_json_response(text: str) -> Any:
    """
    Parse JSON from an LLM response, handling common wrapping patterns.

    Attempts parsing in order:
    1. Direct JSON parse (for clean responses from OpenAI JSON mode)
    2. Extract from markdown code fences (```json ... ``` or ``` ... ```)
    3. Decode the first balanced { ... } or [ ... ] value in the text

    Args:
        text: Raw LLM response text

    Returns:
        Parsed JSON object (dict or list)

    Raises:
        json.JSONDecodeError: If no valid JSON can be extracted
    """
    stripped = text.strip()

    # 1. Direct parse
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code fences (tolerate 3+ backticks on either side)
    fence_match = re.search(r"`{3,}(?:json)?\s*\n?(.*?)\n?\s*`{3,}", stripped, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            # Fence content may itself carry preamble/trailing noise — fall
            # through to balanced-value decoding on the fence body.
            try:
                return _decode_first_balanced_value(fence_match.group(1))
            except json.JSONDecodeError:
                pass

    # 3. Decode the first balanced JSON value embedded in the raw text.
    return _decode_first_balanced_value(stripped)
