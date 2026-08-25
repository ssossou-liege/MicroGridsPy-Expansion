"""Layer 2: the two operating-cost oracles and the life-cycle accounting.

The certificate is only as sound as the inequality between these two oracles, so the tests
concentrate on the properties that inequality rests on: the controller's trajectory must lie
in the feasible set the lower bound is computed over, and the linear fuel curve the bound
uses must never overestimate the fuel the controller actually burns.
"""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.exact.lower_bound import fuel_minorant
from microgrid_expansion.exact.simulator import (
    BatteryModel,
    Capacities,
    Controller,
    GeneratorModel,
    night_reserve,
    simulate,
)
from microgrid_expansion.post.economics import (
    Asset,
    capital_recovery_factor,
    default_assets,
    life_cycle_cost,
)


def synthetic_instance(days: int = 20, households: float = 40.0):
    """A short but realistic instance: evening-peak demand, tropical sun and heat."""
    hours = np.arange(24 * days)
    hour_of_day = hours % 24
    demand = households * (0.010 + 0.004 * np.exp(-((hour_of_day - 19) / 2.5) ** 2)
                           + 0.002 * np.exp(-((hour_of_day - 7) / 2.0) ** 2))
    yield_ = np.clip(np.sin(np.pi * (hour_of_day - 6) / 12.0), 0.0, None) * 0.75
    temperature = 28.0 + 5.0 * np.sin(2 * np.pi * (hour_of_day - 9) / 24.0)
    return demand, yield_, temperature


# ------------------------------------------------------------------ fuel curve
@pytest.mark.parametrize(("part_load", "reference_l_h"),
                         [(0.5, 3.0), (0.75, 4.0), (1.0, 5.3)])
def test_fuel_curve_matches_the_manufacturer_data(part_load, reference_l_h):
    """The ported efficiency must reproduce the fuel figures it was fitted to."""
    generator = GeneratorModel()
    litres = float(generator.fuel_litres(part_load * 16.0, 16.0))
    assert litres == pytest.approx(reference_l_h, rel=0.02)


def test_generator_off_burns_nothing():
    assert float(GeneratorModel().fuel_litres(0.0, 16.0)) == 0.0


def test_linear_fuel_curve_never_overestimates_consumption():
    """A fuel model above the truth could raise the bound above the optimum it bounds."""
    generator = GeneratorModel()
    rating = 16.0
    intercept, slope = fuel_minorant(generator, rating)
    outputs = np.linspace(generator.min_load_fraction * rating, rating, 500)
    true = generator.fuel_litres(outputs, rating)
    linear = intercept + slope * outputs
    assert (linear <= true + 1e-9).all()
    # and it must be tight enough to be useful, not merely valid
    assert np.mean(true - linear) / np.mean(true) < 0.10


def test_fuel_minorant_of_an_absent_generator_is_zero():
    assert fuel_minorant(GeneratorModel(), 0.0) == (0.0, 0.0)


# ------------------------------------------------------------------- controller
def test_the_controller_trajectory_lies_in_the_feasible_set():
    """Assumption 1: without this the bound does not apply at all."""
    from microgrid_expansion.battery import usable_fraction

    demand, yield_, temperature = synthetic_instance()
    capacities = Capacities(pv_kw=12.0, battery_kwh=30.0,
                            inverter_kw=10.0, generator_kw=8.0)
    dispatch = simulate(demand, yield_, temperature, capacities)
    checks = dispatch.feasibility(BatteryModel(), GeneratorModel(),
                                  usable_fraction(temperature))
    assert all(checks.values()), checks


def test_the_energy_balance_closes_at_every_step():
    demand, yield_, temperature = synthetic_instance()
    capacities = Capacities(10.0, 25.0, 8.0, 6.0)
    d = simulate(demand, yield_, temperature, capacities)
    supply = (yield_ * capacities.pv_kw - d.curtailed_kw + d.generator_kw
              + d.discharge_kw - d.charge_kw)
    assert np.allclose(supply, demand - d.unserved_kw, atol=1e-6)


def test_a_larger_plant_never_costs_more_to_operate():
    """Operating cost must fall with capacity; the pruning argument relies on it."""
    demand, yield_, temperature = synthetic_instance()
    small = simulate(demand, yield_, temperature, Capacities(6.0, 15.0, 8.0, 8.0))
    large = simulate(demand, yield_, temperature, Capacities(18.0, 45.0, 12.0, 8.0))
    assert large.operating_cost() <= small.operating_cost()


def test_without_a_generator_the_deficit_becomes_unserved_energy():
    demand, yield_, temperature = synthetic_instance()
    d = simulate(demand, yield_, temperature, Capacities(0.0, 0.0, 5.0, 0.0))
    assert d.generator_kw.sum() == 0.0
    assert d.unserved_kw.sum() == pytest.approx(demand.sum(), rel=1e-6)


def test_the_night_reserve_looks_ahead_to_the_next_surplus():
    demand, yield_, _ = synthetic_instance(days=3)
    reserve = night_reserve(demand, yield_ * 12.0, Controller())
    assert reserve.shape == demand.shape
    assert (reserve >= 0).all()
    # at midday, generation exceeds demand and nothing need be reserved
    midday = np.flatnonzero((np.arange(demand.size) % 24) == 12)
    assert reserve[midday].max() == pytest.approx(0.0, abs=1e-9)


