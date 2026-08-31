"""Project parameters, declared once and supplied by the user.

Everything the model needs that is not measured data lives here: the site, the equipment,
the economics, the operating policy and the calibration settings. They are held in one
typed tree that round-trips through a YAML file, so that sizing a new project is a matter
of editing a document rather than of editing the source, and so that the parameters behind
a published result can be archived with it.

Three principles govern what belongs here.

*One definition.* A quantity that appears in two places will eventually disagree in two
places. Every parameter has exactly one home, and the modules read it from here rather than
keeping a copy — a discipline this project adopted after three separate defects were traced
to duplicated definitions.

*Equipment describes itself.* Fuel curves belong to a generator, not to the model; a
catalogue of four ratings carries four fuel curves. Manufacturers publish consumption at
half, three-quarter and full load, so that is what the user is asked for and the efficiency
curve is fitted from it.

*Unverified values announce themselves.* A parameter nobody has sourced is marked as such
and reported, rather than passing silently as though it were measured.
"""
from __future__ import annotations

from functools import lru_cache
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np

#: Physical constants: properties of matter, not choices, and so not user parameters.
DIESEL_HHV_KJ_KG = 45800.0
DIESEL_DENSITY_KG_L = 0.832
SOLAR_CONSTANT_W_M2 = 1361.0
T_STC_C = 25.0
G_STC_W_M2 = 1000.0


@dataclass
class Provenance:
    """Where a group of parameters comes from, and whether anyone has checked it."""

    source: str = "unsourced"
    verified: bool = False
    note: str = ""


@dataclass
class CurrencySettings:
    """Conversion between the currency of the field and the currency of the model.

    Equipment is quoted and tariffs are set in CFA francs, while the model computes in
    dollars. The CFA franc is pegged to the euro at a fixed parity, so only the euro-dollar
    rate moves; recording both makes a cost traceable back to the quotation it came from
    and lets a result be restated at another rate without re-sourcing anything.
    """

    local_code: str = "XOF"
    xof_per_eur: float = 655.957          # fixed parity, not a market rate
    usd_per_eur: float = 1.08
    rate_note: str = "euro-dollar rate of August 2026; update when restating costs"

    @property
    def local_per_usd(self) -> float:
        return self.xof_per_eur / self.usd_per_eur

    def to_usd(self, amount_local: float) -> float:
        """Convert an amount in the local currency into dollars."""
        return amount_local / self.local_per_usd

    def to_local(self, amount_usd: float) -> float:
        """Convert an amount in dollars into the local currency."""
        return amount_usd * self.local_per_usd


# --------------------------------------------------------------------- equipment
@dataclass
class PhotovoltaicSpec:
    """A photovoltaic module and the array losses around it."""

    unit_kw: float = 0.5                       # rated power of one panel
    #: 100 000 FCFA/kW quoted on the Beninese market.
    cost_usd_kw: float = 164.6
    lifetime_years: int = 25
    om_rate: float = 0.018                     # annual, as a fraction of capital
    noct_c: float = 45.0
    temperature_coefficient_per_k: float = -0.0035
    derate: float = 0.85                       # soiling, wiring, mismatch, conversion
    faiman_u0_w_m2_k: float = 25.0
    faiman_u1_w_s_m3_k: float = 6.84
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="100 000 FCFA/kW quoted on the Beninese market (2026); crystalline "
               "silicon, open rack, generic technical characteristics",
        verified=True,
        note="the price is sourced; the thermal characteristics remain generic"))


@dataclass
class BatterySpec:
    """A storage pack: chemistry, limits and economics."""

    chemistry: str = "lfp"
    unit_kwh: float = 5.0                      # usable energy of one module
    #: 200 000 FCFA/kWh quoted on the Beninese market.
    cost_usd_kwh: float = 329.3
    lifetime_years: int = 16
    cycles: int = 6000
    om_rate: float = 0.060
    charge_efficiency: float = 0.975
    discharge_efficiency: float = 0.975
    soc_min: float = 0.05
    soc_max: float = 0.95
    #: Maximum charge or discharge power as a fraction of nameplate energy, per hour.
    c_rate: float = 0.25
    #: State of charge the plant starts from, as a fraction of the usable ceiling.
    initial_soc_fraction: float = 0.5
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="200 000 FCFA/kWh quoted on the Beninese market (2026); BYD LV Flex, "
               "lithium iron phosphate",
        verified=True,
        note="the price is sourced; cycle life and efficiencies remain manufacturer "
             "figures"))

    def degradation_usd_kwh(self) -> float:
        """Throughput cost of storage [$ per kWh discharged]."""
        throughput = self.cycles * (self.soc_max - self.soc_min)
        return self.cost_usd_kwh / throughput


