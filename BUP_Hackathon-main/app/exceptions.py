"""Custom exception hierarchy.

Keeping every domain failure as a typed exception lets the FastAPI layer
translate them to precise HTTP status codes (400/422/500) without leaking
implementation details.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class GridWiseError(Exception):
    """Base class for all GridWise domain errors."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class SchemaError(GridWiseError):
    """The request did not match the expected JSON schema (HTTP 422)."""

    status_code = 422
    code = "schema_error"


class BadRequestError(GridWiseError):
    """The request was structurally valid but semantically rejected (HTTP 400)."""

    status_code = 400
    code = "bad_request"


class LLMError(GridWiseError):
    """The LLM provider failed or returned unusable output (HTTP 500)."""

    status_code = 500
    code = "llm_error"


class DirectiveValidationError(GridWiseError):
    """A directive produced by the LLM failed deterministic validation (HTTP 500)."""

    status_code = 500
    code = "directive_validation_error"


class OptimizerError(GridWiseError):
    """The LP solver failed, was infeasible, or timed out (HTTP 500)."""

    status_code = 500
    code = "optimizer_error"


class PostValidationError(GridWiseError):
    """The optimized schedule failed independent post-validation (HTTP 500).

    This should never happen for a correctly implemented solver; it is a
    defensive guard so the service never returns a self-inconsistent answer.
    """

    status_code = 500
    code = "post_validation_error"
