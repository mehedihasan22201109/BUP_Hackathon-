"""LLM client abstraction.

Two providers are supported:

* ``OpenAICompatibleClient`` -- calls any /v1/chat/completions endpoint
  (OpenAI, Azure OpenAI, Groq, OpenRouter, Ollama with the OpenAI shim, etc.).
* ``MockLLMClient`` -- deterministic in-process provider for tests and offline
  runs. It dispatches on the operator note text via simple keyword
  classification. It never accesses the network.

Selection is driven by ``Settings.llm_provider``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


class LLMMessage(Dict[str, str]):
    """Convenience dict subclass -- OpenAI SDK accepts plain dicts."""


class LLMClient(Protocol):
    """Minimal contract every provider must satisfy."""

    model_name: str

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        timeout_seconds: float = 30.0,
    ) -> str: ...


# --------------------------------------------------------------------------- #
# OpenAI-compatible client                                                    #
# --------------------------------------------------------------------------- #

class OpenAICompatibleClient:
    """Thin wrapper around the official ``openai`` SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        # Import lazily so unit tests can run without the SDK installed.
        from openai import OpenAI  # type: ignore

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        timeout_seconds: float = 30.0,
    ) -> str:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        logger.info("LLM call: model=%s temperature=%.2f", self.model_name, temperature)
        resp = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            timeout=timeout_seconds,
        )
        if not resp.choices:
            raise RuntimeError("LLM returned no choices")
        content = resp.choices[0].message.content
        if content is None:
            raise RuntimeError("LLM returned empty message content")
        return content


# --------------------------------------------------------------------------- #
# Mock client                                                                 #
# --------------------------------------------------------------------------- #

class MockLLMClient:
    """Deterministic mock used by tests and offline runs.

    The mock **classifies** operator notes using simple, transparent rules
    rather than hard-coding any specific public-case wording. The point is to
    exercise the full interpretation pipeline end-to-end without network
    calls; it must NOT be used as the production path.

    Classification priority:
        1. distractor (no grid/battery keywords at all) -> no_op
        2. solar reduction wording
        3. percentage / kWh reserve wording
        4. no-charge window wording
        5. no-discharge window wording
        6. max-grid / cap / feeder wording
        7. fallback -> no_op
    """

    def __init__(self, model_name: str = "mock-llm") -> None:
        self.model_name = model_name

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _grid_keywords(note_l: str) -> bool:
        keys = (
            "grid", "feeder", "transformer", "import", "cap", "limit",
            "shutdown", "outage", "island", "load shed",
        )
        return any(k in note_l for k in keys)

    @staticmethod
    def _battery_keywords(note_l: str) -> bool:
        keys = (
            "battery", "charge", "discharge", "reserve", "soc",
            "charger", "inverter", "storage",
        )
        return any(k in note_l for k in keys)

    @staticmethod
    def _solar_keywords(note_l: str) -> bool:
        return ("solar" in note_l) or ("panel" in note_l) or ("pv" in note_l)

    # --------------------------------------------------------------- classify
    def _classify(self, note: str) -> Dict[str, Any]:
        """Return a single interpretation entry dict."""
        note_l = note.lower()
        # Default distractor: note mentions no grid/battery/solar topics
        is_grid = self._grid_keywords(note_l)
        is_battery = self._battery_keywords(note_l)
        is_solar = self._solar_keywords(note_l)
        if not (is_grid or is_battery or is_solar):
            return {
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Note does not affect today's energy schedule.",
            }

        # Solar reduction
        if is_solar:
            return {
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {
                    "factor": 0.5,
                    "hours": [],
                },
                "explanation": "Usable solar is reduced during the stated window.",
            }

        # Reserve
        if "reserve" in note_l or "kept" in note_l or "available" in note_l or "soc" in note_l:
            return {
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {
                    "hours": [],
                    "minimum_energy_kwh": 0.0,
                },
                "explanation": "Battery must hold at least the stated reserve during the window.",
            }

        # No charge window
        if "no charge" in note_l or "cannot charge" in note_l or "won't charge" in note_l \
                or "isolated" in note_l or "charger" in note_l and "disconnect" in note_l:
            return {
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": []},
                "explanation": "Battery charging is unavailable during the stated window.",
            }

        # No discharge window
        if "no discharge" in note_l or "cannot discharge" in note_l or "won't discharge" in note_l \
                or "protect" in note_l or "inverter" in note_l and "off" in note_l:
            return {
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": []},
                "explanation": "Battery discharging is unavailable during the stated window.",
            }

        # Max grid
        if "cap" in note_l or "max grid" in note_l or "maximum grid" in note_l \
                or "feeder" in note_l or "transformer" in note_l or "limit" in note_l:
            return {
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": [], "max_grid_kwh": 0.0},
                "explanation": "Grid import is capped during the stated window.",
            }

        # Fallback distractor
        return {
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Note does not affect today's energy schedule.",
        }

    # ----------------------------------------------------------- LLMClient API
    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Return a JSON array of interpretations, one per note.

        The mock produces deliberately minimal structured_adjustment payloads
        (empty hours, zero numerics) because real numeric extraction is the
        responsibility of the deterministic validator downstream. This keeps
        the mock honest: it demonstrates the *shape* without fabricating any
        numbers that could leak into the solver.
        """
        import json
        notes = self._extract_notes(user)
        out = []
        for idx, note in enumerate(notes):
            entry = self._classify(note)
            entry = {"note_index": idx, **entry}
            out.append(entry)
        return json.dumps(out)

    @staticmethod
    def _extract_notes(user_prompt: str) -> List[str]:
        """Pull the operator-notes array out of the user prompt.

        The mock is intentionally simple: it splits the prompt on the sentinel
        line that the real prompt template emits just before the JSON list.
        This avoids depending on any specific phrasing the production prompt
        might use.
        """
        sentinel = "OPERATOR_NOTES_JSON:"
        if sentinel in user_prompt:
            tail = user_prompt.split(sentinel, 1)[1].strip()
            # Strip any closing markers
            for end in ("\n\n", "```", "<"):
                if end in tail:
                    tail = tail.split(end, 1)[0]
            import json
            try:
                data = json.loads(tail)
                if isinstance(data, list):
                    return [str(x) for x in data]
            except Exception:
                pass
        # Fallback: scan the prompt line-by-line for plausible notes
        notes = []
        for line in user_prompt.splitlines():
            s = line.strip().lstrip("-*").strip()
            if len(s) > 12 and any(c.isalpha() for c in s):
                notes.append(s)
        return notes


# --------------------------------------------------------------------------- #
# Factory                                                                     #
# --------------------------------------------------------------------------- #

def build_default_client() -> LLMClient:
    """Construct the configured client using environment variables."""
    from .. import config as _config

    settings = _config.get_settings()
    if settings.llm_provider == _config.LLMProvider.MOCK:
        logger.info("LLM provider: mock")
        return MockLLMClient(model_name=settings.llm_model)

    settings.require_llm_credentials()
    logger.info(
        "LLM provider: openai-compatible model=%s base=%s",
        settings.llm_model, settings.llm_base_url,
    )
    return OpenAICompatibleClient(
        api_key=settings.llm_api_key or "",
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