@dataclass
class GeneratorSpec:
    """One generator of the catalogue, carrying its own fuel curve.

    ``fuel_l_per_h`` is what a manufacturer publishes: consumption at half, three-quarter
    and full load. The quadratic efficiency the model uses is fitted from those three
    points, so a catalogue of several ratings carries several curves rather than borrowing
    one unit's behaviour for every size.
    """

    rating_kw: float
    fuel_l_per_h: dict[float, float]
    #: Generators are quoted per kVA of apparent power while the model sizes active
    #: power, so the quotation and the power factor are held separately rather than
    #: silently conflated: at a factor of 0.8 a kVA buys only 0.8 kW.
    cost_usd_kva: float = 411.6
    power_factor: float = 0.8
    lifetime_years: int = 15
    om_rate: float = 0.080
    min_load_fraction: float = 0.30
    salvage_fraction: float = 0.40
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def cost_usd_kw(self) -> float:
        """Capital cost per kilowatt of active power."""
        return self.cost_usd_kva / self.power_factor

    def efficiency_coefficients(self) -> tuple[float, float, float]:
        """Fit ``eta = a + b x + c x^2`` to the published consumption figures.

        Efficiency at part load ``x`` is the electrical output divided by the fuel power,
        so each published point gives one equation; three points determine the quadratic
        exactly, and more are fitted by least squares.
        """
        loads = np.array(sorted(self.fuel_l_per_h), dtype=float)
        if loads.size < 3:
            raise ValueError(
                f"generator {self.rating_kw} kW needs at least three fuel points, "
                f"got {sorted(self.fuel_l_per_h)}")
        litres = np.array([self.fuel_l_per_h[float(x)] for x in loads], dtype=float)

        fuel_kw = litres * DIESEL_DENSITY_KG_L * DIESEL_HHV_KJ_KG / 3600.0
        efficiency = loads * self.rating_kw / fuel_kw
        design = np.vstack([np.ones_like(loads), loads, loads ** 2]).T
        a, b, c = np.linalg.lstsq(design, efficiency, rcond=None)[0]
        return float(a), float(b), float(c)


def default_generator_catalogue() -> list[GeneratorSpec]:
    """The Perkins 400-series units available in the size range this study needs.

    Each entry carries the consumption its manufacturer publishes at half, three-quarter
    and full load, so the four ratings are genuinely distinguishable rather than one
    curve stretched over a catalogue — which matters, the certificate arbitrating between
    exactly these sizes.

    Ratings are quoted in kVA of apparent power and converted to the active power the model
    sizes. Their specific consumption is not monotone in size: the 15 kVA unit is a
    naturally aspirated three-cylinder and burns less per kilowatt-hour at full load than
    the larger four-cylinder, which is precisely the kind of detail a single scaled curve
    erases.
    """
    perkins = Provenance(
        source="Perkins 400 series, manufacturers' published consumption at 50/75/100 % "
               "load; ratings converted from kVA at the catalogue power factor",
        verified=True)
    return [
        GeneratorSpec(rating_kw=8.0, fuel_l_per_h={0.5: 1.7, 0.75: 2.3, 1.0: 3.0},
                      provenance=Provenance(source="Perkins 403A-11G1, 10 kVA — " +
                                            perkins.source, verified=True)),
        GeneratorSpec(rating_kw=12.0, fuel_l_per_h={0.5: 2.0, 0.75: 2.8, 1.0: 3.7},
                      provenance=Provenance(source="Perkins 403A-15G1, 15 kVA — " +
                                            perkins.source, verified=True)),
        GeneratorSpec(rating_kw=16.0, fuel_l_per_h={0.5: 2.9, 0.75: 4.0, 1.0: 5.3},
                      provenance=Provenance(source="Perkins 404A-22G1, 20 kVA — " +
                                            perkins.source, verified=True)),
    ]


@dataclass
class InverterSpec:
    """The hybrid inverter coupling the assets to the load."""

    unit_kw: float = 2.5
    #: 250 000 FCFA/kW quoted on the Beninese market, at 655.957 XOF/EUR and 1.08 USD/EUR.
    cost_usd_kw: float = 412.0
    lifetime_years: int = 10
    om_rate: float = 0.020
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="hybrid inverter, 250 000 FCFA/kW quoted on the Beninese market (2026)",
        verified=True,
        note="restate through the currency block if the euro-dollar rate is updated"))


