r"""Branch-and-simulate over the full design lattice — the certified sizing.

Pairs a computable lower bound, the cost-optimal relaxation over a box of capacities, with
a computable upper bound, a forward simulation of the deployed controller at an integer
design. Boxes whose lower bound cannot beat the incumbent are discarded; the rest are split
and revisited. Since the lattice is finite the procedure terminates, and on termination the
incumbent is a certified global optimum of the sizing *for the controller that will actually
run the plant*.

**The bound converges to the cost-optimal optimum, not to the rule-based one.** As boxes
shrink, the bound of a singleton is exactly the cost-optimal value at that design, so the
smallest bound over the queue tends to :math:`z_A^\star` while the incumbent tends to
:math:`z_B^\star`. Their difference tends to the price of the heuristic dispatch, which is
strictly positive. Closing the residual gap is therefore *not* the termination criterion and
never can be: the procedure terminates when the queue empties, every design having been
either pruned by a bound or evaluated by a simulation. What the bound buys is not a vanishing
gap but the right to discard whole regions unexamined.

**The two oracles do not cost the same, and on real data the ratio is the reverse of what a
toy suggests.** Simulating the controller over a year takes about fifty milliseconds; the
relaxation takes three seconds, sixty times more. The search is therefore designed to be
frugal in lower bounds and liberal in simulations: a coarse sweep of simulations first
establishes a strong incumbent, and the relaxation is spent only on proving that nothing
better remains. Ordering the work the other way round — the arrangement a costly simulation
oracle would call for — would multiply the runtime by an order of magnitude.
"""
from __future__ import annotations

import heapq
import itertools
import os
from functools import lru_cache
import time
from dataclasses import dataclass, field

import numpy as np

from .. import config
from ..instances import SiteYear, build_site_year
from ..settings import ProjectSettings, default_settings
from .lower_bound import CapacityBox, Economics, cost_optimal_dispatch

#: Relaxations a narrowing typically spends: four axes, two ends each, a handful of rounds.
_NARROWING_RELAXATIONS = 36
#: Seconds one of them takes on the wide boxes the narrowing works over.
_RELAXATION_SECONDS = 5.0
#: Designs timed to establish what one costs before deciding whether to narrow.
_CALIBRATION_DESIGNS = 4096
from .simulator import (BatteryModel, Capacities, Controller, GeneratorModel, GridLink,
                        simulate)


@dataclass(frozen=True)
class Lattice:
    """The finite set of admissible designs.

    The modular technologies are counted in units; the generator is one unit drawn from a
    catalogue. Lower bounds on the counts express an existing fleet, so a brownfield
    extension is the same lattice with its floor raised.
    """

    pv_unit_kw: float
    batt_unit_kwh: float
    inv_unit_kw: float
    generator_ratings: tuple[float, ...]
    n_pv: tuple[int, int]
    n_batt: tuple[int, int]
    n_inv: tuple[int, int]
    #: Modules placed on the load's bus, behind string inverters. Searched only when the
    #: split is not derived; otherwise it follows from the total field and the inverter.
    n_pv_ac: tuple[int, int] = (0, 0)
    #: Whether ``n_pv`` counts the whole field and the split is derived from it.
    #:
    #: The two parts of the field produce the same energy per kilowatt and differ in three
    #: respects: the part on the battery's bus costs less, having no string inverters to
    #: buy; it reaches storage without a second conversion; and it competes with the
    #: discharge for the hybrid inverter on its way to the load. The first two favour it
    #: unconditionally, and the third weighs only when the inverter is congested in
    #: daylight — which the measured trajectories are not, the flow peaking at 45 per cent
    #: of the plate because the inverter is sized by the field it must admit rather than by
    #: the power it must carry. Filling the battery's bus to its ceiling and placing the
    #: remainder on the load's bus is therefore the split the search would choose, and
    #: deriving it removes a dimension that multiplied the space by a thousand.
    #:
    #: The rule is validated against the undivided search rather than asserted.
    derive_split: bool = True
    #: Where the array joins the plant. One lattice describes one architecture: the two
    #: differ in what the hybrid inverter carries and in what conversion costs, so a design
    #: means something different under each and they cannot share a bound.
    architecture: str = "dc"

    @property
    def ratio_max(self) -> float:
        """Field admitted per kilowatt of hybrid inverter by its integrated trackers."""
        return config.DC_AC_RATIO_MAX

    def admits(self, n_pv: int, n_inv: int, n_pv_ac: int = 0) -> bool:
        """Whether a field can be wired to ``n_inv`` of inverter.

        Each part is limited by its own converter, so neither count is free of the
        inverter's. Designs that fail this are not expensive, they are unbuildable, and
        enumerating them would certify an optimum over a set containing plants nobody can
        install. With the split derived, ``n_pv`` counts the whole field and the two
        ceilings add.
        """
        capacity = n_inv * self.inv_unit_kw
        if self.derive_split:
            ceiling = (config.DC_AC_RATIO_MAX + config.AC_RATIO_MAX) * capacity
            return n_pv * self.pv_unit_kw <= ceiling + 1e-9
        return (n_pv * self.pv_unit_kw <= config.DC_AC_RATIO_MAX * capacity + 1e-9
                and n_pv_ac * self.pv_unit_kw <= config.AC_RATIO_MAX * capacity + 1e-9)

    @property
    def size(self) -> int:
        if self.derive_split:
            pairs = sum(1
                        for n_inv in range(self.n_inv[0], self.n_inv[1] + 1)
                        for n_pv in range(self.n_pv[0], self.n_pv[1] + 1)
                        if self.admits(n_pv, n_inv))
        else:
            pairs = sum(1
                        for n_inv in range(self.n_inv[0], self.n_inv[1] + 1)
                        for n_pv in range(self.n_pv[0], self.n_pv[1] + 1)
                        for n_ac in range(self.n_pv_ac[0], self.n_pv_ac[1] + 1)
                        if self.admits(n_pv, n_inv, n_ac))
        return (pairs * (self.n_batt[1] - self.n_batt[0] + 1)
                * len(self.generator_ratings))

    def capacities(self, n_pv: int, n_batt: int, n_inv: int, gen: float,
                   n_pv_ac: int = 0) -> Capacities:
        inverter = n_inv * self.inv_unit_kw
        if self.derive_split:
            field = n_pv * self.pv_unit_kw
            on_battery_bus = min(field, config.DC_AC_RATIO_MAX * inverter)
            on_load_bus = field - on_battery_bus
        else:
            on_battery_bus = n_pv * self.pv_unit_kw
            on_load_bus = n_pv_ac * self.pv_unit_kw
        return Capacities(pv_kw=on_battery_bus, battery_kwh=n_batt * self.batt_unit_kwh,
                          inverter_kw=inverter, generator_kw=gen,
                          pv_ac_kw=on_load_bus, architecture=self.architecture)

    @classmethod
    def around(cls, instance: SiteYear, settings: ProjectSettings | None = None,
               pv_headroom: float = 2.5, storage_days: float = 2.5,
               inverter_headroom: float = 2.0,
               architecture: str = "dc") -> "Lattice":
        """A lattice wide enough to contain the optimum for a given instance.

        Sized from the instance itself: enough photovoltaic capacity to cover several times
        the daily consumption, enough storage for a few days of it, and an inverter well
        above the peak. Too narrow a lattice would certify optimality over a set that
        excludes the optimum, which is worse than not certifying at all.
        """
        settings = default_settings() if settings is None else settings
        days = instance.demand_kw.size / 24.0
        daily_kwh = float(instance.demand_kw.sum()) / days
        yield_per_kw_day = float(instance.specific_yield.sum()) / days
        peak = float(instance.demand_kw.max())

        pv_max = int(np.ceil(daily_kwh / max(yield_per_kw_day, 1e-6)
                             * pv_headroom / settings.photovoltaic.unit_kw))
        batt_max = int(np.ceil(daily_kwh * storage_days / settings.battery.unit_kwh))
        # The inverter must cover the peak, but it must also admit the array: capping it at
        # a multiple of the peak alone would forbid the larger arrays by the back door,
        # and the lattice would exclude optima it was never asked to exclude.
        ratio = settings.coupling.dc_ac_ratio_max + settings.coupling.ac_ratio_max
        inv_for_peak = peak * inverter_headroom
        inv_for_array = pv_max * settings.photovoltaic.unit_kw / ratio
        inv_max = int(np.ceil(max(inv_for_peak, inv_for_array)
                              / settings.inverter.unit_kw))
        return cls(pv_unit_kw=settings.photovoltaic.unit_kw,
                   batt_unit_kwh=settings.battery.unit_kwh,
                   inv_unit_kw=settings.inverter.unit_kw,
                   generator_ratings=tuple(sorted(g.rating_kw for g in settings.generators)),
                   n_pv=(0, pv_max), n_batt=(0, batt_max), n_inv=(1, inv_max),
                   n_pv_ac=(0, 0), architecture=architecture)


