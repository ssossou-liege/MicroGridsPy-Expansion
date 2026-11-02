"""Which settings the interface offers, and how to describe them to a page.

The engine carries some sixty parameters. Putting all sixty on a form is what the tools this
one means to improve already do, and it makes a developer read sixty questions to answer six.
Almost every one has a default worth trusting, so the form asks only for what a site
actually changes and keeps the rest behind an inspector where the value can be read and, if
need be, overridden.
"""
from __future__ import annotations

from dataclasses import dataclass
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


#: What a developer states about the site. Everything else has a default worth trusting.
ESSENTIAL: tuple[Field, ...] = (
    # The three weights replace the single growth choice that used to sit here. That choice
    # moved nothing: the tree, which decides what to build, never read it, and a reader who
    # picked "slow" changed only a side study while believing they had changed the answer.
    Field("trajectory_weights.slow", "Slow growth", "", step=0.05, key="f.weight_slow"),
    Field("trajectory_weights.central", "Central growth", "", step=0.05,
          key="f.weight_central"),
    Field("trajectory_weights.fast", "Fast growth", "", step=0.05, key="f.weight_fast"),
    Field("maturity_months", "Age of the connection", "months", kind="integer",
          hint="Zero for a new site; twelve for a grid a year into service.", key="f.maturity"),
    Field("economics.horizon_years", "Project horizon", "years", kind="integer", key="f.horizon"),
    Field("economics.discount_rate", "Discount rate", "", step=0.005, key="f.discount"),
    Field("economics.diesel_price_usd_l", "Diesel price", "$/L", step=0.01, key="f.diesel"),
    Field("economics.tariff_usd_kwh", "Target tariff", "$/kWh", step=0.001,
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
          hint="To be taken from the utility: a regulated tariff is particular to the "
               "country and often banded. The value offered is an order of magnitude.", key="f.grid.import"),
    Field("grid.export_usd_kwh", "Price of exported energy", "$/kWh", step=0.01,
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
    Field("photovoltaic.cost_usd_kw", "Photovoltaic", "$/kW", step=1.0, key="f.pv_cost"),
    Field("battery.cost_usd_kwh", "Storage", "$/kWh", step=1.0, key="f.batt_cost"),
    Field("inverter.cost_usd_kw", "Power electronics", "$/kW", step=1.0, key="f.inv_cost"),
    Field("coupling.string_inverter_cost_usd_kw", "String inverters", "$/kW", step=1.0, key="f.string_cost"),
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
    Field("infrastructure.network_loss_fraction", "Network losses", "", step=0.01,
          hint="Share of the energy the plant sends into the network that the network "
               "itself consumes. The plant must produce it and nobody is billed for it, so "
               "it sizes the plant like a customer and earns nothing. It does not apply to "
               "the powerhouse, which draws from the busbar beside it. The default is the "
               "thirteen per cent measured on one reference village's feeder meters; a "
               "village with feeder meters of its own should enter what they show.",
          key="f.network_loss"),
    Field("economics.collection_rate", "Customer bills collected", "", step=0.01,
          hint="Share of what is invoiced to customers that is actually paid. It does not "
               "apply to the loads nobody is billed for -- the street lighting, the plant's "
               "own supply -- which are declared as uses and served without being sold.",
          key="f.collection"),
)

#: How the plant is wired and run. Changing these changes what the certificate means.
#: The one-trajectory study, which is no longer how the answer is reached. It is kept
#: because "what would this village need if it grew slowly" is a fair question; it is kept
#: here, away from the decision, because answering it is not taking the decision.
WHAT_IF: tuple[Field, ...] = (
    Field("demand_trajectory", "Certify a single trajectory instead", kind="choice",
          choices=("slow", "central", "fast"), key="f.trajectory"),
)


ADVANCED: tuple[Field, ...] = (
    Field("coupling.architecture", "Coupling", kind="choice",
          choices=("mixed", "dc", "ac", "auto"),
          hint="The divided array contains both pure arrangements as extreme cases.", key="f.coupling"),
    Field("coupling.dc_ac_ratio_max", "Array admitted per kW, battery bus", "kW/kW", step=0.1, key="f.ratio_dc"),
    Field("coupling.ac_ratio_max", "Array admitted per kW, load bus", "kW/kW", step=0.1, key="f.ratio_ac"),
    Field("controller.reserve_multiplier", "Look-ahead reserve", "", step=0.1,
          hint="Multiplies the energy the controller keeps for the night ahead.", key="f.reserve"),
    Field("controller.lookahead_hours", "Look-ahead window", "h", kind="integer", key="f.lookahead"),
    Field("controller.generator_setpoint", "Generator setpoint", "", step=0.05, key="f.setpoint"),
    Field("economics.value_of_lost_load_usd_kwh", "Unserved energy", "$/kWh",
          step=0.1, key="f.voll"),
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
    ("what_if", "A single trajectory, as a study", WHAT_IF),
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


def describe(settings: ProjectSettings | None = None,
             lang: str = DEFAULT_LANG) -> list[dict]:
    """Every offered field, with its value, ready for the page."""
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
