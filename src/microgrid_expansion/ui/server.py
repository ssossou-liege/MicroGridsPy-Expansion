"""The local server behind the interface.

Routes are deliberately thin: they translate between HTTP and the two engine calls, and hold
no modelling logic of their own. Nothing is exposed beyond the loopback address, and no state
outlives the process — the interface is a window onto the library, not a service.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine, projects, schema
from .jobs import JobRegistry

STATIC = Path(__file__).resolve().parent / "static"


class RunRequest(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


class SaveRequest(BaseModel):
    name: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    kind: str
    result: dict[str, Any] = Field(default_factory=dict)


class SiteRequest(BaseModel):
    name: str
    latitude: float | None = None
    longitude: float | None = None
    census: dict[str, int] = Field(default_factory=dict)
    productive_units: int | None = None
    utc_offset_hours: int = 1


class ArchetypeRequest(BaseModel):
    site: str
    archetypes: dict[str, dict[str, float]] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="MicroGrids — dimensionnement certifié", docs_url=None,
                  redoc_url=None)
    registry = JobRegistry()

    @app.get("/api/bootstrap")
    def bootstrap() -> dict:
        """Everything the page needs on first paint."""
        from ..sites import known_sites, to_record
        sites = []
        for site in known_sites().values():
            record = to_record(site)
            record["n_households"] = site.n_households
            record["has_resource"] = bool(site.irradiance_file)
            sites.append(record)
        return {"groups": schema.describe(), "jobs": registry.recent(),
                "projects": projects.listing(), "sites": sites}

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

    # --------------------------------------------------------------------- sites
    @app.get("/api/sites")
    def sites_list() -> list[dict]:
        from ..sites import known_sites, to_record
        out = []
        for site in known_sites().values():
            record = to_record(site)
            record["n_households"] = site.n_households
            record["has_resource"] = bool(site.irradiance_file)
            out.append(record)
        return out

    @app.post("/api/sites")
    def site_save(request: SiteRequest) -> dict:
        from ..sites import Site, save_site, to_record
        census = {k: int(v) for k, v in request.census.items() if int(v) >= 0}
        site = Site(name=request.name.strip(), census=census or {"HH1": 0},
                    latitude=request.latitude, longitude=request.longitude,
                    productive_units=request.productive_units,
                    utc_offset_hours=request.utc_offset_hours, origin="user")
        if not site.name:
            raise HTTPException(status_code=400, detail="le site doit porter un nom")
        save_site(site)
        return to_record(site)

    @app.delete("/api/sites/{name}")
    def site_delete(name: str) -> dict:
        from ..sites import TEMPLATES, delete_site
        if name in TEMPLATES:
            raise HTTPException(status_code=400,
                                detail="les sites d'exemple ne se suppriment pas")
        return {"deleted": delete_site(name)}

    @app.post("/api/sites/{name}/resource")
    def site_resource(name: str) -> dict:
        job = registry.start("resource", f"Série météorologique — {name}",
                             lambda j: engine.fetch_resource(j, name))
        return job.to_dict()

    # ---------------------------------------------------------------- archetypes
    @app.get("/api/archetypes/{site}")
    def archetypes_get(site: str) -> dict:
        return engine.describe_archetypes(site)

    @app.post("/api/archetypes")
    def archetypes_set(request: ArchetypeRequest) -> dict:
        from ..demand import archetypes as A
        A.adjust(request.site, request.archetypes)
        return engine.describe_archetypes(request.site)

    @app.delete("/api/archetypes/{site}")
    def archetypes_reset(site: str) -> dict:
        from ..demand import archetypes as A
        A.reset(site)
        return engine.describe_archetypes(site)

    # ------------------------------------------------------------------ projects
    @app.get("/api/projects")
    def project_list() -> list[dict]:
        return projects.listing()

    @app.post("/api/projects")
    def project_save(request: SaveRequest) -> dict:
        return projects.save(request.name, request.overrides, request.results).to_dict()

    @app.get("/api/projects/{slug}")
    def project_open(slug: str) -> dict:
        try:
            return projects.load(slug).to_dict()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/projects/{slug}")
    def project_delete(slug: str) -> dict:
        return {"deleted": projects.remove(slug)}

    # ------------------------------------------------------------------- export
    @app.post("/api/export.csv")
    def export_csv(request: ExportRequest) -> Response:
        body = projects.as_csv(request.result, request.kind)
        stem = "dimensionnement" if request.kind == "size" else "plan-extension"
        site = str(request.result.get("site", "")).lower() or "site"
        # A byte-order mark so a spreadsheet opens the accents right without being asked.
        return Response("\ufeff" + body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{stem}-{site}.csv"'})

    @app.post("/api/export.json")
    def export_json(request: ExportRequest) -> Response:
        import json as _json
        stem = "dimensionnement" if request.kind == "size" else "plan-extension"
        site = str(request.result.get("site", "")).lower() or "site"
        return Response(_json.dumps(request.result, indent=2, ensure_ascii=False,
                                    default=float),
                        media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{stem}-{site}.json"'})

    @app.exception_handler(Exception)
    def unhandled(_request, exc: Exception) -> JSONResponse:      # pragma: no cover
        return JSONResponse(status_code=500,
                            content={"detail": f"{type(exc).__name__}: {exc}"})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
