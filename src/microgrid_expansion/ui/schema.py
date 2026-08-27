"""Which settings the interface offers, and how to describe them to a page.

The engine carries some sixty parameters. Putting all sixty on a form is what the tools this
one means to improve already do, and it makes a developer read sixty questions to answer six.
Almost every one has a sourced default, so the form asks only for what a site actually
changes and keeps the rest behind an inspector where the value and its source can be read and,
if need be, overridden.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from ..settings import ProjectSettings, default_settings


@dataclass(frozen=True)
class Field:
    """One editable setting, addressed by its dotted path in the settings tree."""

    path: str
    label: str
    unit: str = ""
    kind: str = "number"              # number | integer | choice | text
    choices: tuple[str, ...] = ()
    step: float | None = None
    hint: str = ""
    #: Whose provenance record describes *this* value. Left empty when none does, which is
    #: the honest answer for most: walking up to the group's record instead made a lifetime
    #: display the source of a price, and a string-inverter price display the whole
    #: coupling note. A source shown against a value it does not describe is worse than no
    #: source at all, because it invites trust the record does not support.
    source_path: str = ""


#: What a developer states about the site. Everything else has a default worth trusting.
ESSENTIAL: tuple[Field, ...] = (
    Field("site", "Localité", kind="choice", choices=("Samionta", "Gbowele"),
          hint="Site instrumenté servant de base à la demande."),
    Field("demand_trajectory", "Croissance de la demande", kind="choice",
          choices=("lente", "centrale", "rapide"),
          hint="Rythme auquel la consommation croît avec l'ancienneté du raccordement."),
    Field("maturity_months", "Ancienneté du raccordement", "mois", kind="integer",
          hint="Zéro pour un site neuf ; douze pour un réseau en service depuis un an."),
    Field("economics.horizon_years", "Horizon du projet", "ans", kind="integer"),
    Field("economics.discount_rate", "Taux d'actualisation", "", step=0.005,
          source_path="economics.discount"),
    Field("economics.diesel_price_usd_l", "Prix du gazole", "$/L", step=0.01,
          source_path="economics.diesel"),
    Field("economics.tariff_usd_kwh", "Tarif visé", "$/kWh", step=0.001,
          source_path="economics.tariff",
          hint="Cible de coût actualisé ; l'outil rapporte la subvention qui l'atteint."),
)

#: Prices and equipment, which move from one market to another.
EQUIPMENT: tuple[Field, ...] = (
    Field("photovoltaic.cost_usd_kw", "Photovoltaïque", "$/kW", step=1.0,
          source_path="photovoltaic"),
    Field("battery.cost_usd_kwh", "Stockage", "$/kWh", step=1.0, source_path="battery"),
    Field("inverter.cost_usd_kw", "Électronique de puissance", "$/kW", step=1.0,
          source_path="inverter"),
    Field("coupling.string_inverter_cost_usd_kw", "Onduleurs de chaîne", "$/kW", step=1.0,
          source_path="coupling"),
    Field("photovoltaic.lifetime_years", "Durée de vie du photovoltaïque", "ans",
          kind="integer"),
    Field("battery.lifetime_years", "Durée de vie du stockage", "ans", kind="integer"),
    Field("inverter.lifetime_years", "Durée de vie de la conversion", "ans", kind="integer"),
)

#: How the plant is wired and run. Changing these changes what the certificate means.
ADVANCED: tuple[Field, ...] = (
    Field("coupling.architecture", "Couplage", kind="choice",
          choices=("mixte", "dc", "ac", "auto"),
          hint="Le champ divisé contient les deux dispositions pures comme cas extrêmes."),
    Field("coupling.dc_ac_ratio_max", "Champ admis par kW, bus batterie", "kW/kW", step=0.1,
          source_path="coupling"),
    Field("coupling.ac_ratio_max", "Champ admis par kW, bus charge", "kW/kW", step=0.1,
          source_path="coupling"),
    Field("controller.reserve_multiplier", "Réserve d'anticipation", "", step=0.1,
          hint="Multiplie l'énergie que l'automate garde pour la nuit à venir."),
    Field("controller.lookahead_hours", "Fenêtre d'anticipation", "h", kind="integer"),
    Field("controller.generator_setpoint", "Consigne du groupe", "", step=0.05),
    Field("economics.value_of_lost_load_usd_kwh", "Énergie non distribuée", "$/kWh",
          step=0.1, source_path="economics.voll"),
    Field("solver.name", "Solveur", kind="choice", choices=("gurobi", "highs")),
)

GROUPS: tuple[tuple[str, str, tuple[Field, ...]], ...] = (
    ("essentiel", "Le site", ESSENTIAL),
    ("materiel", "Prix et matériel", EQUIPMENT),
    ("avance", "Architecture et conduite", ADVANCED),
)


def _resolve(settings: Any, path: str) -> tuple[Any, str]:
    """The object holding ``path``'s last segment, and that segment's name."""
    owner = settings
    parts = path.split(".")
    for part in parts[:-1]:
        owner = getattr(owner, part)
    return owner, parts[-1]


def read(settings: ProjectSettings, path: str) -> Any:
    owner, name = _resolve(settings, path)
    return getattr(owner, name)


def provenance_of(settings: ProjectSettings, source_path: str) -> str | None:
    """The recorded source at ``source_path``, or nothing.

    Shown beside a field so a developer overriding a price can see what they are overriding,
    rather than discovering later that a sourced figure was replaced by a guess. Read only
    where the record actually describes the value: ``"battery"`` reads the battery spec's own
    note, ``"economics.diesel"`` reads ``diesel_provenance``.
    """
    if not source_path:
        return None
    if "." in source_path:
        group, name = source_path.rsplit(".", 1)
        owner = settings
        for part in group.split("."):
            owner = getattr(owner, part)
        record = getattr(owner, f"{name}_provenance", None)
    else:
        record = getattr(getattr(settings, source_path), "provenance", None)
    if record is not None and is_dataclass(record):
        source = getattr(record, "source", None)
        if source:
            return str(source)
    return None


def describe(settings: ProjectSettings | None = None) -> list[dict]:
    """Every offered field, with its value and its source, ready for the page."""
    settings = default_settings() if settings is None else settings
    out = []
    for key, title, group in GROUPS:
        entries = []
        for f in group:
            entries.append({
                "path": f.path, "label": f.label, "unit": f.unit, "kind": f.kind,
                "choices": list(f.choices), "step": f.step, "hint": f.hint,
                "value": read(settings, f.path),
                "source": provenance_of(settings, f.source_path),
            })
        out.append({"key": key, "title": title, "fields": entries})
    return out


def apply(settings: ProjectSettings, overrides: dict[str, Any]) -> ProjectSettings:
    """Write the page's answers back, converting to the type each field already holds."""
    known = {f.path for _, _, group in GROUPS for f in group}
    for path, value in overrides.items():
        if path not in known:
            raise KeyError(f"réglage inconnu : {path}")
        owner, name = _resolve(settings, path)
        current = getattr(owner, name)
        if isinstance(current, bool):
            value = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            value = int(round(float(value)))
        elif isinstance(current, float):
            value = float(value)
        setattr(owner, name, value)
    settings.validate()
    return settings
