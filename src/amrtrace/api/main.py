"""FastAPI application for AMRTrace Studio."""

from __future__ import annotations

from fastapi import FastAPI

from .cases import router as cases_router
from .changes import router as changes_router
from .dossier import router as dossier_router
from .runs import router as runs_router
from .errors import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="AMRTrace Studio API",
        version="0.1.0",
    )

    register_error_handlers(app)
    app.include_router(cases_router)
    app.include_router(changes_router)
    app.include_router(dossier_router)
    app.include_router(runs_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        # PROJECT_PLAN.md defines this endpoint as liveness, not DB readiness.
        return {"service": "api", "status": "ok"}

    return app


app = create_app()
