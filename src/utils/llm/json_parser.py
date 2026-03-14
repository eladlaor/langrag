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


def parse_json_response(text: str) -> Any:
    """
    Parse JSON from an LLM response, handling common wrapping patterns.

    Attempts parsing in order:
    1. Direct JSON parse (for clean responses from OpenAI JSON mode)
    2. Extract from markdown code fences (```json ... ``` or ``` ... ```)
    3. Find first { ... } or [ ... ] block in the text

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

    # 2. Extract from markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", stripped, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. Find first JSON object or array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = stripped.find(start_char)
        if start_idx == -1:
            continue
        end_idx = stripped.rfind(end_char)
        if end_idx > start_idx:
            try:
                return json.loads(stripped[start_idx : end_idx + 1])
            except json.JSONDecodeError:
                continue

    raise json.JSONDecodeError("No valid JSON found in LLM response", text, 0)
