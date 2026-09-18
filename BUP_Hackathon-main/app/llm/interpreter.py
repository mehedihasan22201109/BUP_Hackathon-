"""High-level orchestrator: LLM call -> parser -> deterministic validation.

This module never touches FastAPI directly; it is consumed by
``app.services.optimizer_service``. Keeping it free of HTTP concerns makes
it trivially testable.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..config import get_settings
from ..exceptions import LLMError
from .client import LLMClient, build_default_client
from .parser import parse_directive_array
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class NoteInterpreter:
    """Coordinates the LLM call and the deterministic post-validation.

    The validator import is deferred to avoid a circular dependency.
    """

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client or build_default_client()
        self._settings = get_settings()

    @property
    def client(self) -> LLMClient:
        return self._client

    def interpret(self, operator_notes: List[str]) -> List[Dict[str, Any]]:
        """Return a list of validated interpretation dicts, one per note.

        Raises ``LLMError`` on hard failure (no usable JSON at all). If
        validation fails for an entry, the deterministic validator downgrades
        it to a ``no_op`` entry rather than rejecting the whole request.
        """
        if not operator_notes:
            return []

        raw = self._client.complete(
            system=SYSTEM_PROMPT,
            user=build_user_prompt(operator_notes),
            temperature=self._settings.llm_temperature,
            timeout_seconds=self._settings.llm_timeout_seconds,
        )
        try:
            entries = parse_directive_array(raw)
        except LLMError:
            logger.exception("LLM output unparseable; falling back to no_op entries")
            entries = []

        # Local import to avoid circular dependency at module load time.
        from ..validation.directives import (
            normalize_entry,
            ALLOWED_DIRECTIVE_TYPES,
        )

        results: List[Dict[str, Any]] = []
        # First pass: normalize per note_index, downgrade invalid entries to no_op.
        for idx, note in enumerate(operator_notes):
            raw_entry = next((e for e in entries if int(e.get("note_index", -1)) == idx), None)
            normalized = normalize_entry(idx, raw_entry)
            results.append(normalized)
        return results


def build_default_interpreter() -> NoteInterpreter:
    return NoteInterpreter()