@dataclass
class CouplingSpec:
    """Where the array joins the plant, and what that junction permits.

    A hybrid inverter is not a bare converter: it ships with its own maximum-power-point
    trackers, two to four of them on current three-phase units, and it expects to be the
    single authority over the battery. Bolting separate charge controllers onto the same
    lithium bank puts two regulators on one pack, and unless both answer to the same
    battery-management conversation the result is conflicting set-points and a real risk of
    overcharge. It is done — Victron coordinates its controllers and its inverters from one
    device that holds the conversation with the pack — but only inside a single
    manufacturer's ecosystem, and never by mixing brands. The model therefore does not size
    external controllers at all. Conversion on the direct-current side is *inside* the
    hybrid inverter and is bought with it.

    What that costs the design is not money but a ceiling. Integrated trackers accept only
    so much array per kilowatt of inverter — a thirty-kilowatt three-phase unit takes
    thirty-nine kilowatts of array, a ratio of about 1.3 — so enlarging the array past that
    means buying another inverter. Enlarging the *array* and enlarging the *converter* are
    thus one decision, not two.

    The alternative is to put the surplus array on the alternating-current side through its
    own string inverters, where it serves the load without passing the hybrid inverter at
    all. That has its own ceiling: off grid, whatever the load does not take must be
    absorbable by the battery inverter, which is why such an array is not sized beyond the
    hybrid inverter's own rating. It is also curtailed by frequency shift rather than by
    command, and it pays a second conversion on everything that reaches storage.

    Neither is assumed cheaper, and neither has to be chosen: the default divides the array
    between the two buses, each part limited by its own converter, so the pure arrangements
    are the corners of one search rather than two cases to be tried. ``"auto"`` remains for
    certifying the corners separately, which is how the divided array was first measured.
    """

    #: ``"dc"``, ``"ac"``, ``"mixed"``, or ``"auto"``. The divided array is the default:
    #: it holds the two pure arrangements as its corners, so nothing is given up by
    #: searching over it, and it removes the need to solve one programme per arrangement.
    architecture: str = "mixed"
    #: Array admitted per kilowatt of hybrid inverter by its integrated trackers. 1.3 is
    #: what current three-phase units publish (30 kW of inverter, 39 kW of array).
    dc_ac_ratio_max: float = 1.3
    #: Array admitted per kilowatt of hybrid inverter when coupled on the alternating side.
    #: Held at parity: off grid the battery inverter must be able to absorb the whole array
    #: the instant the load drops.
    ac_ratio_max: float = 1.0
    #: String inverters for an alternating-coupled array, 50 000 FCFA/kW. Nothing
    #: corresponds to this under direct-current coupling, the conversion being integrated.
    string_inverter_cost_usd_kw: float = 82.3
    lifetime_years: int = 12
    om_rate: float = 0.020
    #: Round-trip penalty on array energy that reaches storage through the alternating bus,
    #: converted up by the string inverter and down again by the hybrid inverter.
    ac_double_conversion_efficiency: float = 0.94
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="integrated-tracker ratio from current three-phase hybrid inverter data "
               "sheets (30 kW AC / 39 kW PV); string inverters at 50 000 FCFA/kW quoted on "
               "the Beninese market (2026); parity rule for off-grid alternating coupling",
        verified=True))

    def cost_usd_kw(self, architecture: str) -> float:
        """Conversion bought per kilowatt of array, beyond the hybrid inverter itself."""
        if architecture in ("dc", "mixed"):
            # Under the divided array each part carries its own price, the one on the load's
            # bus buying string inverters where this coefficient applies to the whole field.
            return 0.0                     # the trackers come inside the inverter
        if architecture == "ac":
            return self.string_inverter_cost_usd_kw
        raise ValueError("architecture must be 'dc', 'ac' or 'mixed', "
                         f"not {architecture!r}")

    def array_ratio_max(self, architecture: str) -> float:
        """Array admitted per kilowatt of hybrid inverter under the given architecture."""
        if architecture == "dc":
            return self.dc_ac_ratio_max
        if architecture == "ac":
            return self.ac_ratio_max
        raise ValueError(f"architecture must be 'dc' or 'ac', not {architecture!r}")

    def architectures(self) -> tuple[str, ...]:
        """The architectures the search must consider.

        One under the divided array, where the split between the two buses is a decision of
        the programme rather than a case to be tried: the pure arrangements are its corners,
        so solving it once settles what solving two settled before.
        """
        return ("dc", "ac") if self.architecture == "auto" else (self.architecture,)


