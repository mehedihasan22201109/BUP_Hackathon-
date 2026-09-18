"""Safe JSON extraction for LLM output.

LLMs occasionally wrap their JSON in markdown fences, add prose before or
after, or include trailing commas. This module strips noise and returns a
parsed Python object, raising ``LLMError`` if the result is unusable.
"""

from __future__ import annotations

import json
import re
from typing import Any, List

from ..exceptions import LLMError


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_ARRAY_RE = re.compile(r"\[\s*\{.*\}\s*\]", re.DOTALL)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_array(text: str) -> str:
    m = _ARRAY_RE.search(text)
    if not m:
        # Fall back: maybe the LLM wrapped each entry on its own line; try a
        # more permissive search for the outermost brackets.
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        raise LLMError("LLM output did not contain a JSON array")
    return m.group(0)


def parse_directive_array(raw: str) -> List[Any]:
    """Parse the LLM output into a list of raw interpretation dicts.

    Raises ``LLMError`` if extraction or JSON parsing fails. The caller is
    responsible for downstream schema validation.
    """
    if not raw or not raw.strip():
        raise LLMError("LLM returned empty content")

    cleaned = _strip_fences(raw)
    candidate = _extract_array(cleaned)

    # Try strict first, then a forgiving pass that strips trailing commas.
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        forgiving = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            data = json.loads(forgiving)
        except json.JSONDecodeError as exc:
            raise LLMError(
                f"LLM output is not valid JSON: {exc.msg} at column {exc.colno}"
            ) from exc

    if not isinstance(data, list):
        raise LLMError("LLM output JSON is not an array")
    return data
