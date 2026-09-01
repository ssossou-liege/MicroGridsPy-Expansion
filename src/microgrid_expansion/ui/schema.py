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
from .i18n import DEFAULT as DEFAULT_LANG
from .i18n import has, t


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
    #: Catalogue key for the label and the hint. When set, the two above are ignored and the
    #: strings come from the catalogue in the reader's language.
    key: str = ""
    #: Whose provenance record describes *this* value. Left empty when none does, which is
    #: the honest answer for most: walking up to the group's record instead made a lifetime
    #: display the source of a price, and a string-inverter price display the whole
    #: coupling note. A source shown against a value it does not describe is worse than no
    #: source at all, because it invites trust the record does not support.
    source_path: str = ""


#: What a developer states about the site. Everything else has a default worth trusting.
ESSENTIAL: tuple[Field, ...] = (
    Field("demand_trajectory", "Demand growth", kind="choice",
          choices=("slow", "central", "fast"),
          hint="How fast consumption grows with the age of the connection.", key="f.trajectory"),
    Field("maturity_months", "Age of the connection", "months", kind="integer",
          hint="Zero for a new site; twelve for a grid a year into service.", key="f.maturity"),
    Field("economics.horizon_years", "Project horizon", "years", kind="integer", key="f.horizon"),
    Field("economics.discount_rate", "Discount rate", "", step=0.005,
          source_path="economics.discount", key="f.discount"),
    Field("economics.diesel_price_usd_l", "Diesel price", "$/L", step=0.01,
          source_path="economics.diesel", key="f.diesel"),
    Field("economics.tariff_usd_kwh", "Target tariff", "$/kWh", step=0.001,
          source_path="economics.tariff",
          hint="Levelised-cost target; the tool reports the subsidy that reaches it.", key="f.tariff"),
    Field("economics.demand_growth_rate", "Annual demand growth", "", step=0.01,
          hint="Used by the financial appraisal alone, to project revenue. The sizing is "
               "for the year and the connection age stated; serving that growth is "
               "what the expansion plan is for.", key="f.growth"),
)

#: How amounts are shown. The model computes in dollars because that is the currency its
#: sources are restated in; a developer negotiates, quotes and defends a budget in the
#: currency of the country, and an interface that will not speak it forces a spreadsheet
#: between the tool and every conversation it is meant to support.
CURRENCY: tuple[Field, ...] = (
    Field("currency.local_code", "Local currency", kind="choice",
          choices=("XOF", "USD", "EUR", "NGN", "GHS", "KES", "TZS", "ZMW", "MWK"),
          hint="Amounts are shown in this currency; the computation stays in dollars.", key="f.currency"),
    Field("currency.xof_per_eur", "Local units per euro", "", step=0.01,
          hint="A fixed peg for the CFA franc; a market rate for the others.", key="f.per_eur"),
    Field("currency.usd_per_eur", "Dollars per euro", "", step=0.01, key="f.usd_eur"),
)

#: The national grid, where there is one or where one is expected. Half the projects that
#: need sizing sit where the grid is due within a decade, and the question is not whether it
#: arrives but what to build in the meantime.
GRID: tuple[Field, ...] = (
    Field("grid.connected", "Connected to the grid", kind="choice",
          choices=("no", "yes"),
          hint="An intermittent grid displaces the fuel, not the storage: it is the "
               "generating set it replaces, the battery still being needed for the "
               "outages.", key="f.grid.connected"),
    Field("grid.availability", "Grid availability", "", step=0.01,
          hint="Share of the hours the feeder is live.", key="f.grid.availability"),
    Field("grid.mean_outage_hours", "Typical length of an outage", "h", step=0.5,
          hint="What the plant must carry alone, and so what sizes the storage. An "
               "average availability does not say it.", key="f.grid.outage"),
    Field("grid.import_usd_kwh", "Price of imported energy", "$/kWh", step=0.01,
          source_path="grid.tariff",
          hint="To be taken from the utility: a regulated tariff is particular to the "
               "country and often banded. The value offered is an order of magnitude.", key="f.grid.import"),
    Field("grid.export_usd_kwh", "Price of exported energy", "$/kWh", step=0.01,
          source_path="grid.tariff",
          hint="Zero where export is not paid for; the surplus is then curtailed.", key="f.grid.export"),
    Field("grid.capacity_kw", "Connection capacity", "kW", step=1.0,
          hint="Zero to impose no limit beyond the converter's own.", key="f.grid.capacity"),
    Field("grid.connection_usd", "Cost of the connection", "$", step=100.0,
          hint="Line, metering, protection.", key="f.grid.cost"),
    Field("grid.arrival_uncertain", "Treat the arrival as uncertain", kind="choice",
          choices=("no", "yes"),
          hint="For a village where the line is announced without a date. The expansion "
               "plan then branches on its arrival: what is committed today must hold "
               "whether it comes or not. Immaterial where the grid is already there, "
               "or plainly not planned.", key="f.grid.uncertain"),
)