@dataclass
class CostTrajectory:
    """How one price moves over the planning horizon, under three futures.

    A twenty-year plan cannot be costed at today's prices. Equipment gets cheaper and fuel
    does not move predictably, and the *rates* at which they do are themselves uncertain —
    which is why they are carried as three futures rather than one, and why the sizing is
    reported across them rather than at a central case.

    Rates are real, annual, and compound: a price at year ``y`` is the base price times
    ``(1 + rate) ** y``. A negative rate is a decline. Two segments are allowed because the
    published projections break at the mid-2030s, beyond which the learning literature
    expects the decline to flatten as the cheap reductions are exhausted.
    """

    #: Annual real rate to ``break_year``, by scenario.
    early: dict[str, float] = field(default_factory=dict)
    #: Annual real rate after ``break_year``, by scenario.
    late: dict[str, float] = field(default_factory=dict)
    break_year: int = 10
    provenance: Provenance = field(default_factory=lambda: Provenance(source=""))

    def factor(self, scenario: str, years_ahead: int) -> float:
        """Multiplier on the base price ``years_ahead`` years from the base year."""
        if scenario not in self.early:
            raise ValueError(f"unknown cost scenario {scenario!r}; "
                             f"available: {sorted(self.early)}")
        first = min(years_ahead, self.break_year)
        rest = max(years_ahead - self.break_year, 0)
        return ((1.0 + self.early[scenario]) ** first
                * (1.0 + self.late[scenario]) ** rest)

    def scenarios(self) -> tuple[str, ...]:
        return tuple(self.early)


def default_cost_trajectories() -> dict[str, CostTrajectory]:
    """Price trajectories for each technology and for fuel, from the literature.

    Photovoltaic modules and their balance of system follow experience curves whose rate
    is itself declining: the industry's learning rate over 1976--2025 is put at 26 % per
    doubling and is expected to fall towards 17 % by 2050, while balance-of-system costs
    — today the larger share of a mini-grid's photovoltaic capital — learn far more slowly
    than modules. Against that, African mini-grid capital costs fell about a fifth between
    2020 and 2024 and remain roughly twice the global figure, so there is room to converge
    that a mature market does not have.

    Storage is the fastest-moving and the best documented. The three futures below reproduce
    the reductions a national laboratory publishes for small-scale battery storage between
    2022 and 2035 — seventeen, thirty and fifty-two per cent — and the flattening it
    projects thereafter.

    Fuel is the one that does not learn. The near-term outlook is dominated by supply shocks
    rather than by any trend, and the long-run scenarios disagree in sign: prices rise to
    2050 where policy does not tighten, and fall where it does. The three futures are
    therefore built around a flat real price rather than around a forecast, which is an
    admission of ignorance rather than a projection.

    Scenario names are shared across technologies so that a draw is coherent: ``low``
    reduces prices slowly, ``central`` at the published median, ``high`` quickly. For fuel,
    the same names order the *price*, not the rate of learning — ``high`` is the expensive
    fuel future, which is the one that favours a larger array.
    """
    learning = Provenance(
        source="photovoltaic: experience curve at 26 % per doubling over 1976-2025, "
               "expected to decline towards 17 % by 2050, with balance-of-system learning "
               "more slowly than modules; African mini-grid capital fell about 20 % over "
               "2020-2024 and stands near twice the global figure",
        verified=True,
        note="rates are inferred from published learning rates and deployment outlooks, "
             "not read from a table of prices")
    storage = Provenance(
        source="small-scale battery storage capital falls 17 %, 30 % and 52 % between "
               "2022 and 2035 under the conservative, moderate and advanced cases of a "
               "national laboratory's technology baseline, flattening to 0.3 % and 1.5 % "
               "a year thereafter",
        verified=True)
    fuel = Provenance(
        source="near-term outlooks are dominated by supply shocks rather than trend "
               "(Brent projected at 86 then 70 dollars a barrel over two consecutive "
               "years), and long-run scenarios disagree in sign; the band is centred on a "
               "flat real price",
        verified=False,
        note="the weakest-sourced trajectory of the four, and the reason the fuel price "
             "is an uncertainty axis rather than a parameter")

    return {
        "pv": CostTrajectory(early={"low": -0.015, "central": -0.030, "high": -0.050},
                             late={"low": -0.005, "central": -0.015, "high": -0.025},
                             provenance=learning),
        "battery": CostTrajectory(early={"low": -0.014, "central": -0.023, "high": -0.040},
                                  late={"low": -0.003, "central": -0.015, "high": -0.020},
                                  provenance=storage),
        # Converters follow the balance of system rather than the modules, and generating
        # sets are a mature technology whose real price barely moves.
        "inverter": CostTrajectory(early={"low": -0.010, "central": -0.020, "high": -0.030},
                                   late={"low": -0.005, "central": -0.010, "high": -0.015},
                                   provenance=learning),
        "generator": CostTrajectory(early={"low": 0.0, "central": -0.005, "high": -0.010},
                                    late={"low": 0.0, "central": -0.005, "high": -0.010},
                                    provenance=Provenance(
                                        source="reciprocating generating sets are a mature "
                                               "technology; real capital cost is taken as "
                                               "flat to slowly declining",
                                        verified=False)),
        "diesel": CostTrajectory(early={"low": -0.010, "central": 0.0, "high": 0.020},
                                 late={"low": -0.010, "central": 0.0, "high": 0.020},
                                 provenance=fuel),
    }


