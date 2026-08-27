"""The local server behind the interface.

Routes are deliberately thin: they translate between HTTP and the two engine calls, and hold
no modelling logic of their own. Nothing is exposed beyond the loopback address, and no state
outlives the process — the interface is a window onto the library, not a service.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine, schema
from .jobs import JobRegistry

STATIC = Path(__file__).resolve().parent / "static"


class RunRequest(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="MicroGrids — dimensionnement certifié", docs_url=None,
                  redoc_url=None)
    registry = JobRegistry()

    @app.get("/api/bootstrap")
    def bootstrap() -> dict:
        """Everything the page needs on first paint."""
        return {"groups": schema.describe(), "jobs": registry.recent()}

    @app.post("/api/size")
    def size(request: RunRequest) -> dict:
        overrides = request.overrides
        site = overrides.get("site", "?")
        job = registry.start("size", f"Dimensionnement — {site}",
                             lambda j: engine.size_site(j, overrides))
        return job.to_dict()

    @app.post("/api/plan")
    def plan(request: RunRequest) -> dict:
        overrides = request.overrides
        site = overrides.get("site", "?")
        job = registry.start("plan", f"Plan d'extension — {site}",
                             lambda j: engine.plan_expansion(j, overrides))
        return job.to_dict()

    @app.get("/api/job/{job_id}")
    def job_state(job_id: str) -> dict:
        job = registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="tâche inconnue")
        return job.to_dict()

    @app.post("/api/job/{job_id}/cancel")
    def job_cancel(job_id: str) -> dict:
        return {"cancelled": registry.cancel(job_id)}

    @app.get("/api/jobs")
    def jobs() -> list[dict]:
        return registry.recent()

    @app.exception_handler(Exception)
    def unhandled(_request, exc: Exception) -> JSONResponse:      # pragma: no cover
        return JSONResponse(status_code=500,
                            content={"detail": f"{type(exc).__name__}: {exc}"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