#: Prices and equipment, which move from one market to another.
EQUIPMENT: tuple[Field, ...] = (
    Field("photovoltaic.cost_usd_kw", "Photovoltaic", "$/kW", step=1.0,
          source_path="photovoltaic", key="f.pv_cost"),
    Field("battery.cost_usd_kwh", "Storage", "$/kWh", step=1.0, source_path="battery", key="f.batt_cost"),
    Field("inverter.cost_usd_kw", "Power electronics", "$/kW", step=1.0,
          source_path="inverter", key="f.inv_cost"),
    Field("coupling.string_inverter_cost_usd_kw", "String inverters", "$/kW", step=1.0,
          source_path="coupling", key="f.string_cost"),
    Field("photovoltaic.lifetime_years", "Photovoltaic lifetime", "years",
          kind="integer", key="f.pv_life"),
    Field("battery.lifetime_years", "Storage lifetime", "years", kind="integer", key="f.batt_life"),
    Field("inverter.lifetime_years", "Converter lifetime", "years", kind="integer", key="f.inv_life"),
)

#: Everything between the plant and the customer's lamp. It is perhaps half of what a
#: mini-grid costs and none of it can be inferred from the site's coordinates, so all of it
#: starts at zero and says so. A sizing priced at the plant alone is not wrong about the
#: plant; it is silent about the project.
BALANCE: tuple[Field, ...] = (
    Field("infrastructure.distribution_usd", "Distribution network", "$", step=1000.0,
          source_path="infrastructure",
          hint="Poles, conductor, earthing and the labour to string them. A lump sum: no "
               "per-kilometre figure carries from a compact village to a scattered one.",
          key="f.distribution"),
    Field("infrastructure.connection_single_phase_usd", "Connection, single phase", "$",
          step=10.0,
          hint="Per household connected, meter included: service drop, board, meter, "
               "labour.", key="f.connection_1p"),
    Field("infrastructure.connection_three_phase_usd", "Connection, three phase", "$",
          step=10.0,
          hint="Per productive customer. The mill, the welder and the sawmill take three "
               "phases, and they are counted from the productive units declared for the "
               "community.", key="f.connection_3p"),
    Field("infrastructure.civil_works_usd", "Civil works", "$", step=1000.0,
          hint="Foundations, plant room or container, fencing, access, earthing.",
          key="f.civil"),
    Field("infrastructure.development_usd", "Development", "$", step=1000.0,
          hint="Feasibility, survey, permits, design and the developer's own time before "
               "financial close. Spent once and never replaced.", key="f.development"),
    Field("economics.collection_rate", "Energy billed and collected", "", step=0.01,
          hint="Share of the energy served that is actually paid for. One means every "
               "kilowatt-hour delivered is billed and collected, which no rural mini-grid "
               "achieves.", key="f.collection"),
)