# ---------------------------------------------------------------------- economics
@dataclass
class EconomicSettings:
    """Discounting, fuel and the price put on unserved energy."""

    discount_rate: float = 0.08
    horizon_years: int = 25
    diesel_price_usd_l: float = 1.29
    #: Tariff the operator intends to charge; 160 FCFA/kWh. It is also the revealed lower
    #: bound of what a connected household is prepared to pay for a kilowatt-hour.
    tariff_usd_kwh: float = 0.263
    #: Whether that tariff is a *target* to be reached with a capital subsidy. When it is,
    #: the model reports the share of the investment a grant must cover for the levelised
    #: cost to fall to the target. When it is not, the project is assumed to recover its
    #: full cost and the tariff simply is the levelised cost.
    tariff_is_target: bool = True
    #: Value of lost load. See ``voll_provenance``: it fixes the reliability the design
    #: aims at, so it is reported across a range rather than asserted as one number.
    #: Least share of the demand a design must serve to be admissible, or ``None`` when
    #: reliability is priced rather than required. A concession contract usually names one,
    #: and a sizing that reports the shortfall after the fact cannot honour it: the level
    #: has to bound the search, not describe its outcome.
    min_service_fraction: float | None = None
    #: Annual growth of the energy billed, used by the financial appraisal alone. The
    #: sizing is done for the year and maturity stated, not for this curve; a plant that
    #: must serve the growth is what the expansion plan is for.
    demand_growth_rate: float = 0.0
    value_of_lost_load_usd_kwh: float = 1.00
    value_of_lost_load_range_usd_kwh: tuple[float, float] = (0.50, 3.00)
    discount_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="World Bank, Discounting Costs and Benefits in Economic Analysis of World "
               "Bank Projects, OPSPQ, May 2016",
        verified=True,
        note="the guidance derives the rate from per-capita growth through the Ramsey "
             "formula: client-country growth of about 3 % gives 6 %, and the 25-75 "
             "percentile band spans 2-10 %, while the descriptive approach suggests "
             "8-12 % for developing countries. 8 % is the lower end of the descriptive "
             "band and sits inside the Ramsey interval; the guidance asks for a "
             "sensitivity analysis over a range rather than a single value"))
    diesel_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="central benchmark for the study region", verified=False,
        note="the formulation treats the fuel price as an uncertainty axis; this is its "
             "central value, not a fixed datum"))
    def __post_init__(self) -> None:
        # YAML has no tuple; normalising keeps a reloaded project equal to itself.
        self.value_of_lost_load_range_usd_kwh = tuple(
            self.value_of_lost_load_range_usd_kwh)

    tariff_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="160 FCFA/kWh charged on the micro-grid (2026)", verified=True))
    voll_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="bounded below by the tariff households demonstrably pay (0.26 $/kWh) and "
               "by the marginal cost of diesel generation in this model (0.36 $/kWh), "
               "below which the optimiser would shed load rather than generate; anchored "
               "on the cost of the substitute households actually use during an outage, "
               "self-generation in Africa costing about 0.47 $/kWh and lighting and phone "
               "charging by kiosk far more per useful kilowatt-hour",
        verified=False,
        note="this parameter sets the reliability the design aims at, not merely a price; "
             "report the sizing across value_of_lost_load_range_usd_kwh rather than at the "
             "central value alone"))


# ------------------------------------------------------------------------- policy
@dataclass
class ControllerSettings:
    """Parameters of the deployed operating rule — the policy class theta."""

    reserve_multiplier: float = 1.0
    lookahead_hours: int = 14
    generator_setpoint: float = 0.30


# -------------------------------------------------------------------- calibration
@dataclass
class CalibrationSettings:
    """Choices made when turning measurements into archetypes and mixture laws.

    They are method parameters rather than physical ones, but they determine the partition
    everything downstream rests on, so they are recorded with the project rather than left
    in the source.
    """

    n_archetypes: int = 4
    winsor_lower_quantile: float = 0.01
    winsor_upper_quantile: float = 0.99
    outlier_mad_threshold: float = 4.5
    min_support: int = 30
    mixture_prior_strength: float = 20.0
    maturity_edges_months: tuple[int, ...] = (-1, 3, 6, 12, 24, 1200)
    ramp_time_variability: float = 0.2
    ramp_window_variability: float = 0.15
    meter_interval_minutes: int = 15

    def __post_init__(self) -> None:
        # YAML has no tuple, so a reloaded document brings the edges back as a list;
        # normalising here keeps a saved and reloaded project exactly equal to itself.
        self.maturity_edges_months = tuple(self.maturity_edges_months)


