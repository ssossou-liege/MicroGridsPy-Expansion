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

    @classmethod
    def at(cls, capacities: Capacities) -> "CapacityBox":
        """The degenerate box at one design point."""
        return cls(pv_kw=(capacities.pv_kw, capacities.pv_kw),
                   battery_kwh=(capacities.battery_kwh, capacities.battery_kwh),
                   inverter_kw=(capacities.inverter_kw, capacities.inverter_kw),
                   generator_kw=(capacities.generator_kw, capacities.generator_kw))


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
    fuel_usd_l: float = config.DIESEL_PRICE_USD_L
    degradation_usd_kwh: float = None
    voll_usd_kwh: float = config.VOLL_USD_KWH

    def __post_init__(self) -> None:
        if self.crf is None:
            object.__setattr__(self, "crf", config.crf())
        if self.degradation_usd_kwh is None:
            object.__setattr__(self, "degradation_usd_kwh",
                               config.battery_degradation_cost())

    def annualised(self) -> tuple[float, float, float, float]:
        """Annualised cost of one unit of each capacity, capital plus maintenance."""
        om_pv, om_batt, om_inv, om_gen = self.om_rates
        return (self.pv_usd_kw * (self.crf + om_pv),
                self.battery_usd_kwh * (self.crf + om_batt),
                self.inverter_usd_kw * (self.crf + om_inv),
                self.generator_usd_kw * (self.crf + om_gen))


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
    solver: str = "highs",
    terminal: str = "free",
    initial_soc_fraction: float | None = None,
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

    demand = instance.demand_kw
    n = demand.size
    weights = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    steps = np.arange(n)

    big_m = box.generator_kw[1]
    fuel_0, fuel_1 = fuel_minorant(generator, big_m if big_m > 0 else 1.0)
    a_pv, a_batt, a_inv, a_gen = economics.annualised()

    m = linopy.Model()
    cap_pv = m.add_variables(lower=box.pv_kw[0], upper=box.pv_kw[1], name="cap_pv")
    cap_batt = m.add_variables(lower=box.battery_kwh[0], upper=box.battery_kwh[1],
                               name="cap_batt")
    cap_inv = m.add_variables(lower=box.inverter_kw[0], upper=box.inverter_kw[1],
                              name="cap_inv")
    cap_gen = m.add_variables(lower=box.generator_kw[0], upper=box.generator_kw[1],
                              name="cap_gen")

    coords = {"step": steps}
    as_series = lambda values: xr.DataArray(np.asarray(values, dtype=float),
                                            coords=coords, dims="step")
    p_gen = m.add_variables(lower=0.0, coords=coords, name="p_gen")
    p_ch = m.add_variables(lower=0.0, coords=coords, name="p_ch")
    p_dis = m.add_variables(lower=0.0, coords=coords, name="p_dis")
    curtail = m.add_variables(lower=0.0, coords=coords, name="curtail")
    unserved = m.add_variables(lower=0.0, upper=demand, coords=coords, name="unserved")
    soc = m.add_variables(lower=0.0, coords={"step": np.arange(n + 1)}, name="soc")
    # linopy refuses bounds on a binary variable, so the two modes are declared apart:
    # relaxed, the commitment is a continuous fraction of an hour; tight, it is integral.
    if relax_commitment:
        commit = m.add_variables(lower=0.0, upper=1.0, coords=coords, name="commit")
    else:
        commit = m.add_variables(coords=coords, name="commit", binary=True)

    yield_ = as_series(instance.specific_yield)
    # power balance
    m.add_constraints(
        yield_ * cap_pv - curtail + p_gen + p_dis - p_ch + unserved == as_series(demand),
        name="balance")
    m.add_constraints(curtail - yield_ * cap_pv <= 0, name="curtail_limit")

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
    m.add_constraints(
        soc_next - retention * soc_prev
        - battery.charge_efficiency * p_ch
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
    m.add_constraints(p_ch - cap_inv <= 0, name="charge_rating")
    m.add_constraints(p_dis - cap_inv <= 0, name="discharge_rating")
    m.add_constraints(p_ch - battery.c_rate * cap_batt <= 0, name="charge_rate")
    m.add_constraints(p_dis - battery.c_rate * cap_batt <= 0, name="discharge_rate")

    w = as_series(weights)
    operating = (
        (w * (economics.fuel_usd_l * fuel_1) * p_gen).sum()
        + (w * (economics.fuel_usd_l * fuel_0) * commit).sum()
        + (w * economics.degradation_usd_kwh * p_dis).sum()
        + (w * economics.voll_usd_kwh * unserved).sum()
    )
    capital = a_pv * cap_pv + a_batt * cap_batt + a_inv * cap_inv + a_gen * cap_gen
    m.add_objective(operating + capital)

    m.solve(solver_name=solver, output_flag=False)
    status = str(m.status)

    solution = Capacities(
        pv_kw=float(m.variables["cap_pv"].solution),
        battery_kwh=float(m.variables["cap_batt"].solution),
        inverter_kw=float(m.variables["cap_inv"].solution),
        generator_kw=float(m.variables["cap_gen"].solution),
    )
    capital_value = (a_pv * solution.pv_kw + a_batt * solution.battery_kwh
                     + a_inv * solution.inverter_kw + a_gen * solution.generator_kw)
    total = float(m.objective.value)
    return LowerBound(value=total, capacities=solution,
                      operating_cost=total - capital_value,
                      capital_cost=capital_value,
                      relaxed_commitment=relax_commitment, status=status)
