"""What a mini-grid costs is not what its power plant costs.

Every figure in this file was wrong in a way that pointed the same direction -- towards a
project cheaper and more bankable than the one a developer would actually build -- and each
was invisible because the arithmetic was right. The plant was priced and the network that
carries its energy was not, so a village came to three hundred dollars a household against
the eight hundred to fifteen hundred one really costs. The battery was recovered over its
calendar life in the capital accounts and charged again per kilowatt-hour of throughput in
the operating ones, the same pack bought twice. Revenue counted every kilowatt-hour served
as billed and collected -- and then, corrected by one fraction, counted the street lighting
as a customer in arrears rather than as a load nobody is invoiced for. And the residual
value of the plant sat in the revenue column of the final year, where a lender reading a
cash-flow table would take it for cash.

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
    # The level follows the equipment prices, which the operator's procurement budget
    # revised: cheaper storage and much cheaper conversion against a dearer array, and a
    # quarter off the levelised cost of this fixed plant. What the test is about is the
    # ratio above, which the level does not touch.
    assert once.lcoe_usd_kwh == pytest.approx(0.1553, abs=5e-3)


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
    # A fifth of the capital, which is the claim: the plant alone looks bankable and the
    # project does not. The threshold was a quarter while the plant was dearer; what has to
    # stay true is that the answer moves from nothing to a substantial grant.
    assert full.subsidy_fraction > 0.20, "pricing the network must change that answer"
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

# ------------------------------------------------------- what is sold, what is only served
def test_the_tariff_is_collected_on_the_customer_energy_and_not_on_the_delivery() -> None:
    """A mini-grid serves loads it invoices nobody for, and they are not arrears.

    Street lighting and the plant's own supply reach no meter. Passing them through the
    collection rate would make them look like a recoverable shortfall and would also get
    the arithmetic wrong, since a lighting load that burns the same hours whatever the
    village consumes is not a fixed share of what the village consumes.
    """
    assets = assets_from_settings(default_settings(), architecture="ac")
    billable = SERVED * 0.9
    sold = appraise(PLANT, FUEL_USD_YR, SERVED, tariff_usd_kwh=0.263, assets=assets,
                    billable_energy_kwh=billable)
    delivered = appraise(PLANT, FUEL_USD_YR, SERVED, tariff_usd_kwh=0.263, assets=assets)
    assert sold.annual_revenue == pytest.approx(delivered.annual_revenue * 0.9)
    assert sold.billable_energy_kwh == pytest.approx(billable)
    # The two reasons a kilowatt-hour brings in nothing compose rather than replace one
    # another: a tenth is never billed and a sixth of the rest is never paid.
    both = appraise(PLANT, FUEL_USD_YR, SERVED, tariff_usd_kwh=0.263, assets=assets,
                    billable_energy_kwh=billable, collection_rate=0.85)
    assert both.annual_revenue == pytest.approx(sold.annual_revenue * 0.85)


def test_an_unbilled_load_raises_the_subsidy_without_touching_the_levelised_cost() -> None:
    """It costs what it costs to serve; what changes is that it cannot be charged for."""
    assets = assets_from_settings(default_settings(), architecture="ac")
    common = dict(horizon_years=25, discount_rate=0.08, tariff_target_usd_kwh=0.15,
                  assets=assets)
    whole = life_cycle_cost(PLANT, FUEL_USD_YR, SERVED, **common)
    split = life_cycle_cost(PLANT, FUEL_USD_YR, SERVED,
                            billable_energy_kwh=SERVED * 0.9, **common)
    assert split.lcoe_usd_kwh == pytest.approx(whole.lcoe_usd_kwh), (
        "the plant delivers the same energy and costs the same to deliver it")
    assert split.subsidy_fraction > whole.subsidy_fraction
    assert whole.billable_energy_kwh == pytest.approx(SERVED), (
        "with nothing said, every kilowatt-hour is a customer's, as it was before the split")


def test_the_pricing_reads_the_split_off_the_demand_and_not_off_the_form() -> None:
    """The unbilled load is a quantity the community declared, never a parameter.

    Fixed as a share it would grow with the energy sold, which is precisely what the street
    lighting does not do. So the one function that prices a design takes it from the
    instance, and the form carries only the collection rate, which is about arrears.
    """
    from microgrid_expansion.post import appraisal

    source = inspect.getsource(appraisal.price_certified_design)
    assert "billable_fraction" in source
    assert "billable_energy_kwh=billable" in source


# ------------------------------------------------------------- the network in between
def test_the_network_loss_is_a_share_of_the_injection_not_of_the_delivery() -> None:
    """Which is the convention a distribution meter reading is divided into.

    Nine kilowatts reaching customers at a loss of a tenth of the injection means ten
    injected and one lost, not nine point nine injected. At fifteen per cent the two
    readings of the same figure differ by nearly three points, which is more than the
    differences this work reports.
    """
    import numpy as np

    from microgrid_expansion.instances import check_network_loss, with_network_loss

    load = np.full(24, 10.0)
    at_plant = np.full(24, 1.0)          # of which one kilowatt never leaves the plant
    total, lost = with_network_loss(load, at_plant, 0.10)
    assert float(total[0] - at_plant[0]) == pytest.approx(10.0)
    assert float(lost[0]) == pytest.approx(1.0)

    # The plant's own supply draws from the busbar beside it and carries no loss at all.
    same, nothing = with_network_loss(at_plant, at_plant, 0.10)
    assert np.allclose(same, at_plant) and np.allclose(nothing, 0.0)

    # Zero is exactly the behaviour there was before the term existed.
    untouched, none = with_network_loss(load, at_plant, 0.0)
    assert untouched is load and np.allclose(none, 0.0)

    # A share at or above one asks the plant for infinite energy. Refused, not clamped: a
    # figure like that is a decimal point in the wrong place and serving the nearest
    # admissible study would hide it.
    for impossible in (-0.01, 1.0, 15.0):
        with pytest.raises(ValueError):
            check_network_loss(impossible)


def test_the_loss_is_applied_through_one_function_for_the_year_and_for_the_tree() -> None:
    """A plan and a sizing of one village must be asked for the same energy.

    Written twice the two would drift, which is the fault this file already holds the
    repair of in the pricing. So both the certified year and the scenario pool call the
    same function, and this checks that they do rather than that they agree today.
    """
    from microgrid_expansion import instances
    from microgrid_expansion.scenarios import demand_paths

    assert "with_network_loss" in inspect.getsource(instances.build_site_year)
    assert "with_network_loss" in inspect.getsource(demand_paths.simulate_stage_demand)
