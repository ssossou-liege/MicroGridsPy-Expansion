"""What a mini-grid costs is not what its power plant costs.

Every figure in this file was wrong in a way that pointed the same direction -- towards a
project cheaper and more bankable than the one a developer would actually build -- and each
was invisible because the arithmetic was right. The plant was priced and the network that
carries its energy was not, so a village came to three hundred dollars a household against
the eight hundred to fifteen hundred one really costs. The battery was recovered over its
calendar life in the capital accounts and charged again per kilowatt-hour of throughput in
the operating ones, the same pack bought twice. Revenue counted every kilowatt-hour served
as billed and collected. And the residual value of the plant sat in the revenue column of
the final year, where a lender reading a cash-flow table would take it for cash.

These tests hold the corrections in place.
"""
from __future__ import annotations

import inspect

import pytest

from microgrid_expansion.post.economics import (assets_from_settings, infrastructure_assets,
                                                life_cycle_cost)
from microgrid_expansion.post.finance import appraise
from microgrid_expansion.settings import default_settings

PLANT = {"pv": 57.5, "battery": 135.0, "inverter": 25.0, "generator": 8.0,
         "conversion": 25.0}
SERVED = 62_611.8
DISCHARGED = 36_754.0
FUEL_USD_YR = 996.8 * 1.29


def _priced() -> object:
    """Settings with a balance of plant a developer would actually quote."""
    settings = default_settings()
    spec = settings.infrastructure
    spec.distribution_usd = 55_000.0
    spec.connection_single_phase_usd = 120.0
    spec.connection_three_phase_usd = 380.0
    spec.civil_works_usd = 12_000.0
    spec.development_usd = 9_000.0
    return settings


# ------------------------------------------------------------------ the battery, once
def test_the_battery_is_not_paid_for_twice() -> None:
    """Capital over the calendar life plus wear over the cycle life is the same pack twice.

    The two are the same money: the throughput price *is* the capital divided by the cycles
    it buys. Charging both inflated this project's own reported levelised cost by a sixth.
    """
    settings = default_settings()
    life = settings.battery.effective_lifetime_years(135.0, DISCHARGED)
    assets = assets_from_settings(settings, architecture="ac", battery_lifetime_years=life)

    once = life_cycle_cost(PLANT, FUEL_USD_YR, SERVED, horizon_years=25,
                           discount_rate=0.08, assets=assets)
    twice = life_cycle_cost(
        PLANT, FUEL_USD_YR + DISCHARGED * settings.battery.degradation_usd_kwh(), SERVED,
        horizon_years=25, discount_rate=0.08, assets=assets)
    assert twice.lcoe_usd_kwh > once.lcoe_usd_kwh * 1.10, (
        "the throughput charge is not material here, so this test proves nothing")
    assert once.lcoe_usd_kwh == pytest.approx(0.2078, abs=5e-3)


def test_the_operating_cost_no_longer_charges_storage_wear() -> None:
    """The default has to be zero, or the double charge comes back through the default."""
    import inspect

    from microgrid_expansion.exact.simulator import Dispatch

    signature = inspect.signature(Dispatch.operating_cost)
    assert signature.parameters["degradation_usd_kwh"].default == 0.0


def test_a_hard_cycled_pack_is_replaced_before_its_calendar_life() -> None:
    """Wear now shortens the life instead of being billed beside it."""
    battery = default_settings().battery
    roomy = battery.effective_lifetime_years(300.0, DISCHARGED)
    tight = battery.effective_lifetime_years(60.0, DISCHARGED)
    assert roomy == battery.lifetime_years, "a lightly cycled pack should reach its age"
    assert tight < battery.lifetime_years, "a hard-cycled pack should not"
    assert tight == pytest.approx(battery.cycle_limited_years(60.0, DISCHARGED))


def test_an_idle_pack_is_limited_by_the_calendar_and_not_by_nothing() -> None:
    battery = default_settings().battery
    assert battery.effective_lifetime_years(135.0, 0.0) == battery.lifetime_years
    assert battery.cycle_limited_years(135.0, 0.0) == float("inf")


# ------------------------------------------------------- everything beyond the plant
def test_the_balance_of_plant_defaults_to_zero_and_says_so() -> None:
    """A plausible default would be quoted as though someone had sourced it."""
    spec = default_settings().infrastructure
    assert spec.capital_usd(231, 6) == 0.0
    assert spec.annualised_usd_yr(231, 6) == 0.0
    assert not spec.provenance.verified
    assert spec.provenance.note


def test_connections_are_counted_per_customer_and_per_phase() -> None:
    spec = _priced().infrastructure
    assert spec.connections_usd(231, 6) == pytest.approx(231 * 120.0 + 6 * 380.0)
    assert spec.connections_usd(0, 0) == 0.0
    # A negative count is a bug upstream, not a rebate.
    assert spec.connections_usd(-5, -5) == 0.0


def test_pricing_the_network_moves_the_project_from_bankable_to_subsidised() -> None:
    """The finding this whole file exists for, stated as a number."""
    settings = _priced()
    life = settings.battery.effective_lifetime_years(135.0, DISCHARGED)
    plant_only = assets_from_settings(settings, architecture="ac",
                                      battery_lifetime_years=life)
    whole = dict(plant_only)
    balance = infrastructure_assets(settings, 25)
    whole.update(balance)
    capacities = {**PLANT, **{name: 1.0 for name in balance}}

    bare = life_cycle_cost(PLANT, FUEL_USD_YR, SERVED, horizon_years=25,
                           discount_rate=0.08, tariff_target_usd_kwh=0.263,
                           assets=plant_only)
    full = life_cycle_cost(capacities, FUEL_USD_YR, SERVED, horizon_years=25,
                           discount_rate=0.08, tariff_target_usd_kwh=0.263, assets=whole)

    assert bare.subsidy_fraction == 0.0, "the plant alone appears to need no grant"
    assert full.subsidy_fraction > 0.25, "pricing the network must change that answer"
    assert full.lcoe_usd_kwh > bare.lcoe_usd_kwh * 1.5

    capital = sum(whole[name].unit_cost * qty for name, qty in capacities.items())
    assert 600 < capital / 231 < 1200, (
        f"{capital / 231:.0f} $/household is outside what a West African mini-grid costs")


