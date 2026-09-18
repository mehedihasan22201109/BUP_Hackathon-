"""HTTP routes.

The two endpoints are kept minimal: ``/health`` for liveness and
``/optimize-energy`` for the main work. All real logic lives in the
service layer.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from ..schemas import HealthResponse, OptimizeRequest, OptimizeResponse
from ..services.optimizer_service import OptimizerService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_optimizer_service(request: Request) -> OptimizerService:
    """Dependency-injected accessor for the singleton service."""
    svc = getattr(request.app.state, "optimizer_service", None)
    if svc is None:
        # Fallback for environments that wire the service elsewhere
        from ..services.optimizer_service import OptimizerService
        svc = OptimizerService()
    return svc


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    return HealthResponse()


@router.post(
    "/optimize-energy",
    response_model=OptimizeResponse,
    tags=["optimize"],
    responses={
        400: {"description": "Malformed request"},
        422: {"description": "Schema validation error"},
        500: {"description": "LLM, optimizer, or validation failure"},
    },
)
async def optimize_energy(
    payload: OptimizeRequest,
    service: OptimizerService = Depends(get_optimizer_service),
) -> OptimizeResponse:
    logger.info(
        "optimize-energy: scenario_id=%s notes=%d",
        payload.scenario_id,
        len(payload.operator_notes),
    )
    return service.optimize(payload)