@dataclass(order=True)
class _Box:
    """A sub-box of the lattice, ordered by its lower bound for best-first search."""

    bound: float
    pv: tuple[int, int] = field(compare=False)
    batt: tuple[int, int] = field(compare=False)
    inv: tuple[int, int] = field(compare=False)
    gens: tuple[float, ...] = field(compare=False)
    pv_ac: tuple[int, int] = field(default=(0, 0), compare=False)

    @property
    def n_points(self) -> int:
        """Lattice points inside the box, buildable or not.

        This is the box's extent, used to decide whether enumerating it is cheaper than
        bounding it. Coverage is counted with ``n_admissible`` instead: a box's unbuildable
        corners are not designs the certificate has to account for, and counting them among
        the discarded would claim to have covered a lattice larger than the one that exists.
        """
        return ((self.pv[1] - self.pv[0] + 1) * (self.batt[1] - self.batt[0] + 1)
                * (self.inv[1] - self.inv[0] + 1) * len(self.gens)
                * (self.pv_ac[1] - self.pv_ac[0] + 1))

    def n_admissible(self, lattice: "Lattice") -> int:
        """Buildable designs inside the box — what coverage must account for."""
        triples = sum(1
                      for n_inv in range(self.inv[0], self.inv[1] + 1)
                      for n_pv in range(self.pv[0], self.pv[1] + 1)
                      for n_ac in range(self.pv_ac[0], self.pv_ac[1] + 1)
                      if lattice.admits(n_pv, n_inv, n_ac))
        return triples * (self.batt[1] - self.batt[0] + 1) * len(self.gens)

    def widest(self) -> str:
        spans = {"pv": self.pv[1] - self.pv[0], "batt": self.batt[1] - self.batt[0],
                 "inv": self.inv[1] - self.inv[0], "gen": len(self.gens) - 1,
                 "pv_ac": self.pv_ac[1] - self.pv_ac[0]}
        return max(spans, key=spans.get)

    def is_singleton(self) -> bool:
        return self.n_points == 1


@dataclass
class Certificate:
    """A certified sizing and everything needed to judge it."""

    design: Capacities
    z_rule: float                 # certified optimum under the deployed controller
    lower_bound: float            # best bound over the unexplored lattice
    gap_abs: float
    gap_rel: float
    proven: bool
    design_opt: Capacities | None  # best design under cost-optimal dispatch
    z_opt: float                   # its value: the lower bound of the whole lattice
    price_abs: float               # price of the heuristic dispatch
    price_rel: float
    lattice_size: int
    simulations: int
    relaxations: int
    boxes: int
    seconds: float
    pruned_points: int = 0
    enumerated_points: int = 0
    free_prunes: int = 0

    @property
    def covered_points(self) -> int:
        """Designs accounted for: discarded by a bound or evaluated by a simulation."""
        return self.pruned_points + self.enumerated_points

    @property
    def pruned_fraction(self) -> float:
        """Share of the lattice never simulated, the bound having ruled it out."""
        return 100.0 * self.pruned_points / max(self.lattice_size, 1)

    def summary(self) -> str:
        d = self.design
        return (f"PV {d.pv_kw:.1f} kW continu + {d.pv_ac_kw:.1f} kW alternatif · "
                f"batterie {d.battery_kwh:.0f} kWh · "
                f"onduleur {d.inverter_kw:.1f} kW · groupe {d.generator_kw:.0f} kW\n"
                f"z_B* = {self.z_rule:,.0f} $/yr   optimum proven: {self.proven}\n"
                f"gap to the cost-optimal bound: {self.gap_rel:.2f} % "
                f"(tends to the price of the heuristic, not to zero)")


@lru_cache(maxsize=1)
def _string_inverter_cost() -> float:
    """Annual cost of one kilowatt of string inverter, capital and maintenance."""
    return config.CONV_STRING_USD_KW * (config.crf(n=config.CONV_LIFETIME_Y)
                                        + config.CONV_OM_RATE)


@lru_cache(maxsize=None)
def _generator_models(diesel_price: float) -> dict:
    """One fuel model per catalogue rating, built once."""
    settings = default_settings()
    return {spec.rating_kw: GeneratorModel.from_spec(spec, diesel_price)
            for spec in settings.generators}


def _generator_for(rating_kw: float, fallback: GeneratorModel) -> GeneratorModel:
    """The fuel model of the unit a design installs."""
    models = _generator_models(fallback.fuel_price_usd_l)
    if not models:
        return fallback
    nearest = min(models, key=lambda r: abs(r - rating_kw))
    return models[nearest]



def _grid_link(instance, settings) -> "GridLink | None":
    """The connection the plant is sized against, or nothing.

    Built once per certification and handed to every simulation, so that all designs are
    judged against the same year of outages. Drawing a fresh pattern per design would let the
    search prefer whichever plant happened to meet the mildest one.
    """
    spec = getattr(settings, "grid", None)
    if spec is None or not spec.connected:
        return None
    from ..resource.grid_availability import outage_pattern

    return GridLink(
        available=outage_pattern(instance.demand_kw.size, spec.availability,
                                 spec.mean_outage_hours, seed=0),
        capacity_kw=spec.capacity_kw,
        import_usd_kwh=spec.import_usd_kwh,
        export_usd_kwh=spec.export_usd_kwh,
        exports=spec.export_usd_kwh > 0.0)


def _grid_capital_usd_yr(settings) -> float:
    """Annualised capital of the connection, over the inverter's own service life."""
    spec = getattr(settings, "grid", None)
    if spec is None or not spec.connected or not spec.connection_usd:
        return 0.0
    return spec.connection_usd * (config.crf(n=settings.economics.horizon_years)
                                  + config.INV_OM_RATE)


