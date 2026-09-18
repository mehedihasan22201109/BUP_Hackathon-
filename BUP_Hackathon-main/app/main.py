"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router as api_router
from .config import get_settings
from .exceptions import GridWiseError
from .llm.interpreter import build_default_interpreter
from .services.optimizer_service import OptimizerService


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)
    logging.getLogger(__name__).info(
        "Starting GridWise API (provider=%s model=%s)",
        settings.llm_provider.value,
        settings.llm_model,
    )
    app.state.optimizer_service = OptimizerService(
        interpreter=build_default_interpreter()
    )
    try:
        yield
    finally:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title="GridWise -- LLM-Assisted Energy Optimizer",
        version="1.0.0",
        description=(
            "GridWise interprets natural-language operator notes, validates "
            "them deterministically, and produces a 24-hour cost-minimizing "
            "battery+grid schedule."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5500",
            "http://localhost:5500",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        max_age=600,
    )
    @app.exception_handler(GridWiseError)
    async def _gridwise_error_handler(request: Request, exc: GridWiseError):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    app.include_router(api_router)
    return app


app = create_app()