def test_the_balance_of_plant_does_not_change_which_plant_is_cheapest() -> None:
    """It is the same amount whatever the design, so it must not disturb the ranking."""
    settings = _priced()
    balance = infrastructure_assets(settings, 25)
    extra = {name: 1.0 for name in balance}
    assets = assets_from_settings(settings, architecture="ac")
    assets.update(balance)

    bigger = {**PLANT, "battery": 200.0}
    def cost(plant, with_balance):
        caps = {**plant, **(extra if with_balance else {})}
        return life_cycle_cost(caps, FUEL_USD_YR, SERVED, horizon_years=25,
                               discount_rate=0.08, assets=assets).net_present_cost

    gap_without = cost(bigger, False) - cost(PLANT, False)
    gap_with = cost(bigger, True) - cost(PLANT, True)
    assert gap_with == pytest.approx(gap_without, rel=1e-9)


# --------------------------------------------------------------- revenue and salvage
def test_revenue_is_what_is_collected_not_what_is_delivered() -> None:
    assets = assets_from_settings(default_settings(), architecture="ac")
    full = appraise(PLANT, FUEL_USD_YR, SERVED, tariff_usd_kwh=0.263, assets=assets)
    lossy = appraise(PLANT, FUEL_USD_YR, SERVED, tariff_usd_kwh=0.263, assets=assets,
                     collection_rate=0.85)
    assert lossy.annual_revenue == pytest.approx(full.annual_revenue * 0.85)
    assert lossy.irr < full.irr


def test_a_collection_shortfall_raises_the_subsidy_the_project_needs() -> None:
    """A tariff below the levelised cost, or the subsidy is zero either way and the
    comparison says nothing."""
    assets = assets_from_settings(default_settings(), architecture="ac")
    target = 0.15
    paid = life_cycle_cost(PLANT, FUEL_USD_YR, SERVED, horizon_years=25, discount_rate=0.08,
                           tariff_target_usd_kwh=target, assets=assets, collection_rate=1.0)
    short = life_cycle_cost(PLANT, FUEL_USD_YR, SERVED, horizon_years=25, discount_rate=0.08,
                            tariff_target_usd_kwh=target, assets=assets,
                            collection_rate=0.85)
    assert target < paid.lcoe_usd_kwh, "the target must bind for this to test anything"
    assert paid.subsidy_fraction > 0
    assert short.subsidy_fraction > paid.subsidy_fraction


def test_salvage_is_not_revenue() -> None:
    """It appears on its own line, and the return is given with and without it.

    Straight-line residual value is a standard levelised-cost convention and belongs in the
    cost. In a cash-flow table it is not cash: nobody pays it, and a lender strikes it out.
    """
    assets = assets_from_settings(default_settings(), architecture="ac")
    result = appraise(PLANT, FUEL_USD_YR, SERVED, tariff_usd_kwh=0.263, assets=assets)
    last = result.years[-1]

    assert result.salvage > 0
    assert last.salvage == pytest.approx(result.salvage)
    assert last.revenue == pytest.approx(result.annual_revenue), (
        "the residual value has leaked back into the revenue column")
    assert last.net == pytest.approx(last.net_without_salvage + result.salvage)
    assert result.irr_without_salvage < result.irr

    payload = result.to_dict()
    assert payload["cash_flows"][-1]["salvage"] == pytest.approx(result.salvage)
    assert payload["irr_without_salvage"] == pytest.approx(result.irr_without_salvage)


# ---------------------------------------------------- the figure that measures the controller
def test_the_price_of_the_heuristic_does_not_move_with_the_cost_boundary() -> None:
    """It measures the controller, so pricing a network must not change it.

    Adding the balance of plant adds the same money to both oracles. Left in the
    denominator it shrank the reported price of the heuristic from 6.1 to 3.5 per cent on
    this project's own example site, without a line of the controller changing -- which
    would let a developer improve their dispatch by costing their poles.
    """
    from microgrid_expansion.exact.certify import _price_relative
    from microgrid_expansion.exact.lower_bound import Economics

    z_rule, z_opt = 15_302.0, 14_424.0
    bare = _price_relative(z_rule, z_opt, Economics())
    constant = 11_807.0
    costed = _price_relative(z_rule + constant, z_opt + constant,
                             Economics(infrastructure_usd_yr=constant))
    assert bare == pytest.approx(costed, rel=1e-9)
    assert bare == pytest.approx(6.09, abs=0.02)


def test_a_saturated_ceiling_is_reported_rather_than_left_to_be_noticed() -> None:
    """Both array ratios are single sourced numbers, and the optimum sits on them.

    Checked where a design is priced, which is the one function the interface and the
    command line share; asserting it in the caller would have to be written twice, which is
    what put the two of them out of step in the first place.
    """
    from microgrid_expansion.post import appraisal
    from microgrid_expansion.ui import engine

    priced = inspect.getsource(appraisal.price_certified_design)
    assert "dc_ac_ratio_max" in priced and "ac_ratio_max" in priced
    assert "binding" in priced
    assert "binding_ceilings" in inspect.getsource(engine.size_site)