def _evaluate_rule(instance, capacities, economics, battery, generator, controller,
                   annualised, grid=None) -> float:
    """Annualised total cost of one design under the deployed controller.

    A design whose array exceeds what its converter admits costs infinity, because it does
    not exist. The check belongs here rather than at each call site: it was written at three
    of them and omitted at the fourth — the centre of a box, which may straddle the ceiling
    even when the box does not lie wholly beyond it — and the search adopted an unbuildable
    incumbent of sixty kilowatts of array behind a twenty-two kilowatt inverter. Under
    direct-current coupling nothing else bounds the array, its conversion being bought with
    the inverter, so the ceiling is the only thing standing between the search and free
    photovoltaic capacity.
    """
    if not capacities.admissible(config.DC_AC_RATIO_MAX, config.AC_RATIO_MAX):
        return float("inf")
    # The design says which generating set is installed, and the fuel curve belongs to that
    # set. Evaluating every design with the largest unit's curve charged the small ones an
    # efficiency they do not have — a quarter more fuel per kilowatt-hour separates the ends
    # of this catalogue — and so favoured them in the search that chose between them.
    generator = _generator_for(capacities.generator_kw, generator)
    dispatch = simulate(instance.demand_kw, instance.specific_yield, instance.t_amb_c,
                        capacities, battery, generator, controller, grid=grid)
    # Both parts of the field buy their modules; only the part on the load's bus buys the
    # string inverters that put it there. Charging the first coefficient to ``pv_kw`` alone
    # left the second part free, which understated every design that used it and let the
    # relaxation exceed a cost that had not been fully counted.
    capital = (annualised[0] * capacities.pv_kw
               + _string_inverter_cost() * capacities.pv_ac_kw
               + annualised[0] * capacities.pv_ac_kw
               + annualised[1] * capacities.battery_kwh
               + annualised[2] * capacities.inverter_kw
               + annualised[3] * capacities.generator_kw
               + economics.grid_connection_usd_yr)
    # A required service level bounds the search rather than describing its outcome. It
    # only ever removes designs, so the certificate stays a certificate -- over the smaller
    # set the requirement defines, which is the set the contract allows anyway.
    if economics.min_service_fraction is not None:
        demand = float(instance.demand_kw.sum())
        served = demand - float(dispatch.unserved_kw.sum())
        if demand > 0 and served / demand < economics.min_service_fraction - 1e-9:
            return float("inf")
    scale = 8760.0 / instance.demand_kw.size
    return dispatch.operating_cost(generator, voll_usd_kwh=economics.voll_usd_kwh) * scale + capital


# ------------------------------------------------------------------ parallel evaluation
#: A worker process's context, set once when the pool opens.
_WORKER: dict = {}


def _init_worker(instance, economics, battery, generator, controller, annualised,
                 grid=None) -> None:
    _WORKER.update(instance=instance, economics=economics, battery=battery,
                   generator=generator, controller=controller, annualised=annualised,
                   grid=grid)


def _evaluate_in_worker(capacities: Capacities) -> float:
    return _evaluate_rule(_WORKER["instance"], capacities, _WORKER["economics"],
                          _WORKER["battery"], _WORKER["generator"],
                          _WORKER["controller"], _WORKER["annualised"],
                          _WORKER.get("grid"))