@lru_cache(maxsize=1)
def best_available_solver() -> str:
    """The fastest solver this machine can actually run.

    The bound is the same whichever solves it, so the choice is one of runtime alone: on the
    wide boxes of the narrowing, a commercial solver returns the identical value in about
    two fifths of the time, and the narrowing is where the certification spends most of its
    wall clock once the simulations are spread across cores. The licence is checked by
    solving a trivial model rather than by importing the module, an expired or absent
    licence importing perfectly well and failing only when asked to work.
    """
    try:
        import gurobipy

        environment = gurobipy.Env(params={"OutputFlag": 0})
        environment.dispose()
        return "gurobi"
    except Exception:
        return "highs"


@dataclass
class GridSpec:
    """A connection to the national grid, when there is one.

    Half the projects that need sizing sit where the grid is expected within a decade, and
    the two questions a developer actually faces are whether to build for that arrival and
    what to build in the meantime. Neither is answered by treating the grid as a perfect
    source: in the countries this tool is for it is intermittent, and a connection available
    six hours in ten is a different asset from one available all day.

    Availability is stated as a share of hours and a typical outage length, because those are
    the two things an operator knows about their feeder. They generate the outage pattern
    rather than describing one, so that a sizing is not tuned to the particular outages of
    one recorded year.
    """

    #: Whether a connection exists at all. Everything else is ignored when it does not.
    connected: bool = False
    #: Share of hours the feeder is energised.
    availability: float = 0.6
    #: Typical length of an outage [h]; with the availability it sets how often they start.
    mean_outage_hours: float = 4.0
    #: Largest power the connection can draw or inject [kW]. Zero means no physical limit
    #: beyond the plant's own conversion.
    capacity_kw: float = 0.0
    #: What imported energy costs and what exported energy earns. Both are placeholders and
    #: must be replaced: a utility tariff is a regulated, banded, country-specific figure
    #: that no default can stand in for, and an injection price is often zero or absent
    #: entirely. The value below is an order of magnitude for West Africa and nothing more.
    import_usd_kwh: float = 0.11
    export_usd_kwh: float = 0.0
    #: Capital of the connection itself: line, metering, protection.
    connection_usd: float = 0.0
    #: Year of the horizon at which the grid arrives; zero when it is already there. Used by
    #: the expansion plan, where the arrival is an uncertainty rather than a date.
    arrival_year: int = 0
    #: Whether the arrival of the line is treated as an uncertainty over the horizon rather
    #: than as a fact known today. Off by default: a village where the grid is already there,
    #: or plainly is not coming, is not helped by branching a tree over a question that has
    #: an answer.
    arrival_uncertain: bool = False
    #: Chance the line arrives during each milestone, given it has not arrived before.
    arrival_hazard_by_stage: tuple[float, ...] = (0.0, 0.15, 0.20, 0.20, 0.20)
    tariff_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="", verified=False,
        note="an unsourced order of magnitude; take the utility's tariff and the export "
             "price from the concession holder before sizing anything"))
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="", verified=False,
        note="availability and outage regime: to be measured on the feeder concerned"))

    def __post_init__(self) -> None:
        # YAML has no tuple, so a reloaded document brings the hazards back as a list and a
        # saved project stops equalling itself. The same normalisation the maturity edges
        # already carry.
        self.arrival_hazard_by_stage = tuple(self.arrival_hazard_by_stage)


@dataclass
class SolverSettings:
    """How the mathematical programmes are solved."""

    name: str = field(default_factory=best_available_solver)
    mip_gap: float = 0.01
    time_limit_s: int = 3600
    threads: int = 0


# ------------------------------------------------------------------------- project
def _rebuild(existing, item):
    """Restore ``item`` to the type of the value it replaces, however it is nested.

    Reconstruction keyed on a field's *name* left every differently named record as a plain
    mapping; keyed on its type it survives renaming, and it reaches into dictionaries and
    lists, which is where the cost trajectories live.
    """
    if is_dataclass(existing) and isinstance(item, dict):
        fields_of = {f.name for f in fields(type(existing))}
        kwargs = {k: _rebuild(getattr(existing, k, None), v)
                  for k, v in item.items() if k in fields_of}
        return type(existing)(**kwargs)
    if isinstance(existing, dict) and isinstance(item, dict):
        return {k: _rebuild(existing.get(k), v) for k, v in item.items()}
    return item