def test_a_wider_reserve_multiplier_defers_more_energy():
    demand, yield_, temperature = synthetic_instance()
    caps = Capacities(12.0, 30.0, 10.0, 8.0)
    lean = simulate(demand, yield_, temperature, caps,
                    controller=Controller(reserve_multiplier=0.0))
    ample = simulate(demand, yield_, temperature, caps,
                     controller=Controller(reserve_multiplier=2.0))
    assert ample.generator_kw.sum() >= lean.generator_kw.sum()


# -------------------------------------------------------------------- economics
def test_capital_recovery_factor_matches_the_closed_form():
    assert capital_recovery_factor(0.12, 25) == pytest.approx(0.127500, abs=1e-5)
    assert capital_recovery_factor(0.0, 10) == pytest.approx(0.1)


def test_assets_are_replaced_within_the_horizon_and_credited_at_the_end():
    battery = Asset("battery", 450.0, 16, 0.06)
    assert battery.replacement_years(25) == [16]
    assert battery.replacement_years(10) == []
    costed = battery.present_cost(10.0, 25, 0.12)
    assert costed["replacement"] > 0            # one replacement in year 16
    assert costed["salvage"] > 0                # nine years of life remain at the horizon
    assert costed["total"] < costed["capital"] + costed["replacement"] + costed["maintenance"]


def test_a_long_lived_asset_needs_no_replacement():
    pv = default_assets()["pv"]
    assert pv.replacement_years(25) == []
    assert pv.present_cost(10.0, 25, 0.12)["replacement"] == 0.0


def test_levelised_cost_scales_inversely_with_energy_served():
    capacities = {"pv": 8.2, "battery": 17.2, "generator": 5.85, "inverter": 6.0}
    a = life_cycle_cost(capacities, 2000.0, 20_000.0)
    b = life_cycle_cost(capacities, 2000.0, 40_000.0)
    assert a.lcoe_usd_kwh == pytest.approx(2 * b.lcoe_usd_kwh, rel=1e-9)
    assert a.net_present_cost == pytest.approx(b.net_present_cost)


def test_unknown_asset_is_rejected():
    with pytest.raises(KeyError):
        life_cycle_cost({"windmill": 1.0}, 0.0, 1.0)


# ------------------------------------------------- the inequality that certifies
def _instance_from(demand, yield_, temperature):
    """Wrap synthetic series in the structure the lower-bound oracle consumes."""
    from microgrid_expansion.battery import self_discharge_fraction, usable_fraction
    from microgrid_expansion.instances import SiteYear

    return SiteYear(site="test", year=2025, demand_kw=demand, specific_yield=yield_,
                    t_amb_c=temperature, usable_fraction=usable_fraction(temperature),
                    self_discharge=self_discharge_fraction(temperature),
                    trajectory="centrale", maturity_months=12, seed=0)


@pytest.mark.parametrize("design", [
    Capacities(8.0, 20.0, 8.0, 6.0),
    # 13 kW of array on 10 kW of inverter is the most its trackers admit; 14 would
    # be a plant nobody can wire, and the bound rightly reports no feasible point.
    Capacities(13.0, 35.0, 10.0, 6.0),
    Capacities(4.0, 10.0, 8.0, 10.0),
])
def test_the_relaxation_never_exceeds_the_rule(design):
    """Proposition 1 on a short real-shaped instance, at three contrasted designs."""
    from microgrid_expansion.exact.lower_bound import (
        CapacityBox, Economics, cost_optimal_dispatch)

    demand, yield_, temperature = synthetic_instance(days=5)
    instance = _instance_from(demand, yield_, temperature)
    economics = Economics()

    dispatch = simulate(demand, yield_, temperature, design)
    relaxed = cost_optimal_dispatch(instance, CapacityBox.at(design), economics,
                                    relax_commitment=True, terminal="free",
                                    initial_soc_fraction=0.5)
    rule_operating = dispatch.operating_cost()
    assert relaxed.operating_cost <= rule_operating + 1e-6 * max(rule_operating, 1.0)


def test_a_cyclic_closure_is_not_comparable_with_a_causal_controller():
    """Documenting the trap: closing the cycle can push the bound above the rule."""
    from microgrid_expansion.exact.lower_bound import (
        CapacityBox, Economics, cost_optimal_dispatch)

    demand, yield_, temperature = synthetic_instance(days=5)
    instance = _instance_from(demand, yield_, temperature)
    design = Capacities(14.0, 60.0, 10.0, 6.0)

    free = cost_optimal_dispatch(instance, CapacityBox.at(design), Economics(),
                                 relax_commitment=True, terminal="free",
                                 initial_soc_fraction=0.5)
    cyclic = cost_optimal_dispatch(instance, CapacityBox.at(design), Economics(),
                                   relax_commitment=True, terminal="cyclic",
                                   initial_soc_fraction=0.5)
    # closing the cycle can only constrain the problem further
    assert cyclic.value >= free.value - 1e-6


def test_an_invalid_terminal_condition_is_rejected():
    from microgrid_expansion.exact.lower_bound import (
        CapacityBox, cost_optimal_dispatch)

    demand, yield_, temperature = synthetic_instance(days=2)
    instance = _instance_from(demand, yield_, temperature)
    with pytest.raises(ValueError, match="terminal"):
        cost_optimal_dispatch(instance, CapacityBox.at(Capacities(5.0, 10.0, 5.0, 5.0)),
                              terminal="periodic")
