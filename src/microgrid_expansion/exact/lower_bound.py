"""Cost-optimal dispatch over a capacity box — the lower-bound oracle.

Solves the operating problem to optimality with the capacities themselves free within a
box, which is the relaxation Proposition 1 licenses: relaxing integrality enlarges the
admissible set and replacing the rule-based operating cost by the cost-optimal one lowers
the objective, so the value returned underestimates the best rule-based sizing anywhere in
the box. That is what makes it a pruning bound.

**The fuel model must underestimate too.** The controller burns fuel according to an
efficiency that varies quadratically with part load, which no linear programme can express.
A linear fuel curve is therefore fitted as a *minorant* of the true consumption over the
operating range rather than as a fit through it: on that range the true consumption is
convex, so the tangent parallel to the chord lies below it everywhere and touches at about
three-quarters of the rating, where a generator normally runs. Using a least-squares fit or
the chord instead would overestimate consumption at some outputs and could raise the bound
above the true optimum, which would let branch-and-simulate prune the optimal design.

Two modes are exposed. Relaxing the commitment binary gives a cheaper and looser bound;
keeping it integral gives a tighter one at a higher cost. Both are valid.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import config
from ..instances import SiteYear
from .simulator import BatteryModel, Capacities, GeneratorModel


@dataclass(frozen=True)
class CapacityBox:
    """Box of admissible capacities. A degenerate box pins the design to a point."""

    pv_kw: tuple[float, float]
    battery_kwh: tuple[float, float]
    inverter_kw: tuple[float, float]
    generator_kw: tuple[float, float]
    #: Field on string inverters, feeding the load's bus.
    pv_ac_kw: tuple[float, float] = (0.0, 0.0)
    #: Bounds on the whole field, both buses together. Supplied when the search fixes the
    #: total and leaves the split to be resolved: the relaxation is then free to divide it,
    #: which relaxes the rule the search applies and therefore still minorises it.
    pv_total_kw: tuple[float, float] | None = None
    #: Where the array joins the plant. A box spans capacities, never architectures: the
    #: two impose different constraints, so a box holding both could not be bounded by one
    #: linear programme. The search enumerates them separately.
    architecture: str = "dc"

    @classmethod
    def at(cls, capacities: Capacities) -> "CapacityBox":
        """The degenerate box at one design point."""
        return cls(pv_kw=(capacities.pv_kw, capacities.pv_kw),
                   battery_kwh=(capacities.battery_kwh, capacities.battery_kwh),
                   inverter_kw=(capacities.inverter_kw, capacities.inverter_kw),
                   generator_kw=(capacities.generator_kw, capacities.generator_kw),
                   pv_ac_kw=(capacities.pv_ac_kw, capacities.pv_ac_kw),
                   architecture=capacities.architecture)


@dataclass(frozen=True)
class Economics:
    """Annualised cost of capacity and the unit costs of operation."""

    crf: float = None                      # capital recovery factor
    pv_usd_kw: float = config.PV_COST_USD_KW
    battery_usd_kwh: float = config.BATT_COST_USD_KWH
    inverter_usd_kw: float = config.INV_COST_USD_KW
    generator_usd_kw: float = config.GEN_COST_USD_KVA
    om_rates: tuple[float, float, float, float] = (
        config.PV_OM_RATE, config.BATT_OM_RATE, config.INV_OM_RATE, config.GEN_OM_RATE)
    #: Service life of each asset [years], in the same order. Each is annualised over its
    #: own life rather than the project's, which is what charges an asset for the
    #: replacements it will need. Annualising a ten-year inverter at a twenty-five-year
    #: factor makes it look some two-fifths cheaper than it is and biases the optimum
    #: towards conversion capacity the project would in truth have to buy twice.
    lifetimes: tuple[int, int, int, int] = (
        config.PV_LIFETIME_Y, config.BATT_LIFETIME_Y,
        config.INV_LIFETIME_Y, config.GEN_LIFETIME_Y)
    #: Photovoltaic-side conversion, per kilowatt of array. It is proportional to the array
    #: and so is folded into the array's own coefficient rather than carried as a fifth
    #: dimension the search would have to explore for nothing.
    conversion_usd_kw: float = 0.0
    #: String inverters, bought per kilowatt of field placed on the load's bus.
    string_inverter_usd_kw: float = config.CONV_STRING_USD_KW
    conversion_om_rate: float = config.CONV_OM_RATE
    conversion_lifetime_y: int = config.CONV_LIFETIME_Y
    fuel_usd_l: float = config.DIESEL_PRICE_USD_L
    degradation_usd_kwh: float = None
    voll_usd_kwh: float = config.VOLL_USD_KWH
    #: Least share of demand a design must serve; ``None`` when reliability is only priced.
    #: Carried here so the rule oracle can reject what the contract forbids.
    min_service_fraction: float | None = None
    #: Annualised capital of the connection to the national grid, when there is one. A cost
    #: the plant carries whatever it dispatches, so it belongs beside the other capitals.
    grid_connection_usd_yr: float = 0.0
    #: What imported energy costs and what exported energy earns, per kilowatt-hour.
    grid_import_usd_kwh: float = 0.0
    grid_export_usd_kwh: float = 0.0
    #: Annualised capital of everything between the plant and the customer -- network,
    #: connections, civil works, development. It does not depend on the design, so it moves
    #: every cost by the same amount and leaves the ranking, and the certificate, untouched.
    #: It moves the tariff and the subsidy, which is what the project is judged on.
    infrastructure_usd_yr: float = 0.0

    #: The rate every annuity here is computed at. It belongs to the project, and the field
    #: exists because this object is what the certification carries its prices in: read from
    #: ``config`` instead, as the methods below did, a project at twelve per cent recovered
    #: its plant at eight and nothing said so.
    discount_rate: float = config.DISCOUNT_RATE

    def __post_init__(self) -> None:
        if self.crf is None:
            object.__setattr__(self, "crf", config.crf(self.discount_rate))
        if self.degradation_usd_kwh is None:
            object.__setattr__(self, "degradation_usd_kwh",
                               config.battery_degradation_cost())

    #: The storage pack, needed to work out which of its two lives ends it. Left unset the
    #: calendar life is used, which is the relaxation the lower bound wants.
    battery_spec: object | None = None

    #: The plant already standing, as ``settings.InstalledPlant`` describes it. ``None`` is
    #: bare ground. It enters the cost twice and in two different ways: what it already
    #: covers is capacity the design does not buy, and what it still owes -- its upkeep and
    #: the replacement its remaining life defers -- is a constant every design carries.
    installed: object | None = None

    @classmethod
    def from_settings(cls, settings, architecture: str = "mixed", **overrides
                      ) -> "Economics":
        """Every price, life and rate of one project, in the form the oracles read.

        The defaults of this dataclass are the defaults of the package, which is only
        acceptable where a production caller replaces them. The certification did not: it
        passed the fuel price, the value of lost load and the balance of plant, and left the
        prices of the equipment, the service lives, the maintenance rates and the discount
        rate to whatever ``config`` had read at import. A project that declared a dearer
        array was certified at the default array.
        """
        generator = max(settings.generators, key=lambda g: g.rating_kw)
        coupling = settings.coupling
        # The plant on the ground belongs to the project like every price here. Left out,
        # a village running since 2024 was certified as bare ground.
        overrides.setdefault("installed", getattr(settings, "installed", None))
        return cls(
            discount_rate=settings.economics.discount_rate,
            pv_usd_kw=settings.photovoltaic.cost_usd_kw,
            battery_usd_kwh=settings.battery.cost_usd_kwh,
            inverter_usd_kw=settings.inverter.cost_usd_kw,
            generator_usd_kw=generator.cost_usd_kw,
            om_rates=(settings.photovoltaic.om_rate, settings.battery.om_rate,
                      settings.inverter.om_rate, generator.om_rate),
            lifetimes=(settings.photovoltaic.lifetime_years,
                       settings.battery.lifetime_years,
                       settings.inverter.lifetime_years,
                       generator.lifetime_years),
            conversion_usd_kw=coupling.cost_usd_kw(architecture),
            string_inverter_usd_kw=coupling.string_inverter_cost_usd_kw,
            conversion_om_rate=coupling.om_rate,
            conversion_lifetime_y=coupling.lifetime_years,
            fuel_usd_l=settings.economics.diesel_price_usd_l,
            voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh,
            **overrides)

    def string_inverter_annualised(self) -> float:
        """Annual cost of one kilowatt of string inverter, capital and maintenance.

        Computed here rather than memoised at module level, as it was. Keyed on nothing, the
        cache held the first project a process certified and served it to every project
        after -- two villages sized one after another, the second priced with the first
        one's converters.
        """
        return self.string_inverter_usd_kw * (
            config.crf(self.discount_rate, self.conversion_lifetime_y)
            + self.conversion_om_rate)

    def battery_annualised(self, capacity_kwh: float = 0.0,
                           annual_discharge_kwh: float = 0.0) -> float:
        """Annualised cost of one kilowatt-hour of storage, on the life that ends it.

        A pack cycled beyond its cycle life is replaced sooner than the calendar says, and
        charging it over the calendar life would understate it. Charging it over both --
        capital on the calendar, wear on the cycles -- is what this replaces, and that
        overstated it by more.
        """
        _, om_batt, _, _ = self.om_rates
        life = self.lifetimes[1]
        if self.battery_spec is not None and capacity_kwh > 0 and annual_discharge_kwh > 0:
            life = self.battery_spec.effective_lifetime_years(capacity_kwh,
                                                              annual_discharge_kwh)
        return self.battery_usd_kwh * (config.crf(self.discount_rate, life) + om_batt)

    # ------------------------------------------------------------ the standing plant
    def _deferred(self, life: float, age_years: float) -> float:
        """Capital recovery factor of an asset whose replacement is deferred by its age.

        A kilowatt is recovered here at the factor of its own service life, and that is
        exactly the annuity of buying it now and replacing it for ever:
        ``crf(r, L) = r / (1 - (1+r)^-L)``. One already standing differs in a single
        respect, that its first replacement falls in ``L - a`` years rather than in ``L``,
        so its annuity is the same one discounted over that deferral. At ``a = L`` the two
        coincide, which is right: an asset at the end of its life has to be bought again,
        and being there is worth nothing. Past its life it is not charged *more* than a new
        one, hence the floor on the remaining years.
        """
        remaining = max(float(life) - float(age_years), 0.0)
        return config.crf(self.discount_rate, life) / (1.0 + self.discount_rate) ** remaining

    def existing_annualised(self, plant=None) -> tuple[float, float, float, float, float]:
        """Annual cost of keeping what already stands, per technology [$/yr].

        In the order the capacities are counted in: array on the battery's bus, storage,
        hybrid inverter, generating set, array on the load's bus. Each vintage is charged
        separately, because neither reference village has a field or a pack of one age, and
        one age for the lot would defer the whole of it by the wrong interval.

        The storage is charged on its calendar life rather than on the life its cycling
        would imply. The wear a standing pack has already taken is not in the model, and
        charging its replacement on the cycling of a plan drawn after it was bought would
        attribute this plan's duty to a pack that was not sized for it.
        """
        plant = self.installed if plant is None else plant
        if plant is None:
            return (0.0, 0.0, 0.0, 0.0, 0.0)
        om_pv, om_batt, om_inv, om_gen = self.om_rates
        life_pv, life_batt, life_inv, life_gen = self.lifetimes
        out = []
        for technology, unit_cost, life, om in (
                ("pv", self.pv_usd_kw, life_pv, om_pv),
                ("battery", self.battery_usd_kwh, life_batt, om_batt),
                ("inverter", self.inverter_usd_kw, life_inv, om_inv),
                ("generator", self.generator_usd_kw, life_gen, om_gen),
                ("pv_ac", self.pv_usd_kw, life_pv, om_pv)):
            total = 0.0
            for vintage in plant.vintages(technology):
                age = plant.age_years(vintage)
                total += vintage.capacity * unit_cost * (self._deferred(life, age) + om)
                if technology == "pv":
                    total += vintage.capacity * self.conversion_usd_kw * (
                        self._deferred(self.conversion_lifetime_y, age)
                        + self.conversion_om_rate)
                elif technology == "pv_ac":
                    total += vintage.capacity * self.string_inverter_usd_kw * (
                        self._deferred(self.conversion_lifetime_y, age)
                        + self.conversion_om_rate)
            out.append(total)
        return tuple(out)

    @property
    def existing_plant_usd_yr(self) -> float:
        """What the standing plant costs a year, whatever the plan decides.

        A constant of the design, like the network and the connections: it shifts every
        cost by the same amount and leaves the ranking, and so the certificate, untouched.
        What moves the optimum is the floor the plant puts under the search, not this.
        """
        return float(sum(self.existing_annualised()))

    def installed_capacity(self, technology: str) -> float:
        """Capacity of one technology already standing, in its own unit."""
        if self.installed is None:
            return 0.0
        return self.installed.capacity(technology)

    def added_capacity(self, capacities) -> tuple[float, float, float, float, float]:
        """What one design buys, over and above what is already there.

        Never negative. A design below the standing plant is not admissible -- the lattice
        puts its floor at what exists -- and clamping here keeps a cost finite rather than
        crediting the project for capacity it would have to remove.
        """
        return (max(capacities.pv_kw - self.installed_capacity("pv"), 0.0),
                max(capacities.battery_kwh - self.installed_capacity("battery"), 0.0),
                max(capacities.inverter_kw - self.installed_capacity("inverter"), 0.0),
                max(capacities.generator_kw - self.installed_capacity("generator"), 0.0),
                max(capacities.pv_ac_kw - self.installed_capacity("pv_ac"), 0.0))

    def annualised(self) -> tuple[float, float, float, float]:
        """Annualised cost of one unit of each capacity, capital plus maintenance.

        Each asset is recovered over its own service life, so that a short-lived one is
        charged for the replacements it requires. The photovoltaic coefficient carries the
        conversion equipment on top of the modules, that equipment being sized to the array.
        """
        om_pv, om_batt, om_inv, om_gen = self.om_rates
        life_pv, life_batt, life_inv, life_gen = self.lifetimes
        rate = self.discount_rate
        return (self.pv_usd_kw * (config.crf(rate, life_pv) + om_pv)
                + self.conversion_usd_kw * (config.crf(rate, self.conversion_lifetime_y)
                                            + self.conversion_om_rate),
                self.battery_usd_kwh * (config.crf(rate, life_batt) + om_batt),
                self.inverter_usd_kw * (config.crf(rate, life_inv) + om_inv),
                self.generator_usd_kw * (config.crf(rate, life_gen) + om_gen))


def catalogue_fuel_minorant(generator: GeneratorModel,
                            rating_range: tuple[float, float]) -> tuple[float, float]:
    """A fuel line below every catalogue unit the box allows.

    Falls back to the supplied model when no catalogue unit falls inside the range, which
    is the degenerate case of a box pinned to a rating the project does not stock.
    """
    from ..settings import default_settings

    low, high = rating_range
    intercepts, slopes = [], []
    for spec in default_settings().generators:
        if not (low - 1e-9 <= spec.rating_kw <= high + 1e-9):
            continue
        unit = GeneratorModel.from_spec(spec, generator.fuel_price_usd_l)
        intercept, slope = fuel_minorant(unit, spec.rating_kw)
        intercepts.append(intercept)
        slopes.append(slope)
    if not intercepts:
        return fuel_minorant(generator, high if high > 0 else 1.0)
    return min(intercepts), min(slopes)


def fuel_minorant(generator: GeneratorModel, rating_kw: float) -> tuple[float, float]:
    """Linear fuel curve ``F0 + F1 p`` lying below the true consumption [L/h, L/kWh].

    On the operating range the true consumption is convex, so the affine minorant with the
    smallest maximum gap is the tangent parallel to the chord. Its intercept is the exact
    minimum of ``fuel(p) - slope x p`` over the range, found by numerical minimisation
    rather than by sampling: a minorant that holds only at the sampled points is not a
    minorant, and a fuel model above the truth could raise the bound above the optimum it
    is supposed to bound.
    """
    if rating_kw <= 0:
        return 0.0, 0.0
    from scipy.optimize import minimize_scalar

    lo = generator.min_load_fraction * rating_kw
    hi = rating_kw
    fuel_lo = float(generator.fuel_litres(lo, rating_kw))
    fuel_hi = float(generator.fuel_litres(hi, rating_kw))
    slope = (fuel_hi - fuel_lo) / (hi - lo)

    gap = lambda p: float(generator.fuel_litres(p, rating_kw)) - slope * p
    result = minimize_scalar(gap, bounds=(lo, hi), method="bounded",
                             options={"xatol": 1e-10})
    intercept = float(result.fun)
    return intercept, float(slope)


@dataclass
class LowerBound:
    """Value of the relaxation over a box, and the design that attains it."""

    value: float
    capacities: Capacities
    operating_cost: float
    capital_cost: float
    relaxed_commitment: bool
    status: str


def cost_optimal_dispatch(
    instance: SiteYear,
    box: CapacityBox,
    economics: Economics = Economics(),
    battery: BatteryModel = BatteryModel(),
    generator: GeneratorModel = GeneratorModel(),
    relax_commitment: bool = True,
    weights: np.ndarray | None = None,
    solver: str | None = None,
    terminal: str = "free",
    initial_soc_fraction: float | None = None,
    integer_units: tuple[float, float, float] | None = None,
    generator_ratings: tuple[float, ...] | None = None,
    threads: int | None = None,
    grid=None,
    coupling=None,
) -> LowerBound:
    """Minimise annualised total cost over the box and return the bound.

    ``terminal`` governs the storage boundary condition, and the choice bears directly on
    whether the result is a valid bound. A *causal* controller ends the horizon wherever
    its decisions leave it, generally poorer than it started; requiring the relaxation to
    close its cycle would constrain it where the controller is not constrained, and the
    relaxation could then exceed the very quantity it is supposed to bound — which is
    observed, and worth up to fifteen per cent of the operating cost over a week. Leaving
    the terminal state ``"free"`` keeps every controller trajectory admissible and the bound
    valid. ``"cyclic"`` reproduces the representative-day closure of the formulation and is
    tighter, but is only comparable with a controller run under the same closure.
    """
    import linopy
    import xarray as xr

    if coupling is None:
        from ..settings import default_settings

        coupling = default_settings().coupling
    demand = instance.demand_kw
    n = demand.size
    weights = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    steps = np.arange(n)

    big_m = box.generator_kw[1]
    # A box may span several catalogue ratings, and the relaxation is free to choose among
    # them. Its fuel model must therefore lie below every one of them: taking the minorant
    # of a single unit and applying it to a design that installs another charges an
    # efficiency that was never bought — a quarter of a litre per kilowatt-hour separates
    # the ends of this catalogue — and the bound then stops bounding.
    fuel_0, fuel_1 = catalogue_fuel_minorant(generator, box.generator_kw)
    a_pv, a_batt, a_inv, a_gen = economics.annualised()
    a_pv_ac = a_pv + economics.string_inverter_annualised()

    m = linopy.Model()
    if integer_units is None:
        cap_pv = m.add_variables(lower=box.pv_kw[0], upper=box.pv_kw[1], name="cap_pv")
        cap_pv_ac = m.add_variables(lower=box.pv_ac_kw[0], upper=box.pv_ac_kw[1],
                                    name="cap_pv_ac")
        cap_batt = m.add_variables(lower=box.battery_kwh[0], upper=box.battery_kwh[1],
                                   name="cap_batt")
        cap_inv = m.add_variables(lower=box.inverter_kw[0], upper=box.inverter_kw[1],
                                  name="cap_inv")
        cap_gen = m.add_variables(lower=box.generator_kw[0], upper=box.generator_kw[1],
                                  name="cap_gen")
    else:
        # Capacities restricted to the lattice itself. Declaring them integer and handing
        # the catalogue to the solver as a selection is the whole of the integer search:
        # relaxing and then rounding by hand is doing badly, and outside any guarantee,
        # what a mixed-integer solver does exactly — and it was returning designs a
        # hundred dollars a year worse than the true lattice optimum, enough to reverse
        # the sign of the very quantity this study exists to measure.
        pv_unit, batt_unit, inv_unit = integer_units
        n_pv = m.add_variables(lower=int(round(box.pv_kw[0] / pv_unit)),
                               upper=int(round(box.pv_kw[1] / pv_unit)),
                               integer=True, name="n_pv")
        n_batt = m.add_variables(lower=int(round(box.battery_kwh[0] / batt_unit)),
                                 upper=int(round(box.battery_kwh[1] / batt_unit)),
                                 integer=True, name="n_batt")
        n_inv = m.add_variables(lower=int(round(box.inverter_kw[0] / inv_unit)),
                                upper=int(round(box.inverter_kw[1] / inv_unit)),
                                integer=True, name="n_inv")
        n_pv_ac = m.add_variables(lower=int(round(box.pv_ac_kw[0] / pv_unit)),
                                  upper=int(round(box.pv_ac_kw[1] / pv_unit)),
                                  integer=True, name="n_pv_ac")
        cap_pv, cap_batt, cap_inv = n_pv * pv_unit, n_batt * batt_unit, n_inv * inv_unit
        cap_pv_ac = n_pv_ac * pv_unit
        ratings = tuple(generator_ratings or (box.generator_kw[1],))
        choose = m.add_variables(coords={"unit": np.arange(len(ratings))},
                                 binary=True, name="choose")
        m.add_constraints(choose.sum() == 1, name="one_generator")
        cap_gen = sum(float(r) * choose.sel(unit=k) for k, r in enumerate(ratings))

    coords = {"step": steps}
    as_series = lambda values: xr.DataArray(np.asarray(values, dtype=float),
                                            coords=coords, dims="step")
    p_gen = m.add_variables(lower=0.0, coords=coords, name="p_gen")
    p_ch = m.add_variables(lower=0.0, coords=coords, name="p_ch")
    p_dis = m.add_variables(lower=0.0, coords=coords, name="p_dis")
    curtail = m.add_variables(lower=0.0, coords=coords, name="curtail")
    unserved = m.add_variables(lower=0.0, upper=demand, coords=coords, name="unserved")
    # Each source is split by destination. The aggregated balance could not express which
    # flows cross the hybrid inverter, and that is precisely what the two architectures
    # disagree about: under direct-current coupling the array reaches the load through it
    # and the battery around it, under alternating-current coupling the reverse.
    pv_load = m.add_variables(lower=0.0, coords=coords, name="pv_load")
    pv_batt = m.add_variables(lower=0.0, coords=coords, name="pv_batt")
    ac_load = m.add_variables(lower=0.0, coords=coords, name="ac_load")
    ac_batt = m.add_variables(lower=0.0, coords=coords, name="ac_batt")
    ac_curtail = m.add_variables(lower=0.0, coords=coords, name="ac_curtail")
    gen_load = m.add_variables(lower=0.0, coords=coords, name="gen_load")
    gen_batt = m.add_variables(lower=0.0, coords=coords, name="gen_batt")
    soc = m.add_variables(lower=0.0, coords={"step": np.arange(n + 1)}, name="soc")
    # linopy refuses bounds on a binary variable, so the two modes are declared apart:
    # relaxed, the commitment is a continuous fraction of an hour; tight, it is integral.
    if relax_commitment:
        commit = m.add_variables(lower=0.0, upper=1.0, coords=coords, name="commit")
    else:
        commit = m.add_variables(coords=coords, name="commit", binary=True)

    yield_ = as_series(instance.specific_yield)
    # Every kilowatt the array produces goes to the load, to the battery, or nowhere.
    m.add_constraints(pv_load + pv_batt + curtail - yield_ * cap_pv == 0, name="pv_split")
    m.add_constraints(ac_load + ac_batt + ac_curtail - yield_ * cap_pv_ac == 0,
                      name="pv_ac_split")
    # The generator likewise; what it cannot place is burnt for nothing.
    gen_curtail = m.add_variables(lower=0.0, coords=coords, name="gen_curtail")
    m.add_constraints(gen_load + gen_batt + gen_curtail - p_gen == 0, name="gen_split")
    # The battery is charged from one or the other.
    m.add_constraints(p_ch - pv_batt - ac_batt - gen_batt == 0, name="charge_split")
    # What reaches the load.
    # The national grid, when the plant has one. It must be here and not only in the
    # simulation: the controller can import cheaply, so a relaxation that cannot would price
    # the plant above what the controller achieves and stop being a lower bound at all. It
    # did, once -- the anticipative optimum came out four thousand dollars a year above the
    # rule it is meant to minorise, and the reported price of the heuristic went negative.
    if grid is not None and grid.available is not None:
        live = np.asarray(grid.available, dtype=float)[:steps.size]
        room = (float(grid.capacity_kw) if grid.capacity_kw > 0
                else float(np.max(np.asarray(demand, dtype=float))) * 2.0)
        grid_load = m.add_variables(lower=0.0, upper=live * room, coords=coords,
                                    name="grid_load")
        grid_export = m.add_variables(lower=0.0, upper=live * room, coords=coords,
                                      name="grid_export")
        m.add_constraints(grid_export - curtail - ac_curtail <= 0, name="export_from_spill")
    else:
        grid_load = None
        grid_export = None

    load_sources = pv_load + ac_load + gen_load + p_dis + unserved
    if grid_load is not None:
        load_sources = load_sources + grid_load
    m.add_constraints(load_sources == as_series(demand), name="balance")

    # A required service level binds both oracles or neither. Imposed on the controller
    # alone -- which is where it first went -- it raised the cost of the rule without
    # raising the cost of perfect anticipation, and the difference between them, which this
    # work reports as the price of the heuristic, silently absorbed the price of a
    # contractual requirement instead. On the reference instance that was one point in three
    # of a gap of eight.
    if economics.min_service_fraction is not None:
        total_demand = float(np.asarray(demand, dtype=float).sum())
        allowance = (1.0 - economics.min_service_fraction) * total_demand
        m.add_constraints(unserved.sum() <= allowance, name="service_floor")

    # generator
    m.add_constraints(p_gen - cap_gen <= 0, name="gen_rating")
    m.add_constraints(p_gen - big_m * commit <= 0, name="gen_commit")
    m.add_constraints(
        p_gen - generator.min_load_fraction * cap_gen + big_m * (1 - commit) >= 0,
        name="gen_min_load")

    # storage
    retention = as_series(1.0 - np.clip(instance.self_discharge, 0.0, 1.0))
    # The recursion couples consecutive steps, so both ends are re-indexed onto a common
    # axis before being combined; linopy aligns expressions by coordinate.
    soc_next = soc.isel(step=slice(1, None)).assign_coords(step=steps)
    soc_prev = soc.isel(step=slice(0, n)).assign_coords(step=steps)
    # Array energy stored across the alternating bus is converted twice; generator energy
    # is rectified once whichever bus it crosses. The two charging streams therefore do not
    # share an efficiency, and the relaxation must apply the same penalty as the controller
    # or it would minorise a plant with better storage than the one being certified.
    eta_ac = battery.charge_efficiency * coupling.ac_double_conversion_efficiency
    m.add_constraints(
        soc_next - retention * soc_prev
        - battery.charge_efficiency * (pv_batt + gen_batt) - eta_ac * ac_batt
        + (1.0 / battery.discharge_efficiency) * p_dis == 0,
        name="soc_dynamics")
    if terminal == "cyclic":
        m.add_constraints(soc.isel(step=0) - soc.isel(step=n) == 0, name="soc_cyclic")
    elif terminal != "free":
        raise ValueError(f"terminal must be 'free' or 'cyclic', not {terminal!r}")
    if initial_soc_fraction is not None:
        m.add_constraints(
            soc.isel(step=0) - initial_soc_fraction * battery.soc_max * cap_batt == 0,
            name="soc_initial")
    ceiling = xr.DataArray(
        battery.soc_max * np.concatenate([instance.usable_fraction,
                                          instance.usable_fraction[-1:]]),
        coords={"step": np.arange(n + 1)}, dims="step")
    m.add_constraints(soc - ceiling * cap_batt <= 0, name="soc_upper")
    m.add_constraints(soc - battery.soc_min * cap_batt >= 0, name="soc_lower")
    # The hybrid inverter carries what the field on the battery's bus sends the load, every
    # discharge, and everything rectified into storage from the load's bus. A field on the
    # load's bus reaches that load without crossing it.
    m.add_constraints(pv_load + p_dis + gen_batt + ac_batt - cap_inv <= 0,
                      name="inverter_rating")
    # Each part of the array is limited by its own converter, and for different reasons: the
    # trackers integrated in the hybrid inverter accept a bounded field per unit of rating,
    # and a field on the load's bus must be absorbable by the battery inverter the instant
    # the load falls away. Neither part is enlarged without buying the conversion it needs.
    m.add_constraints(cap_pv - coupling.dc_ac_ratio_max * cap_inv <= 0,
                      name="array_ratio_dc")
    m.add_constraints(cap_pv_ac - coupling.ac_ratio_max * cap_inv <= 0,
                      name="array_ratio_ac")
    if box.pv_total_kw is not None:
        low, high = box.pv_total_kw
        m.add_constraints(cap_pv + cap_pv_ac - high <= 0, name="field_upper")
        m.add_constraints(cap_pv + cap_pv_ac - low >= 0, name="field_lower")
    m.add_constraints(p_ch - battery.c_rate * cap_batt <= 0, name="charge_rate")
    m.add_constraints(p_dis - battery.c_rate * cap_batt <= 0, name="discharge_rate")

    w = as_series(weights)
    operating = (
        (w * (economics.fuel_usd_l * fuel_1) * p_gen).sum()
        + (w * (economics.fuel_usd_l * fuel_0) * commit).sum()
        + (w * economics.voll_usd_kwh * unserved).sum()
        + ((w * economics.grid_import_usd_kwh * grid_load).sum()
           - (w * economics.grid_export_usd_kwh * grid_export).sum()
           if grid_load is not None else 0.0)
    )
    # No throughput charge on the battery. Its cost is its capital, recovered over the life
    # that ends it, and charging its wear here as well paid for the same pack twice. The
    # capital below recovers it over the calendar life, which is the longest life it can
    # have and therefore the cheapest: a relaxation, which is what a lower bound must be.
    #
    # A field on the battery's bus buys only its modules, the conversion coming with the
    # hybrid inverter; a field on the load's bus buys its string inverters as well.
    capital = (a_pv * cap_pv + a_pv_ac * cap_pv_ac + a_batt * cap_batt
               + a_inv * cap_inv + a_gen * cap_gen)
    # The connection and the balance of plant are the same amount for every design, so they
    # move the bound and the rule oracle by exactly as much and leave the ranking alone.
    # Leaving them out of the bound alone does not make it invalid -- a smaller number is
    # still a lower bound -- but it makes it loose by their whole size, and a loose bound
    # prunes nothing. With them the gap is the price of the heuristic; without them it was
    # the price of the heuristic plus the network.
    # Added to the solved value rather than to the model: a constant term shifts no
    # optimum, and linopy declines to carry one.
    #
    # The plant already standing enters here for the same reason, and it is exactly a
    # constant. Every admissible design carries at least what exists -- the lattice puts
    # its floor there -- so ``cap - installed`` is the capacity actually bought and the
    # credit below is the difference between charging the whole and charging the
    # extension. What the standing plant still owes, its upkeep and the replacement its
    # remaining life defers, is added in its place. Were the floor not the standing plant
    # this credit would over-pay a design below it, which is why the floor and this term
    # belong to one change.
    credit = (a_pv * economics.installed_capacity("pv")
              + a_pv_ac * economics.installed_capacity("pv_ac")
              + a_batt * economics.installed_capacity("battery")
              + a_inv * economics.installed_capacity("inverter")
              + a_gen * economics.installed_capacity("generator"))
    constant = (economics.grid_connection_usd_yr + economics.infrastructure_usd_yr
                + economics.existing_plant_usd_yr - credit)
    m.add_objective(operating + capital)

    # The bound is solved thousands of times; its progress bars would drown every other
    # line of output, and each solver silences itself under a different name.
    if solver is None:
        from ..settings import default_settings
        solver = default_settings().solver.name
    quiet = {"highs": {"output_flag": False}, "gurobi": {"OutputFlag": 0}}
    options = dict(quiet.get(solver, {}))
    if threads is not None:
        # Several bounds solved at once must each keep to one thread, or sixteen solvers
        # each claiming every core spend their time contending rather than solving.
        options[{"gurobi": "Threads"}.get(solver, "threads")] = int(threads)
    if solver == "gurobi":
        # Gurobi prints its licence banner when the environment starts, before any model
        # option can apply; the global default has to be set first.
        import gurobipy
        gurobipy.setParam("OutputFlag", 0)
    m.solve(solver_name=solver, progress=False, **options)
    status = str(m.status)

    if "ok" not in status:
        # A box holding no buildable design — every array in it exceeding what its
        # converter admits — has no feasible point and therefore an infinite bound, which
        # is exactly what the search needs in order to discard it. Raising here instead
        # would abort a certification over one empty corner of the lattice.
        return LowerBound(value=float("inf"),
                          capacities=Capacities(pv_kw=box.pv_kw[0],
                                                battery_kwh=box.battery_kwh[0],
                                                inverter_kw=box.inverter_kw[0],
                                                generator_kw=box.generator_kw[0],
                                                pv_ac_kw=box.pv_ac_kw[0],
                                                architecture=box.architecture),
                          operating_cost=float("inf"), capital_cost=float("inf"),
                          relaxed_commitment=relax_commitment, status=status)

    if integer_units is None:
        resolved_ac = float(m.variables["cap_pv_ac"].solution)
        resolved = (float(m.variables["cap_pv"].solution),
                    float(m.variables["cap_batt"].solution),
                    float(m.variables["cap_inv"].solution),
                    float(m.variables["cap_gen"].solution))
    else:
        pv_unit, batt_unit, inv_unit = integer_units
        picked = np.asarray(m.variables["choose"].solution, dtype=float)
        resolved_ac = round(float(m.variables["n_pv_ac"].solution)) * pv_unit
        resolved = (round(float(m.variables["n_pv"].solution)) * pv_unit,
                    round(float(m.variables["n_batt"].solution)) * batt_unit,
                    round(float(m.variables["n_inv"].solution)) * inv_unit,
                    float(sum(r * w for r, w in zip(ratings, picked))))
    solution = Capacities(
        pv_kw=resolved[0],
        battery_kwh=resolved[1],
        inverter_kw=resolved[2],
        generator_kw=resolved[3],
        pv_ac_kw=resolved_ac,
        architecture=box.architecture,
    )
    capital_value = (a_pv * solution.pv_kw + a_pv_ac * solution.pv_ac_kw
                     + a_batt * solution.battery_kwh
                     + a_inv * solution.inverter_kw + a_gen * solution.generator_kw)
    total = float(m.objective.value) + constant
    return LowerBound(value=total, capacities=solution,
                      operating_cost=total - capital_value - constant,
                      capital_cost=capital_value + constant,
                      relaxed_commitment=relax_commitment, status=status)