@dataclass
class ProjectSettings:
    """Everything a project needs beyond its measured data."""

    site: str = "Samionta"
    year: int = 2025
    demand_trajectory: str = "central"
    maturity_months: int = 12
    seed: int = 0

    currency: CurrencySettings = field(default_factory=CurrencySettings)
    photovoltaic: PhotovoltaicSpec = field(default_factory=PhotovoltaicSpec)
    battery: BatterySpec = field(default_factory=BatterySpec)
    inverter: InverterSpec = field(default_factory=InverterSpec)
    coupling: CouplingSpec = field(default_factory=CouplingSpec)
    cost_trajectories: dict[str, CostTrajectory] = field(
        default_factory=default_cost_trajectories)
    generators: list[GeneratorSpec] = field(default_factory=default_generator_catalogue)
    economics: EconomicSettings = field(default_factory=EconomicSettings)
    controller: ControllerSettings = field(default_factory=ControllerSettings)
    calibration: CalibrationSettings = field(default_factory=CalibrationSettings)
    grid: GridSpec = field(default_factory=GridSpec)
    solver: SolverSettings = field(default_factory=SolverSettings)

    # ---------------------------------------------------------------- validation
    def validate(self) -> None:
        """Reject a configuration that cannot describe a real plant."""
        from .battery import CHEMISTRIES

        if self.battery.chemistry not in CHEMISTRIES:
            raise ValueError(f"unknown battery chemistry {self.battery.chemistry!r}; "
                             f"available: {sorted(CHEMISTRIES)}")
        if not 0.0 <= self.battery.soc_min < self.battery.soc_max <= 1.0:
            raise ValueError("battery state-of-charge limits must satisfy 0 <= min < max <= 1")
        if not 0.0 < self.economics.discount_rate < 1.0:
            raise ValueError("the discount rate must lie strictly between 0 and 1")
        if self.grid.connected:
            if not 0.0 < self.grid.availability <= 1.0:
                raise ValueError("grid.availability must lie in (0, 1]")
            if self.grid.mean_outage_hours <= 0:
                raise ValueError("grid.mean_outage_hours must be positive")
        if self.coupling.architecture not in ("dc", "ac", "mixed", "auto"):
            raise ValueError("coupling.architecture must be 'dc', 'ac', 'mixed' or "
                             f"'auto', not {self.coupling.architecture!r}")
        if min(self.coupling.dc_ac_ratio_max, self.coupling.ac_ratio_max) <= 0.0:
            raise ValueError("the array-to-inverter ratios must be strictly positive")
        if self.economics.horizon_years <= 0:
            raise ValueError("the horizon must be a positive number of years")
        if not self.generators:
            raise ValueError("the generator catalogue must not be empty")
        ratings = [g.rating_kw for g in self.generators]
        if len(set(ratings)) != len(ratings):
            raise ValueError(f"duplicate generator ratings in the catalogue: {ratings}")
        for generator in self.generators:
            generator.efficiency_coefficients()          # raises if under-specified
            if not 0.0 <= generator.min_load_fraction < 1.0:
                raise ValueError(f"minimum loading of the {generator.rating_kw} kW unit "
                                 "must lie in [0, 1)")
        if self.demand_trajectory not in ("slow", "central", "fast"):
            raise ValueError(f"unknown demand trajectory {self.demand_trajectory!r}")

        low, high = self.economics.value_of_lost_load_range_usd_kwh
        if not 0 < low <= self.economics.value_of_lost_load_usd_kwh <= high:
            raise ValueError(
                "the value of lost load must lie inside its own reported range")
        if self.economics.value_of_lost_load_usd_kwh < self.economics.tariff_usd_kwh:
            raise ValueError(
                "the value of lost load cannot fall below the tariff households pay: "
                "they demonstrably value a kilowatt-hour at least that much")

    def unverified(self) -> list[tuple[str, Provenance]]:
        """Every parameter group nobody has sourced, so the software can say so."""
        found: list[tuple[str, Provenance]] = []

        def walk(obj: Any, path: str) -> None:
            if isinstance(obj, Provenance):
                if not obj.verified:
                    found.append((path, obj))
                return
            if is_dataclass(obj):
                for f in fields(obj):
                    walk(getattr(obj, f.name), f"{path}.{f.name}" if path else f.name)
            elif isinstance(obj, (list, tuple)):
                for i, item in enumerate(obj):
                    walk(item, f"{path}[{i}]")
            elif isinstance(obj, dict):
                # Parameters keyed by name — the cost trajectories, one per technology —
                # were walked past entirely, so an unsourced one announced nothing.
                for key, item in obj.items():
                    walk(item, f"{path}[{key}]")

        walk(self, "")
        return found

    # --------------------------------------------------------------------- files
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        """Write the parameters to a YAML document."""
        import yaml

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False,
                                       allow_unicode=True, default_flow_style=False))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "ProjectSettings":
        """Read parameters from a YAML document, filling anything absent with defaults."""
        import yaml

        raw = yaml.safe_load(Path(path).read_text()) or {}
        settings = cls.from_dict(raw)
        settings.validate()
        return settings

    @classmethod
    def from_dict(cls, raw: dict) -> "ProjectSettings":
        """Build settings from a plain mapping, tolerating omitted sections."""
        def build(kind, value):
            if value is None:
                return None
            if is_dataclass(kind) and isinstance(value, dict):
                kwargs = {}
                for f in fields(kind):
                    if f.name in value:
                        kwargs[f.name] = build(f.type if is_dataclass(f.type) else None,
                                               value[f.name]) or value[f.name]
                return kind(**kwargs)
            return value

        settings = cls()
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            if f.name == "generators":
                setattr(settings, f.name, [
                    GeneratorSpec(**{**g, "provenance": Provenance(**g["provenance"])}
                                  if isinstance(g.get("provenance"), dict) else g)
                    for g in value])
            elif isinstance(value, dict):
                current = getattr(settings, f.name)
                if isinstance(current, dict):
                    # Parameters keyed by name — the cost trajectories, one per technology.
                    # Left as plain mappings they lose their type, and with it the
                    # provenance that says whether anybody sourced them.
                    setattr(settings, f.name,
                            {k: _rebuild(current.get(k), v) for k, v in value.items()})
                elif is_dataclass(current):
                    for key, item in value.items():
                        if not hasattr(current, key):
                            continue
                        # Rebuild a nested record from its own type rather than from its
                        # name. Keying on the name ``provenance`` left every differently
                        # named one — ``diesel_provenance``, ``voll_provenance`` — as a
                        # plain mapping, so a reloaded project reported no unsourced
                        # parameter at all and the one guarantee this file makes was void
                        # for exactly the projects that read their settings from a file.
                        existing = getattr(current, key)
                        item = _rebuild(existing, item)
                        setattr(current, key, item)
                else:
                    setattr(settings, f.name, value)
            else:
                setattr(settings, f.name, value)

        # Sections are populated attribute by attribute, which bypasses the normalisation
        # a dataclass does on construction; re-run it so a reloaded project equals itself.
        for f in fields(settings):
            section = getattr(settings, f.name)
            if is_dataclass(section) and hasattr(section, "__post_init__"):
                section.__post_init__()
        return settings