#: How the plant is wired and run. Changing these changes what the certificate means.
ADVANCED: tuple[Field, ...] = (
    Field("coupling.architecture", "Coupling", kind="choice",
          choices=("mixed", "dc", "ac", "auto"),
          hint="The divided array contains both pure arrangements as extreme cases.", key="f.coupling"),
    Field("coupling.dc_ac_ratio_max", "Array admitted per kW, battery bus", "kW/kW", step=0.1,
          source_path="coupling", key="f.ratio_dc"),
    Field("coupling.ac_ratio_max", "Array admitted per kW, load bus", "kW/kW", step=0.1,
          source_path="coupling", key="f.ratio_ac"),
    Field("controller.reserve_multiplier", "Look-ahead reserve", "", step=0.1,
          hint="Multiplies the energy the controller keeps for the night ahead.", key="f.reserve"),
    Field("controller.lookahead_hours", "Look-ahead window", "h", kind="integer", key="f.lookahead"),
    Field("controller.generator_setpoint", "Generator setpoint", "", step=0.05, key="f.setpoint"),
    Field("economics.value_of_lost_load_usd_kwh", "Unserved energy", "$/kWh",
          step=0.1, source_path="economics.voll", key="f.voll"),
    Field("economics.min_service_fraction", "Required service level", "", step=0.005,
          hint="The least share of demand a design must serve to be admitted. Leave it at "
               "zero to require nothing and let the cost of unserved energy arbitrate "
               "alone; raise it to 0.98 where a concession imposes one.", key="f.service"),
    Field("solver.name", "Solver", kind="choice", choices=("gurobi", "highs"), key="f.solver"),
)

GROUPS: tuple[tuple[str, str, tuple[Field, ...]], ...] = (
    ("project", "The project", ESSENTIAL),
    ("currency", "Display currency", CURRENCY),
    ("grid", "National grid", GRID),
    ("equipment", "Prices and equipment", EQUIPMENT),
    ("balance", "Beyond the plant", BALANCE),
    ("advanced", "Architecture and control", ADVANCED),
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


def provenance_of(settings: ProjectSettings, source_path: str,
                  lang: str = DEFAULT_LANG) -> str | None:
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
        # No source is itself worth showing, and the note is where a record says so. A field
        # whose value nobody has checked should say nothing rather than look sourced -- but
        # a field that says "unsourced, go and ask the concession" is telling the reader the
        # single most useful thing about it.
        note = getattr(record, "note", None)
        if note and not getattr(record, "verified", False):
            return f'{t("source.unsourced", lang)} — {note}'
    return None


def describe(settings: ProjectSettings | None = None,
             lang: str = DEFAULT_LANG) -> list[dict]:
    """Every offered field, with its value and its source, ready for the page."""
    settings = default_settings() if settings is None else settings
    out = []
    for key, title, group in GROUPS:
        entries = []
        for f in group:
            label = t(f"{f.key}", lang) if f.key else f.label
            # A field without a hint carries no ".hint" entry, and t() would hand back the
            # key itself. An absent hint is an absent hint, not a label.
            hint = t(f"{f.key}.hint", lang) if f.key and has(f"{f.key}.hint") else f.hint
            entries.append({
                "path": f.path, "label": label, "unit": f.unit, "kind": f.kind,
                "choices": list(f.choices), "step": f.step, "hint": hint,
                "value": ({True: "yes", False: "no"}[read(settings, f.path)]
                          if f.kind == "choice" and isinstance(read(settings, f.path), bool)
                          else read(settings, f.path)),
                "source": provenance_of(settings, f.source_path, lang),
            })
        out.append({"key": key, "title": t(f"group.{key}", lang) or title,
                    "fields": entries})
    return out


#: Settled elsewhere than on the form -- the community page owns the site -- but still
#: carried in the same bag of overrides, so ``apply`` must not reject them.
ELSEWHERE = frozenset({"site"})


def apply(settings: ProjectSettings, overrides: dict[str, Any]) -> ProjectSettings:
    """Write the page's answers back, converting to the type each field already holds."""
    known = {f.path for _, _, group in GROUPS for f in group} | ELSEWHERE
    for path, value in overrides.items():
        if path not in known:
            raise KeyError(f"unknown setting: {path}")
        owner, name = _resolve(settings, path)
        current = getattr(owner, name)
        if value is None:
            # A field whose current value is absent round-trips as absent; converting it
            # would turn "not required" into zero, which for a service floor is the
            # difference between no requirement and an impossible one.
            setattr(owner, name, None)
            continue
        if isinstance(current, bool):
            value = value in (True, "yes", "true", 1, "1") if isinstance(value, (str, bool, int)) \
                else bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            value = int(round(float(value)))
        elif isinstance(current, float) or current is None:
            # A floor of zero is no floor: the field reads as a percentage a contract names,
            # and leaving it at zero must mean "not required" rather than "serve nothing".
            value = float(value)
            if path == "economics.min_service_fraction" and value <= 0.0:
                value = None
        setattr(owner, name, value)
    settings.validate()
    return settings