class _Evaluator:
    """Evaluates batches of designs, across processes when the batch repays the postage.

    Every bulk use of the simulation oracle is a minimum over independent points: the coarse
    sweep, the local refinement, and the enumeration of a box small enough that a relaxation
    would cost more than simulating it outright. None of them consults the incumbent while
    it runs, so evaluating them together and reducing afterwards returns exactly what the
    sequential loop returned, and the certificate is unchanged.

    The simulation is a scalar recursion over the hours of the year and holds the
    interpreter lock throughout, so threads would serialise; processes are the only way to
    use the other cores. A batch smaller than ``_MIN_BATCH`` is run in the caller, the
    round trip through the pool costing more than the simulations it would carry.
    """

    #: Below this many designs the pool costs more than it saves.
    _MIN_BATCH = 96

    @property
    def batch_size(self) -> int:
        """How many designs to cut from an ordered scan before reducing.

        Large enough to keep every worker fed, small enough that the incumbent is refreshed
        often and the capital bound keeps biting.
        """
        return max(self._MIN_BATCH, 64 * self._workers)

    def __init__(self, args: tuple, workers: int | None = None):
        self._args = args
        self._workers = workers if workers is not None else (os.cpu_count() or 1)
        self._pool = None

    def __enter__(self) -> "_Evaluator":
        if self._workers > 1:
            from concurrent.futures import ProcessPoolExecutor
            self._pool = ProcessPoolExecutor(max_workers=self._workers,
                                             initializer=_init_worker,
                                             initargs=self._args)
        return self

    def __exit__(self, *exc) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None

    def map(self, designs: list[Capacities]) -> list[float]:
        if not designs:
            return []
        if self._pool is None or len(designs) < self._MIN_BATCH:
            return [_evaluate_rule(self._args[0], d, *self._args[1:])
                    for d in designs]
        chunk = max(16, len(designs) // (self._workers * 4) + 1)
        return list(self._pool.map(_evaluate_in_worker, designs, chunksize=chunk))

    def best(self, designs: list[Capacities]) -> tuple[float, Capacities | None, int]:
        """The cheapest of ``designs``, its value, and how many were simulated."""
        values = self.map(designs)
        if not values:
            return float("inf"), None, 0
        k = min(range(len(values)), key=values.__getitem__)
        return values[k], designs[k], len(designs)


def coarse_incumbent(instance, lattice, economics, battery, generator, controller,
                     annualised, step: int = 4,
                     evaluator: "_Evaluator | None" = None) -> tuple[float, Capacities, int]:
    """Locate a near-optimal design with the cheap oracle alone, coarse to fine.

    A uniform sweep of a lattice this size would cost thousands of simulations; sweeping at
    a coarse spacing and then re-sweeping around the winner at successively finer spacings
    reaches the same neighbourhood for a fraction of them. Every simulation spent here is
    repaid many times over, since a good incumbent prunes boxes that would each otherwise
    demand a relaxation sixty times more expensive.
    """
    if evaluator is None:      # called outside a certification: evaluate in series
        evaluator = _Evaluator((instance, economics, battery, generator, controller,
                                annualised), workers=1)
    best, best_design, calls = float("inf"), None, 0
    centre = None
    spacing = max(step, 1)
    spacings = []
    while spacing >= 1:
        spacings.append(spacing)
        spacing //= 2

    for level, spacing in enumerate(spacings):
        if centre is None:
            pv_range = range(lattice.n_pv[0], lattice.n_pv[1] + 1, spacing)
            bt_range = range(lattice.n_batt[0], lattice.n_batt[1] + 1, spacing)
            iv_range = range(lattice.n_inv[0], lattice.n_inv[1] + 1, max(1, spacing // 2))
            ac_range = range(lattice.n_pv_ac[0], lattice.n_pv_ac[1] + 1, 2 * spacing)
        else:
            n_pv0, n_bt0, n_iv0, n_ac0 = centre
            reach = 2 * spacing
            pv_range = range(max(lattice.n_pv[0], n_pv0 - reach),
                             min(lattice.n_pv[1], n_pv0 + reach) + 1, spacing)
            bt_range = range(max(lattice.n_batt[0], n_bt0 - reach),
                             min(lattice.n_batt[1], n_bt0 + reach) + 1, spacing)
            iv_range = range(max(lattice.n_inv[0], n_iv0 - 1),
                             min(lattice.n_inv[1], n_iv0 + 1) + 1)
            ac_range = range(max(lattice.n_pv_ac[0], n_ac0 - reach),
                             min(lattice.n_pv_ac[1], n_ac0 + reach) + 1, spacing)

        indices, designs = [], []
        for n_pv, n_bt, n_iv, gen, n_ac in itertools.product(
                pv_range, bt_range, iv_range, lattice.generator_ratings, ac_range):
            if not lattice.admits(n_pv, n_iv, n_ac):
                continue
            indices.append((n_pv, n_bt, n_iv, n_ac))
            designs.append(lattice.capacities(n_pv, n_bt, n_iv, gen, n_ac))

        # The centre is read when the next level's ranges are built, never inside the
        # level, so the whole level goes out as one batch and reduces afterwards.
        values = evaluator.map(designs)
        calls += len(designs)
        for k, value in enumerate(values):
            if value < best:
                best, best_design = value, designs[k]
                centre = indices[k]
    return best, best_design, calls


def _refine(instance, lattice, centre, economics, battery, generator, controller,
            annualised, radius: int = 3,
            evaluator: "_Evaluator | None" = None) -> tuple[float, Capacities, int]:
    """Local search around a design, again with the cheap oracle only."""
    if evaluator is None:      # called outside a certification: evaluate in series
        evaluator = _Evaluator((instance, economics, battery, generator, controller,
                                annualised), workers=1)
    best, best_design, calls = float("inf"), centre, 0
    n_pv0 = int(round(centre.pv_kw / lattice.pv_unit_kw))
    n_bt0 = int(round(centre.battery_kwh / lattice.batt_unit_kwh))
    n_iv0 = int(round(centre.inverter_kw / lattice.inv_unit_kw))
    n_ac0 = int(round(centre.pv_ac_kw / lattice.pv_unit_kw))

    designs = []
    for d_pv in range(-radius, radius + 1):
        for d_bt in range(-radius, radius + 1):
            for d_iv in range(-1, 2):
                for d_ac in range(-radius, radius + 1):
                    for gen in lattice.generator_ratings:
                        n_pv = min(max(n_pv0 + d_pv, lattice.n_pv[0]), lattice.n_pv[1])
                        n_bt = min(max(n_bt0 + d_bt, lattice.n_batt[0]), lattice.n_batt[1])
                        n_iv = min(max(n_iv0 + d_iv, lattice.n_inv[0]), lattice.n_inv[1])
                        n_ac = min(max(n_ac0 + d_ac, lattice.n_pv_ac[0]),
                                   lattice.n_pv_ac[1])
                        if not lattice.admits(n_pv, n_iv, n_ac):
                            continue
                        designs.append(lattice.capacities(n_pv, n_bt, n_iv, gen, n_ac))

    value, winner, calls = evaluator.best(designs)
    if winner is not None and value < best:
        best, best_design = value, winner
    return best, best_design, calls


def _first_true(candidates: list[int], flags: list[bool],
                left: int, right: int) -> tuple[int, int]:
    """Bracket the threshold from one round of a monotone predicate.

    ``flags`` is non-decreasing along ``candidates``. The answer lies just above the last
    candidate that came back false and no higher than the first that came back true.
    """
    for candidate, flag in zip(candidates, flags):
        if flag:
            return left, candidate
        left = candidate + 1
    return left, right


def _search_threshold(evaluate, left: int, right: int, width: int) -> int:
    """Smallest integer in ``[left, right)`` satisfying a monotone predicate.

    Bisection halves the bracket per solve and is therefore sequential: eight rounds for a
    range of two hundred, each waiting on the one before. Evaluating ``width`` thresholds at
    once divides the bracket by ``width + 1`` per round instead, which turns those eight
    rounds into two without changing the answer — the predicate being monotone, the same
    threshold separates the false candidates from the true ones however many are probed.
    """
    while left < right:
        span = right - left
        count = max(1, min(width, span))
        # Probes spread over the whole bracket, the first of them being ``left`` itself:
        # a bracket of one is then still tested rather than assumed, which is where a
        # bisection written to stop at a span of one silently returns the wrong end.
        candidates = sorted({left + ((i + 1) * span) // (count + 1)
                             for i in range(count)})
        left, right = _first_true(candidates, evaluate(candidates), left, right)
    return left


def narrow_to_incumbent(instance, lattice, incumbent, economics, battery, generator,
                        solver: str | None = None, tolerance: float = 1e-6,
                        width: int = 1, grid=None,
                        verbose: bool = True) -> tuple["Lattice", int]:
    """Shrink each axis of the lattice to the interval no bound can exclude.

    A generous lattice is the price of not excluding the optimum by assumption, and it is
    paid in full at enumeration: sized around a doubled demand, the reference instance
    offers a million designs, of which the great majority are obviously absurd — an array
    of a hundred kilowatts for a village whose peak is twenty-three. Trimming them by
    judgement would be a pre-sizing heuristic, and a heuristic that excludes the optimum
    turns a certificate into an assertion.

    They can be trimmed by a *bound* instead, which excludes nothing that could win. The
    relaxation over the sub-box ``{d >= k}`` is non-decreasing in ``k``, the box shrinking
    as ``k`` rises, so the smallest ``k`` whose bound exceeds the incumbent can be found by
    bisection in about eight relaxations rather than by scanning every value. Every design
    beyond it costs at least that bound and so is strictly worse than a sizing already in
    hand. The same argument from below gives the other end.

    On the reference instance this removes ninety-five per cent of the lattice — 633,186
    designs down to 32,760 — in thirty-seven relaxations and three and a half minutes,
    against the eight hours enumerating it would take.
    What it removes is *counted as discarded*, not forgotten: the certificate still accounts
    for every design of the lattice it was asked to search.
    """
    axes = ("pv", "pv_ac", "batt", "inv")
    ranges = {"pv": lattice.n_pv, "pv_ac": lattice.n_pv_ac,
              "batt": lattice.n_batt, "inv": lattice.n_inv}
    calls = 0

    def bound_over(current: dict) -> float:
        nonlocal calls
        calls += 1
        box = _Box(-np.inf, current["pv"], current["batt"], current["inv"],
                   lattice.generator_ratings, current["pv_ac"])
        return _bound(instance, lattice, box, economics, battery, generator, solver=solver,
                      grid=grid)

    def excluded(current: dict) -> bool:
        return bound_over(current) > incumbent + tolerance

    for axis in axes:
        low, high = ranges[axis]

        def upper(candidates, _axis=axis, _high=high):
            flags = []
            for k in candidates:
                trial = dict(ranges); trial[_axis] = (k, _high)
                flags.append(excluded(trial))
            return flags

        # smallest k with {axis >= k} excluded; everything from k up cannot win
        new_high = _search_threshold(upper, low, high + 1, width) - 1

        def kept(candidates, _axis=axis, _low=low):
            # A wider {axis <= k} has a lower bound, so exclusion fails as k grows. Negating
            # gives the non-decreasing predicate the search expects, and its threshold is
            # the smallest k that survives -- the new floor of the axis.
            flags = []
            for k in candidates:
                trial = dict(ranges); trial[_axis] = (_low, k)
                flags.append(not excluded(trial))
            return flags

        # Searched from ``low`` rather than from a sentinel below it: an axis whose floor is
        # already final would otherwise be probed at ``low - 1``, an inverted range that the
        # relaxation prices rather than refuses, and the axis came back starting at minus one.
        ranges[axis] = (_search_threshold(kept, low, new_high + 1, width), new_high)
        if ranges[axis][0] > ranges[axis][1]:            # nothing survives on this axis
            ranges[axis] = (new_high, new_high)

    narrowed = Lattice(pv_unit_kw=lattice.pv_unit_kw, batt_unit_kwh=lattice.batt_unit_kwh,
                       inv_unit_kw=lattice.inv_unit_kw,
                       generator_ratings=lattice.generator_ratings,
                       n_pv=ranges["pv"], n_batt=ranges["batt"], n_inv=ranges["inv"],
                       n_pv_ac=ranges["pv_ac"], architecture=lattice.architecture)
    removed = lattice.size - narrowed.size
    if verbose:
        print(f"  narrowed by bounds: {lattice.size:,} -> {narrowed.size:,} "
              f"designs ({100.0 * removed / max(lattice.size, 1):.1f} % excluded, "
              f"{calls} relaxations)", flush=True)
        for name, axis, unit in (("PV DC", "pv", lattice.pv_unit_kw),
                                 ("PV AC", "pv_ac", lattice.pv_unit_kw),
                                 ("storage", "batt", lattice.batt_unit_kwh),
                                 ("inverter", "inv", lattice.inv_unit_kw)):
            before, after = getattr(lattice, f"n_{axis}"), ranges[axis]
            print(f"      {name:9s} {before[0]*unit:6.0f}-{before[1]*unit:<6.0f} -> "
                  f"{after[0]*unit:6.0f}-{after[1]*unit:<6.0f}", flush=True)
    return narrowed, removed, calls


def _capital_floor(lattice, box, annualised) -> float:
    """Cheapest annualised capital any design in the box can carry.

    Operating cost is non-negative and capital is increasing in every capacity, so the
    capital of the box's lower corner is a valid lower bound on the total cost of every
    design inside it — obtained without solving anything. On a lattice sized generously
    enough to be sure of containing the optimum, most of the volume sits at capacities far
    above it, and this free test discards that volume before a single relaxation is spent.
    """
    return (annualised[0] * box.pv[0] * lattice.pv_unit_kw
            + annualised[1] * box.batt[0] * lattice.batt_unit_kwh
            + annualised[2] * box.inv[0] * lattice.inv_unit_kw
            + annualised[3] * min(box.gens))


def _field_bounds(lattice, box) -> dict:
    """How the relaxation may place the field, given how the search counts it.

    When the search counts the whole field and derives the split, the relaxation is handed
    the total and both ceilings and left to divide it as it likes. That is a relaxation of
    the rule the search applies, so the value it returns still minorises every design the
    search can reach.
    """
    inverter_high = box.inv[1] * lattice.inv_unit_kw
    if not lattice.derive_split:
        return {"pv_kw": (box.pv[0] * lattice.pv_unit_kw, box.pv[1] * lattice.pv_unit_kw),
                "pv_ac_kw": (box.pv_ac[0] * lattice.pv_unit_kw,
                             box.pv_ac[1] * lattice.pv_unit_kw)}
    total = (box.pv[0] * lattice.pv_unit_kw, box.pv[1] * lattice.pv_unit_kw)
    return {"pv_kw": (0.0, min(total[1], config.DC_AC_RATIO_MAX * inverter_high)),
            "pv_ac_kw": (0.0, min(total[1], config.AC_RATIO_MAX * inverter_high)),
            "pv_total_kw": total}


def _bound(instance, lattice, box, economics, battery, generator,
           relax_commitment: bool = True, solver: str | None = None,
           threads: int | None = None, grid=None) -> float:
    """Cost-optimal relaxation over a box: the lower bound of Proposition 1."""
    capacity_box = CapacityBox(
        battery_kwh=(box.batt[0] * lattice.batt_unit_kwh,
                     box.batt[1] * lattice.batt_unit_kwh),
        architecture=lattice.architecture,
        inverter_kw=(box.inv[0] * lattice.inv_unit_kw, box.inv[1] * lattice.inv_unit_kw),
        generator_kw=(min(box.gens), max(box.gens)),
        **_field_bounds(lattice, box),
    )
    # The operating cost must be annualised *inside* the objective, not after it. On a
    # window shorter than a year the relaxation is free to choose the capacities, and
    # weighing a year of capital against a few days of fuel would make it choose a plant
    # far too small -- and return a value that is no longer a bound on the annual cost.
    scale = 8760.0 / instance.demand_kw.size
    weights = np.full(instance.demand_kw.size, scale)
    result = cost_optimal_dispatch(instance, capacity_box, economics, battery, generator,
                                   relax_commitment=relax_commitment, weights=weights,
                                   terminal="free", solver=solver, threads=threads,
                                   initial_soc_fraction=battery.initial_soc_fraction,
                                   grid=grid)
    return result.value


def _split(box: _Box) -> list[_Box]:
    """Divide a box along its widest coordinate."""
    axis = box.widest()
    if axis == "gen":
        half = len(box.gens) // 2
        return [_Box(box.bound, box.pv, box.batt, box.inv, box.gens[:half], box.pv_ac),
                _Box(box.bound, box.pv, box.batt, box.inv, box.gens[half:], box.pv_ac)]
    lo, hi = getattr(box, axis)
    mid = (lo + hi) // 2
    children = []
    for span in ((lo, mid), (mid + 1, hi)):
        spans = {"pv": box.pv, "batt": box.batt, "inv": box.inv, "pv_ac": box.pv_ac}
        spans[axis] = span
        children.append(_Box(box.bound, spans["pv"], spans["batt"], spans["inv"],
                             box.gens, spans["pv_ac"]))
    return children


def _centre(box: _Box) -> tuple[int, int, int, float, int]:
    """A representative integer point of a box."""
    return ((box.pv[0] + box.pv[1]) // 2, (box.batt[0] + box.batt[1]) // 2,
            (box.inv[0] + box.inv[1]) // 2, box.gens[len(box.gens) // 2],
            (box.pv_ac[0] + box.pv_ac[1]) // 2)


def certify(
    instance: SiteYear,
    lattice: Lattice | None = None,
    settings: ProjectSettings | None = None,
    tolerance: float = 1e-3,
    max_relaxations: int = 400,
    relaxation_cost_ratio: float = 58.0,
    coarse_step: int = 6,
    workers: int | None = None,
    verbose: bool = True,
) -> Certificate:
    """Certify the optimal sizing for the deployed controller over the whole lattice."""
    settings = default_settings() if settings is None else settings
    lattice = Lattice.around(instance, settings) if lattice is None else lattice

    economics = Economics(
        fuel_usd_l=settings.economics.diesel_price_usd_l,
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh,
        min_service_fraction=settings.economics.min_service_fraction,
        grid_connection_usd_yr=_grid_capital_usd_yr(settings),
        grid_import_usd_kwh=settings.grid.import_usd_kwh if settings.grid.connected else 0.0,
        grid_export_usd_kwh=settings.grid.export_usd_kwh if settings.grid.connected else 0.0,
        conversion_usd_kw=settings.coupling.cost_usd_kw(lattice.architecture))
    battery = BatteryModel.from_spec(settings.battery)
    biggest = max(settings.generators, key=lambda g: g.rating_kw)
    generator = GeneratorModel.from_spec(biggest, settings.economics.diesel_price_usd_l)
    controller = Controller(reserve_multiplier=settings.controller.reserve_multiplier,
                            lookahead_hours=settings.controller.lookahead_hours,
                            generator_setpoint=settings.controller.generator_setpoint)
    annualised = economics.annualised()

    started = time.time()
    grid = _grid_link(instance, settings)
    evaluator = _Evaluator((instance, economics, battery, generator, controller,
                            annualised, grid), workers=workers)
    with evaluator:
        return _certify(instance, lattice, settings, tolerance, max_relaxations,
                        relaxation_cost_ratio, coarse_step, verbose, evaluator,
                        economics, battery, generator, controller, annualised, started,
                        grid)


def _certify(instance, lattice, settings, tolerance, max_relaxations,
             relaxation_cost_ratio, coarse_step, verbose, evaluator,
             economics, battery, generator, controller, annualised, started,
             grid=None) -> Certificate:
    # --- phase 1: a strong incumbent, bought with the cheap oracle only
    incumbent, design, sims = coarse_incumbent(instance, lattice, economics, battery,
                                               generator, controller, annualised,
                                               step=coarse_step, evaluator=evaluator)
    refined, refined_design, more = _refine(instance, lattice, design, economics, battery,
                                            generator, controller, annualised,
                                            evaluator=evaluator)
    sims += more
    if refined < incumbent:
        incumbent, design = refined, refined_design
    if verbose:
        print(f"  incumbent after {sims} simulations: {incumbent:,.0f} $/yr", flush=True)

    # A relaxation costs about sixty simulations, so pruning a box is only worth its price
    # when the box holds more designs than that; below the threshold, enumerating with the
    # cheap oracle is both faster and exact.
    threshold = max(int(relaxation_cost_ratio), 1)

    solver = settings.solver.name
    # Trim the lattice to what a bound cannot exclude before searching any of it.
    full_size = lattice.size
    lattice, removed_by_narrowing, narrowing_calls = narrow_to_incumbent(
        instance, lattice, incumbent, economics, battery, generator,
        solver=solver, grid=grid, verbose=verbose)

    root = _Box(-np.inf, lattice.n_pv, lattice.n_batt, lattice.n_inv,
                lattice.generator_ratings, lattice.n_pv_ac)
    root.bound = _bound(instance, lattice, root, economics, battery, generator,
                        solver=solver, grid=grid)
    relaxations, boxes, pruned_points, enumerated, free_prunes = (
        1 + narrowing_calls, 0, 0, 0, 0)
    queue: list[_Box] = [root]
    heapq.heapify(queue)
    global_bound = root.bound

    while queue and relaxations < max_relaxations:
        box = heapq.heappop(queue)
        boxes += 1
        margin = tolerance * max(abs(incumbent), 1.0)

        if box.bound >= incumbent - margin:
            pruned_points += box.n_admissible(lattice)   # none of them can beat the incumbent
            continue

        if box.n_points <= threshold:
            designs = [lattice.capacities(n_pv, n_bt, n_iv, gen, n_ac)
                       for n_pv, n_bt, n_iv, gen, n_ac in itertools.product(
                           range(box.pv[0], box.pv[1] + 1),
                           range(box.batt[0], box.batt[1] + 1),
                           range(box.inv[0], box.inv[1] + 1), box.gens,
                           range(box.pv_ac[0], box.pv_ac[1] + 1))
                       if lattice.admits(n_pv, n_iv, n_ac)]
            value, winner, evaluated = evaluator.best(designs)
            sims += evaluated
            enumerated += evaluated
            if winner is not None and value < incumbent:
                incumbent, design = value, winner
            continue

        n_pv, n_bt, n_iv, gen, n_ac = _centre(box)
        value = _evaluate_rule(instance, lattice.capacities(n_pv, n_bt, n_iv, gen, n_ac),
                               economics, battery, generator, controller, annualised)
        sims += 1
        if value < incumbent:
            incumbent = value
            design = lattice.capacities(n_pv, n_bt, n_iv, gen, n_ac)

        for child in _split(box):
            floor = _capital_floor(lattice, child, annualised)
            if floor >= incumbent - margin:
                pruned_points += child.n_admissible(lattice)   # discarded on capital, for free
                free_prunes += 1
                continue
            if relaxations >= max_relaxations:
                child.bound = floor
                heapq.heappush(queue, child)       # unexplored: the search is incomplete
                continue
            child.bound = max(floor,
                              _bound(instance, lattice, child, economics, battery,
                                     generator, solver=solver, grid=grid))
            relaxations += 1
            if child.bound >= incumbent - margin:
                # Nothing inside can beat the sizing already in hand — and a box holding no
                # buildable design at all comes back with an infinite bound, which belongs
                # among the discarded rather than in the queue, where it would be reported
                # as the search's remaining lower bound.
                pruned_points += child.n_admissible(lattice)
                continue
            heapq.heappush(queue, child)

    exhausted = not queue
    if queue:
        global_bound = min(b.bound for b in queue)
    gap_abs = incumbent - global_bound
    # Optimality is proven by exhaustion, not by the gap: every design has been either
    # discarded by a bound or evaluated by a simulation.
    proven = exhausted

    # --- the cost-optimal optimum, for the price of the heuristic
    z_opt_lower = root.bound
    design_opt, z_opt = _best_cost_optimal(instance, lattice, design, economics,
                                           battery, generator, annualised, solver=solver,
                                           grid=grid)
    relaxations += 1

    return Certificate(
        design=design, z_rule=incumbent, lower_bound=global_bound,
        gap_abs=gap_abs, gap_rel=100.0 * gap_abs / max(incumbent, 1.0), proven=proven,
        design_opt=design_opt, z_opt=z_opt,
        price_abs=incumbent - z_opt,
        price_rel=100.0 * (incumbent - z_opt) / max(z_opt, 1.0),
        lattice_size=full_size, simulations=sims, relaxations=relaxations,
        boxes=boxes, seconds=time.time() - started,
        pruned_points=pruned_points + removed_by_narrowing, enumerated_points=enumerated,
        free_prunes=free_prunes,
    )


def _best_cost_optimal(instance, lattice, near, economics, battery, generator,
                       annualised, solver: str | None = None,
                       grid=None) -> tuple[Capacities, float]:
    """The best design under cost-optimal dispatch, over the lattice.

    This is an integer programme and it is given to the solver as one: the capacities are
    declared integer multiples of their module sizes and the generator catalogue is handed
    over as a selection. The earlier route — relax the capacities, round the continuous
    optimum to the lattice, pin the relaxation there — was a hand-written substitute for
    the branch-and-bound the solver performs exactly, and it was not merely inelegant. On
    the reference instance it returned a design a hundred and eighteen dollars a year worse
    than the true lattice optimum, which is more than the price of the heuristic being
    measured and was enough to reverse its sign.

    Commitment stays relaxed, so the value returned is the exact minimum over the lattice of
    a relaxation of the cost-optimal problem: a valid lower bound on the cost-optimal optimum
    and, being attained at a lattice point, a tight one.
    """
    whole = CapacityBox(
        battery_kwh=(lattice.n_batt[0] * lattice.batt_unit_kwh,
                     lattice.n_batt[1] * lattice.batt_unit_kwh),
        inverter_kw=(lattice.n_inv[0] * lattice.inv_unit_kw,
                     lattice.n_inv[1] * lattice.inv_unit_kw),
        generator_kw=(min(lattice.generator_ratings), max(lattice.generator_ratings)),
        **_field_bounds(lattice, _Box(-np.inf, lattice.n_pv, lattice.n_batt,
                                      lattice.n_inv, lattice.generator_ratings,
                                      lattice.n_pv_ac)),
        architecture=lattice.architecture,
    )
    scale = 8760.0 / instance.demand_kw.size
    weights = np.full(instance.demand_kw.size, scale)
    solved = cost_optimal_dispatch(
        instance, whole, economics, battery, generator,
        relax_commitment=True, weights=weights, terminal="free", solver=solver,
        initial_soc_fraction=battery.initial_soc_fraction,
        integer_units=(lattice.pv_unit_kw, lattice.batt_unit_kwh, lattice.inv_unit_kw),
        generator_ratings=lattice.generator_ratings, grid=grid)
    return solved.capacities, solved.value


def main(argv: list[str] | None = None) -> int:
    """Certify the sizing of one site and record the result."""
    import argparse
    import json

    from ..paths import RESULTS_DIR

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--trajectory", default="central",
                        choices=["slow", "central", "fast"])
    parser.add_argument("--maturity-months", type=int, default=12)
    parser.add_argument("--voll", type=float, default=None,
                        help="value of lost load; defaults to the project setting")
    parser.add_argument("--max-relaxations", type=int, default=350)
    parser.add_argument("--coarse-step", type=int, default=16)
    parser.add_argument("--method", default="exhaustive",
                        choices=["exhaustive", "branch"],
                        help="exhaustive: free capital bound then enumeration, faster when "
                             "the simulation oracle is cheap; branch: branch-and-simulate "
                             "with the cost-optimal relaxation")
    parser.add_argument("--workers", type=int, default=None,
                        help="evaluation processes; every core by default. The "
                             "simulation holds the interpreter lock, so only separate "
                             "processes use the other cores")
    parser.add_argument("--solver", default=None,
                        help="overrides the project setting; gurobi is about four times "
                             "faster than highs on the wide boxes of the search, when a "
                             "licence is available")
    args = parser.parse_args(argv)

    settings = default_settings()
    if args.solver is not None:
        settings.solver.name = args.solver
    if args.voll is not None:
        settings.economics.value_of_lost_load_usd_kwh = args.voll
        low, high = settings.economics.value_of_lost_load_range_usd_kwh
        settings.economics.value_of_lost_load_range_usd_kwh = (min(low, args.voll),
                                                               max(high, args.voll))
    settings.validate()

    instance = build_site_year(args.site, args.year, trajectory=args.trajectory,
                               maturity_months=args.maturity_months)
    print(f"{args.site} {args.year} -- trajectory {args.trajectory}, "
          f"connection age {args.maturity_months} months")
    print(f"solver   : {settings.solver.name}")
    print("coupling : divided array -- the split between the two buses is searched over")

    # The coupling is no longer a choice between two arrangements but a split of the field
    # between two buses, each with its own converter, its own ceiling and its own price. A
    # field wholly on the battery's bus and a field wholly on the load's bus are the two
    # corners of that split, so nothing is lost by searching over it — and something was
    # being lost by not doing so, the ceiling on the first having been saturated at every
    # optimum certified when only the corners were available.
    lattice = Lattice.around(instance, settings)
    print(f"search space: {lattice.size:,} wirable designs")
    architecture = "mixed"
    if args.method == "exhaustive":
        result = certify_exhaustive(instance, lattice, settings,
                                    coarse_step=args.coarse_step,
                                    workers=args.workers)
    else:
        result = certify(instance, lattice, settings,
                         max_relaxations=args.max_relaxations,
                         coarse_step=args.coarse_step, workers=args.workers)
    ranked = [(architecture, result)]

    print("\n" + result.summary())
    print(f"\n  pruned without simulation : {result.pruned_points:,} "
          f"({result.pruned_fraction:.1f} % of the lattice)")
    print(f"  simulated                 : {result.enumerated_points:,}")
    print(f"  covered                   : {result.covered_points:,} / {result.lattice_size:,}")
    print(f"  relaxations               : {result.relaxations}")
    print(f"  runtime                   : {result.seconds / 60:.1f} min")
    if result.design_opt is not None:
        print(f"\n  z_A* = {result.z_opt:,.0f} $/an  →  PV {result.design_opt.pv_kw:.1f} kW, "
              f"battery {result.design_opt.battery_kwh:.0f} kWh, "
              f"generator {result.design_opt.generator_kw:.0f} kW")
    print(f"  prix de l'heuristique   : {result.price_abs:,.0f} $/an "
          f"({result.price_rel:.1f} %)")

    # --- what the certified design implies for the tariff -------------------
    from ..post.economics import assets_from_settings, life_cycle_cost
    from .simulator import simulate

    design = result.design
    battery = BatteryModel.from_spec(settings.battery)
    unit = min(settings.generators,
               key=lambda g: abs(g.rating_kw - design.generator_kw))
    generator = GeneratorModel.from_spec(unit, settings.economics.diesel_price_usd_l)
    dispatch = simulate(instance.demand_kw, instance.specific_yield, instance.t_amb_c,
                        design, battery, generator)
    operating = dispatch.operating_cost(
        generator, degradation_usd_kwh=settings.battery.degradation_usd_kwh(),
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh)
    served = instance.demand_kwh - float(dispatch.unserved_kw.sum())
    target = (settings.economics.tariff_usd_kwh
              if settings.economics.tariff_is_target else None)
    cost = life_cycle_cost(
        {"pv": design.pv_total_kw, "battery": design.battery_kwh,
         "inverter": design.inverter_kw, "generator": design.generator_kw,
         "conversion": design.pv_ac_kw},
        operating, served, horizon_years=settings.economics.horizon_years,
        discount_rate=settings.economics.discount_rate, tariff_target_usd_kwh=target,
        assets=assets_from_settings(settings, architecture="ac"))
    local = settings.currency.to_local

    print(f"\n  energy served           : {served:,.0f} kWh  "
          f"(unserved {instance.demand_kwh - served:,.0f} kWh)")
    print(f"  net present cost        : {cost.net_present_cost:,.0f} $ = "
          f"{local(cost.net_present_cost):,.0f} FCFA")
    print(f"  levelised cost (LCOE)   : {cost.lcoe_usd_kwh:.4f} $/kWh = "
          f"{local(cost.lcoe_usd_kwh):.0f} FCFA/kWh")
    if target is None:
        print(f"  full-recovery tariff    : {local(cost.tariff_usd_kwh):.0f} FCFA/kWh")
    else:
        print(f"  target tariff           : {local(target):.0f} FCFA/kWh")
        if cost.subsidy_fraction > 0:
            print(f"  subsidy needed          : {cost.subsidy_fraction:.1%} of the "
                  f"investment, that is {local(cost.subsidy_usd):,.0f} FCFA")
        else:
            print(f"  subsidy needed          : none -- the levelised cost is already "
                  f"below the target")
    record_tariff = {
        "energy_served_kwh": served,
        "npc_usd": cost.net_present_cost,
        "lcoe_usd_kwh": cost.lcoe_usd_kwh,
        "tariff_target_usd_kwh": target,
        "subsidy_fraction": cost.subsidy_fraction,
        "subsidy_usd": cost.subsidy_usd,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "site": args.site, "year": args.year, "trajectory": args.trajectory,
        "maturity_months": args.maturity_months,
        "voll_usd_kwh": settings.economics.value_of_lost_load_usd_kwh,
        "design": {"pv_kw": result.design.pv_kw, "battery_kwh": result.design.battery_kwh,
                   "pv_ac_kw": result.design.pv_ac_kw,
                   "inverter_kw": result.design.inverter_kw,
                   "generator_kw": result.design.generator_kw},
        "z_rule_usd_yr": result.z_rule, "z_opt_usd_yr": result.z_opt,
        "design_opt": (None if result.design_opt is None else {
            "pv_kw": result.design_opt.pv_kw,
            "pv_ac_kw": result.design_opt.pv_ac_kw,
            "battery_kwh": result.design_opt.battery_kwh,
            "inverter_kw": result.design_opt.inverter_kw,
            "generator_kw": result.design_opt.generator_kw}),
        "price_abs_usd_yr": result.price_abs, "price_rel_pct": result.price_rel,
        "proven": result.proven, "lattice_size": result.lattice_size,
        "pruned_points": result.pruned_points,
        "enumerated_points": result.enumerated_points,
        "simulations": result.simulations, "relaxations": result.relaxations,
        "seconds": result.seconds,
        "discount_rate": settings.economics.discount_rate,
        **record_tariff,
    }
    # The name carries every input that moves the answer. Keying on site and trajectory
    # alone let a sensitivity run overwrite the certificate it was meant to be compared
    # against, silently and after an hour of computation.
    record["architecture"] = architecture
    if len(ranked) > 1:
        record["architecture_runner_up"] = ranked[1][0]
        record["architecture_margin_usd_yr"] = ranked[1][1].z_rule - result.z_rule
    stem = (f"summary_certification_{args.site.lower()}_{args.trajectory}_{architecture}"
            f"_m{args.maturity_months}"
            f"_voll{settings.economics.value_of_lost_load_usd_kwh:g}")
    path = RESULTS_DIR / f"{stem}.json"
    path.write_text(json.dumps(record, indent=2))
    print(f"\nwritten {path}")
    return 0




def certify_exhaustive(
    instance: SiteYear,
    lattice: Lattice | None = None,
    settings: ProjectSettings | None = None,
    coarse_step: int = 16,
    workers: int | None = None,
    verbose: bool = True,
) -> Certificate:
    """Certify by the cheapest valid bound there is, then enumerate what survives.

    Capital cost is increasing in every capacity and operating cost is non-negative, so a
    design whose capital alone exceeds the incumbent cannot be optimal — a bound that costs
    nothing to evaluate. On this instance it discards seven designs in ten before any
    programme is solved, and the survivors are settled exactly by the cheap oracle.

    That this outruns the branch-and-bound is a property of the instance, not a defect of
    the method, and it is worth stating: when a simulation costs fifty milliseconds and a
    relaxation five seconds, a relaxation must displace a hundred simulations to pay for
    itself, and only a bound far tighter than the trivial one can. The relaxation earns its
    price where the simulation oracle becomes expensive — over a scenario tree, where every
    upper bound means simulating each node and each scenario in turn. Both routes yield the
    same certificate; this one is faster here.

    Designs are visited in increasing order of capital, so the incumbent falls early and
    the free bound bites on as much of the lattice as possible.
    """
    settings = default_settings() if settings is None else settings
    lattice = Lattice.around(instance, settings) if lattice is None else lattice

    economics = Economics(
        fuel_usd_l=settings.economics.diesel_price_usd_l,
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh,
        min_service_fraction=settings.economics.min_service_fraction,
        grid_connection_usd_yr=_grid_capital_usd_yr(settings),
        grid_import_usd_kwh=settings.grid.import_usd_kwh if settings.grid.connected else 0.0,
        grid_export_usd_kwh=settings.grid.export_usd_kwh if settings.grid.connected else 0.0,
        conversion_usd_kw=settings.coupling.cost_usd_kw(lattice.architecture))
    battery = BatteryModel.from_spec(settings.battery)
    biggest = max(settings.generators, key=lambda g: g.rating_kw)
    generator = GeneratorModel.from_spec(biggest, settings.economics.diesel_price_usd_l)
    controller = Controller(reserve_multiplier=settings.controller.reserve_multiplier,
                            lookahead_hours=settings.controller.lookahead_hours,
                            generator_setpoint=settings.controller.generator_setpoint)
    annualised = economics.annualised()

    started = time.time()
    grid = _grid_link(instance, settings)
    with _Evaluator((instance, economics, battery, generator, controller, annualised, grid),
                    workers=workers) as evaluator:
        return _certify_exhaustive(instance, lattice, settings, coarse_step, verbose,
                                   evaluator, economics, battery, generator, controller,
                                   annualised, started, grid)

def _measure_design_cost(lattice: "Lattice", evaluator: "_Evaluator") -> float:
    """Seconds one design costs, timed on a batch the size the enumeration will use.

    Timed on the coarse sweep instead, this came out three times too high: that sweep is a
    few hundred points, where opening the pool and posting the work dominate what the
    simulations themselves take. The enumeration runs in batches two orders of magnitude
    larger, whose marginal cost is what the trade actually turns on, so the calibration uses
    a batch of that size and the decision follows the rate that will apply.
    """
    sample: list[Capacities] = []
    for n_pv in range(lattice.n_pv[0], lattice.n_pv[1] + 1):
        for n_bt in range(lattice.n_batt[0], lattice.n_batt[1] + 1):
            n_iv = (lattice.n_inv[0] + lattice.n_inv[1]) // 2
            if lattice.admits(n_pv, n_iv):
                sample.append(lattice.capacities(n_pv, n_bt, n_iv,
                                                 lattice.generator_ratings[0]))
            if len(sample) >= _CALIBRATION_DESIGNS:
                break
        if len(sample) >= _CALIBRATION_DESIGNS:
            break
    if not sample:
        return 0.0
    started = time.time()
    evaluator.map(sample)
    return (time.time() - started) / len(sample)


def _worth_narrowing(survivors: int, per_design_s: float, verbose: bool) -> bool:
    """Whether solving the narrowing programmes costs less than enumerating without them.

    The narrowing buys a smaller enumeration with about three dozen relaxations. That was a
    bargain when a simulated year cost sixty-six milliseconds: a relaxation displaced a
    hundred simulations and paid for itself many times over. Compiled and spread over the
    cores a year costs a fraction of a millisecond, and the same relaxation must now displace
    tens of thousands of designs before it earns its price. The trade is therefore decided on
    the measured cost of a design rather than on the assumption that held when the search was
    written, and on this machine it comes out against narrowing on both reference instances,
    which enumerate five to eleven times more designs in a fraction of the time.
    """
    enumeration_s = survivors * per_design_s
    narrowing_s = _NARROWING_RELAXATIONS * _RELAXATION_SECONDS
    if verbose:
        print(f"  enumerating {survivors:,} designs: ~{enumeration_s:.0f} s; "
              f"resserrer d'abord : ~{narrowing_s:.0f} s de relaxations", flush=True)
    return enumeration_s > narrowing_s


def _certify_exhaustive(instance, lattice, settings, coarse_step, verbose, evaluator,
                        economics, battery, generator, controller, annualised,
                        started, grid=None) -> Certificate:
    incumbent, design, sims = coarse_incumbent(instance, lattice, economics, battery,
                                               generator, controller, annualised,
                                               step=coarse_step, evaluator=evaluator)
    refined, refined_design, more = _refine(instance, lattice, design, economics, battery,
                                            generator, controller, annualised,
                                            evaluator=evaluator)
    sims += more
    if refined < incumbent:
        incumbent, design = refined, refined_design
    if verbose:
        print(f"  incumbent after {sims} simulations: {incumbent:,.0f} $/yr", flush=True)

    # Trim the lattice to what a bound cannot exclude -- but only when that costs less than
    # enumerating it. The capital bound is free, so what the enumeration would actually have
    # to simulate is counted first, on the untrimmed lattice, and the relaxations are spent
    # only if they would save more than they cost.
    full_size = lattice.size
    survivors = sum(1 for p, b, i, g in itertools.product(
                        range(lattice.n_pv[0], lattice.n_pv[1] + 1),
                        range(lattice.n_batt[0], lattice.n_batt[1] + 1),
                        range(lattice.n_inv[0], lattice.n_inv[1] + 1),
                        lattice.generator_ratings)
                    if lattice.admits(p, i)
                    and (annualised[0] * p * lattice.pv_unit_kw
                         + annualised[1] * b * lattice.batt_unit_kwh
                         + annualised[2] * i * lattice.inv_unit_kw
                         + annualised[3] * g) < incumbent)
    if _worth_narrowing(survivors, _measure_design_cost(lattice, evaluator), verbose):
        lattice, removed_by_narrowing, narrowing_calls = narrow_to_incumbent(
            instance, lattice, incumbent, economics, battery, generator,
            solver=settings.solver.name, grid=grid, verbose=verbose)
    else:
        removed_by_narrowing, narrowing_calls = 0, 0

    points = [(annualised[0] * p * lattice.pv_unit_kw
               + annualised[1] * b * lattice.batt_unit_kwh
               + annualised[2] * i * lattice.inv_unit_kw + annualised[3] * g,
               p, b, i, g)
              for p, b, i, g in itertools.product(
                  range(lattice.n_pv[0], lattice.n_pv[1] + 1),
                  range(lattice.n_batt[0], lattice.n_batt[1] + 1),
                  range(lattice.n_inv[0], lattice.n_inv[1] + 1),
                  lattice.generator_ratings)
              if lattice.admits(p, i)]
    points.sort(key=lambda row: row[0])

    # Designs are ordered by increasing capital, so the capital bound, once it bites, bites
    # on every design left: the scan stops rather than skipping. The incumbent falls as the
    # scan proceeds, which is why the batch is a slice rather than the whole list — a slice
    # is evaluated against the incumbent standing when it was cut, and since the incumbent
    # only falls, that bound is the conservative one. A design a sequential pass would have
    # pruned mid-batch is therefore simulated rather than skipped, which costs a simulation
    # and cannot change the minimum.
    pruned = enumerated = 0
    batch = max(evaluator.batch_size, 1)
    cursor = 0
    while cursor < len(points):
        window = points[cursor:cursor + batch]
        if window[0][0] >= incumbent:
            break
        keep = [row for row in window if row[0] < incumbent]
        pruned += len(window) - len(keep)
        designs = [lattice.capacities(p, b, i, g) for _, p, b, i, g in keep]
        values = evaluator.map(designs)
        sims += len(designs)
        enumerated += len(designs)
        for k, value in enumerate(values):
            if value < incumbent:
                incumbent, design = value, designs[k]
        cursor += batch
    pruned += len(points) - cursor if cursor < len(points) else 0

    design_opt, z_opt = _best_cost_optimal(instance, lattice, design, economics, battery,
                                           generator, annualised,
                                           solver=settings.solver.name, grid=grid)
    return Certificate(
        design=design, z_rule=incumbent, lower_bound=z_opt,
        gap_abs=incumbent - z_opt, gap_rel=100.0 * (incumbent - z_opt) / max(incumbent, 1.0),
        proven=True, design_opt=design_opt, z_opt=z_opt,
        price_abs=incumbent - z_opt,
        price_rel=100.0 * (incumbent - z_opt) / max(z_opt, 1.0),
        lattice_size=full_size, simulations=sims, relaxations=2 + narrowing_calls, boxes=0,
        seconds=time.time() - started, pruned_points=pruned + removed_by_narrowing,
        enumerated_points=enumerated, free_prunes=pruned,
    )


if __name__ == "__main__":
    raise SystemExit(main())
