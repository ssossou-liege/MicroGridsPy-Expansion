"""Saving a study and opening it again.

A sizing is an argument a developer will have to defend months later, in front of a lender or
a ministry, and an argument that cannot be reopened is worth little. A project therefore holds
both halves: the answers that were given, and the result they produced, so that reopening it
shows what was decided *and* on what basis — rather than inviting a rerun whose defaults may
since have moved.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .i18n import DEFAULT as DEFAULT_LANG
from .i18n import t
from ..paths import RESULTS_DIR

PROJECTS_DIR = RESULTS_DIR.parent / "projets"
_SAFE = re.compile(r"[^A-Za-z0-9À-ÿ _.-]")


def _slug(name: str) -> str:
    cleaned = _SAFE.sub("", name).strip().replace(" ", "-").lower()
    return cleaned or "sans-nom"


@dataclass(frozen=True)
class Project:
    name: str
    slug: str
    saved_at: str
    overrides: dict[str, Any]
    results: dict[str, Any]

    def to_dict(self) -> dict:
        return {"name": self.name, "slug": self.slug, "saved_at": self.saved_at,
                "overrides": self.overrides, "results": self.results}


def save(name: str, overrides: dict, results: dict) -> Project:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    project = Project(name=name.strip() or "Sans nom", slug=_slug(name),
                      saved_at=datetime.now(timezone.utc).isoformat(),
                      overrides=overrides or {}, results=results or {})
    path = PROJECTS_DIR / f"{project.slug}.json"
    path.write_text(json.dumps(project.to_dict(), indent=2, ensure_ascii=False,
                               default=float), encoding="utf-8")
    return project


def load(slug: str) -> Project:
    path = PROJECTS_DIR / f"{_slug(slug)}.json"
    if not path.exists():
        raise FileNotFoundError(f"projet introuvable : {slug}")
    record = json.loads(path.read_text(encoding="utf-8"))
    return Project(name=record.get("name", slug), slug=record.get("slug", slug),
                   saved_at=record.get("saved_at", ""),
                   overrides=record.get("overrides", {}),
                   results=record.get("results", {}))


def remove(slug: str) -> bool:
    path = PROJECTS_DIR / f"{_slug(slug)}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def listing() -> list[dict]:
    """Saved projects, newest first, without their payloads."""
    if not PROJECTS_DIR.exists():
        return []
    out = []
    for path in PROJECTS_DIR.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue                       # a half-written file must not hide the others
        size = record.get("results", {})
        out.append({"name": record.get("name", path.stem), "slug": path.stem,
                    "saved_at": record.get("saved_at", ""),
                    "site": record.get("overrides", {}).get("site"),
                    "has_size": bool(size.get("size")),
                    "has_plan": bool(size.get("plan"))})
    return sorted(out, key=lambda r: r["saved_at"], reverse=True)


# ------------------------------------------------------------------------- export
def as_csv(result: dict, kind: str, lang: str = DEFAULT_LANG) -> str:
    """One flat table a spreadsheet opens without asking questions.

    The headers follow the language the interface is being read in: an export is a document
    someone hands to a colleague, and it should speak the language they were reading.
    """
    rows: list[tuple[str, Any]] = []
    if kind == "size":
        d = result.get("design", {})
        rows += [(t("csv.site", lang), result.get("site")),
                 (t("csv.trajectory", lang), result.get("trajectory")),
                 (t("csv.coupling", lang), result.get("architecture")),
                 (t("csv.pv_dc", lang), d.get("pv_kw")),
                 (t("csv.pv_ac", lang), d.get("pv_ac_kw")),
                 (t("csv.storage", lang), d.get("battery_kwh")),
                 (t("csv.inverter", lang), d.get("inverter_kw")),
                 (t("csv.generator", lang), d.get("generator_kw")),
                 (t("csv.z_rule", lang), result.get("z_rule_usd_yr")),
                 (t("csv.z_opt", lang),
                  result.get("z_opt_usd_yr")),
                 (t("csv.gap", lang), result.get("price_rel_pct")),
                 (t("csv.lcoe", lang), result.get("lcoe_usd_kwh")),
                 (t("csv.npc", lang), result.get("npc_usd")),
                 (t("csv.subsidy", lang), result.get("subsidy_fraction")),
                 (t("csv.served", lang), result.get("energy_served_kwh")),
                 (t("csv.unserved", lang), result.get("unserved_kwh")),
                 (t("csv.proven", lang), result.get("proven")),
                 (t("csv.lattice", lang), result.get("lattice_size")),
                 (t("csv.pruned", lang), result.get("pruned_points")),
                 (t("csv.evaluated", lang), result.get("enumerated_points")),
                 (t("csv.seconds", lang), result.get("seconds"))]
    else:
        p = result.get("root_plan", {})
        e = result.get("expected", {})
        rows += [(t("csv.site", lang), result.get("site")),
                 (t("csv.coupling", lang), result.get("architecture")),
                 (t("csv.nodes", lang), result.get("nodes")),
                 (t("csv.leaves", lang), result.get("leaves")),
                 (t("csv.pv_dc", lang), p.get("pv_kw")),
                 (t("csv.pv_ac", lang), p.get("pv_ac_kw")),
                 (t("csv.storage", lang), p.get("battery_kwh")),
                 (t("csv.inverter", lang), p.get("inverter_kw")),
                 (t("csv.generator", lang), p.get("generator_kw")),
                 (t("csv.exp_lcoe", lang), e.get("expected_lcoe_usd_kwh")),
                 (t("csv.exp_cost", lang), e.get("expected_rule_cost_usd")),
                 (t("csv.gap", lang), e.get("price_of_heuristic_pct"))]

    lines = [f'{t("csv.quantity", lang)};{t("csv.value", lang)}']
    lines += [f"{k};{'' if v is None else v}" for k, v in rows]

    per_node = result.get("per_node")
    if per_node:
        lines += ["", ";".join(t(f"csv.node.{c}", lang) for c in
                               ("node", "stage", "probability", "pv_dc", "pv_ac",
                                "storage", "inverter", "served", "unserved"))]
        for n in per_node:
            lines.append(";".join(str(n.get(k, "")) for k in
                                  ("node", "stage", "probability", "pv_kw", "pv_ac_kw",
                                   "battery_kwh", "inverter_kw", "energy_served_kwh",
                                   "unserved_kwh")))
    return "\r\n".join(lines) + "\r\n"