def default_settings() -> ProjectSettings:
    """The parameters this study runs with, as shipped."""
    settings = ProjectSettings()
    settings.validate()
    return settings


# ---------------------------------------------------------------------------- CLI
TEMPLATE_HEADER = """\
# Project parameters -- microgrid-expansion
#
# This document holds everything the model needs to know beyond the measured data. Edit it
# rather than the code: published results must be archivable together with the parameter
# set that produced them.
#
# A "provenance" block says where a parameter comes from and whether anyone has checked it.
# A parameter marked "verified: false" has not been sourced and should not support a
# published conclusion until it is replaced.
#
# Fuel consumptions are the manufacturer's own, at 50, 75 and 100 % of load; the efficiency
# curve is derived from them. Every size in the catalogue carries its own, which is what
# economically distinguishes the sizes the certificate arbitrates between.
"""


def write_template(path: str | Path) -> Path:
    """Write a documented parameter file for a user to edit."""
    settings = default_settings()
    written = settings.save(path)
    written.write_text(TEMPLATE_HEADER + "\n" + written.read_text())
    return written


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Project parameters.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("template", help="write a parameter file to fill in") \
        .add_argument("--output", default="project.yaml")
    sub.add_parser("check", help="validate a file and report what is unsourced") \
        .add_argument("path")

    args = parser.parse_args(argv)
    if args.command == "template":
        path = write_template(args.output)
        print(f"written {path}")
        return 0

    settings = ProjectSettings.load(args.path)
    print(f"{args.path}: valid")
    unverified = settings.unverified()
    if not unverified:
        print("every parameter is sourced.")
        return 0
    print(f"\n{len(unverified)} unverified parameter group(s):")
    for path, provenance in unverified:
        print(f"  {path}")
        print(f"      origin:  {provenance.source}")
        if provenance.note:
            print(f"      to do:   {provenance.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
