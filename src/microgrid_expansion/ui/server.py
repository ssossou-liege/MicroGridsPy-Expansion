"""The local server behind the interface.

Routes are deliberately thin: they translate between HTTP and the engine calls, and hold no
modelling logic of their own. Nothing is exposed beyond the loopback address, and no state
outlives the process — the interface is a window onto the library, not a service.

One route does the work the tool exists for. ``/api/size`` answers what a community should
build this year; the rest describe a site, fetch its weather, list its archetypes, or carry a
study to and from disk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine, i18n, projects, schema
from .jobs import JobRegistry

STATIC = Path(__file__).resolve().parent / "static"


class RunRequest(BaseModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


class SaveRequest(BaseModel):
    name: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    #: There is one kind of result to export, so there is no kind to declare.
    result: dict[str, Any] = Field(default_factory=dict)
    lang: str = i18n.DEFAULT


class SiteRequest(BaseModel):
    name: str
    latitude: float | None = None
    longitude: float | None = None
    census: dict[str, int] = Field(default_factory=dict)
    productive_units: int | None = None
    productive_mix: dict[str, int] = Field(default_factory=dict)
    #: Omitted by the interface, which reads it off the longitude: an hour's displacement
    #: between sun and load is the error a storage sizing is most sensitive to, and asking
    #: a developer to state it invites exactly that error.
    utc_offset_hours: int | None = None


class ArchetypeRequest(BaseModel):
    site: str
    archetypes: dict[str, dict[str, float]] = Field(default_factory=dict)


def create_app() -> FastAPI:
    app = FastAPI(title="MicroGridsPy", docs_url=None,
                  redoc_url=None)
    registry = JobRegistry()

    @app.get("/api/bootstrap")
    def bootstrap(lang: str = i18n.DEFAULT) -> dict:
        """Everything the page needs on first paint, in the language it asked for."""
        lang = lang if lang in i18n.LANGUAGES else i18n.DEFAULT
        from ..sites import known_sites, to_record
        sites = []
        for site in known_sites().values():
            record = to_record(site)
            record["n_households"] = site.n_households
            record["has_resource"] = bool(site.irradiance_file)
            sites.append(record)
        return {"groups": schema.describe(lang=lang), "jobs": registry.recent(),
                "projects": projects.listing(), "sites": sites,
                "lang": lang, "languages": i18n.LANGUAGES,
                "strings": i18n.catalogue(lang)}

    @app.post("/api/size")
    def size(request: RunRequest) -> dict:
        """The one question the tool answers: what to build this year.

        Sizing a reference year and planning an expansion were two buttons, and the
        separation put a choice to the developer that is not theirs to make: a plant is
        built once, under an uncertain future, and the year-0 decision of the scenario
        tree *is* the sizing. The tree is therefore what runs, and the reference-year
        certificate is reported beside it as the corroboration it always was.
        """
        overrides = request.overrides
        site = overrides.get("site", "?")
        job = registry.start("size", "job.size",
                             lambda j: engine.size(j, overrides), site=site)
        return job.to_dict()

    @app.get("/api/productive-classes")
    def productive_classes(lang: str = i18n.DEFAULT) -> list[dict]:
        """The activity classes the demand model knows, named for a reader."""
        from ..demand.productive import CLASSES

        return [{"key": c, "label": i18n.t(f"pue.{c}", lang),
                 "hint": i18n.t(f"pue.{c}.hint", lang)} for c in CLASSES]

    @app.get("/api/job/{job_id}")
    def job_state(job_id: str) -> dict:
        job = registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
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
        from ..sites import Site, save_site, standard_offset, to_record
        census = {k: int(v) for k, v in request.census.items() if int(v) >= 0}
        roster = {k: int(v) for k, v in request.productive_mix.items() if int(v) > 0}
        offset = (request.utc_offset_hours if request.utc_offset_hours is not None
                  else standard_offset(request.longitude))
        site = Site(name=request.name.strip(), census=census or {"HH1": 0},
                    latitude=request.latitude, longitude=request.longitude,
                    productive_units=request.productive_units or (sum(roster.values()) or None),
                    productive_mix=roster or None,
                    utc_offset_hours=offset, origin="user")
        if not site.name:
            raise HTTPException(status_code=400, detail="the site needs a name")
        save_site(site)
        return to_record(site)

    @app.delete("/api/sites/{name}")
    def site_delete(name: str) -> dict:
        from ..sites import TEMPLATES, delete_site
        if name in TEMPLATES:
            raise HTTPException(status_code=400,
                                detail="the worked examples cannot be deleted")
        return {"deleted": delete_site(name)}

    @app.post("/api/sites/{name}/resource")
    def site_resource(name: str) -> dict:
        job = registry.start("resource", "job.resource",
                             lambda j: engine.fetch_resource(j, name), site=name)
        return job.to_dict()

    # ---------------------------------------------------------------- archetypes
    @app.get("/api/archetypes/{site}")
    def archetypes_get(site: str, lang: str = i18n.DEFAULT) -> dict:
        return engine.describe_archetypes(site, lang)

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
        body = projects.as_csv(request.result, request.lang)
        stem = "sizing"
        site = str(request.result.get("site", "")).lower() or "site"
        # A byte-order mark so a spreadsheet opens the accents right without being asked.
        return Response("\ufeff" + body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{stem}-{site}.csv"'})

    @app.post("/api/export.json")
    def export_json(request: ExportRequest) -> Response:
        import json as _json
        stem = "sizing"
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
