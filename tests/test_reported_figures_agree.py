"""Figures shown side by side must be computed side by side.

Every round of this project's review has turned up the same shape of defect: two paths that
compute the same quantity and drift apart, or a parameter that binds one oracle and not the
other. A levelised cost that credits an asset's residual value beside a rate of return that
does not; a service floor imposed on the controller and not on the programme it is compared
against; a cache keyed on a site's name after the site became something a user edits.

None of those were caught by testing each part alone, because each part was right. They are
caught here, by asserting that what the interface puts on one page agrees.
"""
from __future__ import annotations

import pytest

from microgrid_expansion.post.economics import assets_from_settings, life_cycle_cost
from microgrid_expansion.post.finance import appraise
from microgrid_expansion.settings import default_settings

PLANT = {"pv": 40.0, "battery": 95.0, "inverter": 17.5, "generator": 8.0,
         "conversion": 17.25}
OPERATING = 4_000.0
SERVED = 44_800.0


def _both(**kwargs):
    settings = default_settings()
    assets = assets_from_settings(settings, architecture="ac")
    cost = life_cycle_cost(
        PLANT, OPERATING, SERVED,
        horizon_years=settings.economics.horizon_years,
        discount_rate=settings.economics.discount_rate, assets=assets,
        tariff_target_usd_kwh=settings.economics.tariff_usd_kwh)
    money = appraise(
        PLANT, OPERATING, SERVED, tariff_usd_kwh=settings.economics.tariff_usd_kwh,
        horizon_years=settings.economics.horizon_years,
        discount_rate=settings.economics.discount_rate, assets=assets, **kwargs)
    return settings, cost, money


def test_the_two_cost_models_start_from_the_same_capital():
    """The plant costs what it costs, whichever figure is being computed from it."""
    _, cost, money = _both()
    capital = sum(block["capital"] for name, block in cost.breakdown.items()
                  if name != "operating")
    assert money.initial_capital == pytest.approx(capital, rel=1e-9)


def test_the_two_cost_models_credit_the_same_residual_value():
    """Salvage is one property of one plant; both readings must put the same number on it."""
    _, cost, money = _both()
    discount = default_settings().economics.discount_rate
    horizon = default_settings().economics.horizon_years
    # The life-cycle model discounts salvage to today; the cash flow receives it in the
    # final year. Comparing them means bringing one to the other.
    discounted = money.salvage / (1.0 + discount) ** horizon
    expected = sum(block["salvage"] for name, block in cost.breakdown.items()
                   if name != "operating")
    assert discounted == pytest.approx(expected, rel=1e-6)


def test_residual_value_is_credited_by_both_or_by_neither():
    """A late-replaced asset leaves value on the table, and both readings must see it."""
    _, _, money = _both()
    assert money.salvage > 0, (
        "the cash flow credits no residual value while the levelised cost credits "
        "one; both appear on the same page")


def test_a_subsidy_sized_to_the_target_tariff_brings_the_project_to_break_even():
    """The two models agree on what the subsidy is for.

    The levelised cost reports the grant that brings the tariff to its target; the appraisal
    receives that grant. If they agree, the project's value at the discount rate is nil and
    its rate of return is the discount rate. Any real gap between them is the two models
    disagreeing about the same plant.
    """
    settings, cost, _ = _both()
    if not cost.subsidy_usd:
        pytest.skip("no subsidy is needed at this tariff")
    _, _, money = _both(subsidy_usd=cost.subsidy_usd)
    assert money.net_present_value == pytest.approx(0.0, abs=0.02 * abs(money.initial_capital))
    assert money.irr == pytest.approx(settings.economics.discount_rate, abs=0.01)


def test_demand_growth_moves_revenue_and_nothing_else():
    """Growth is a financial assumption; it must not silently alter the plant or its cost."""
    _, _, flat = _both(demand_growth_rate=0.0)
    _, _, grown = _both(demand_growth_rate=0.05)
    assert grown.initial_capital == flat.initial_capital
    assert grown.annual_operating == flat.annual_operating
    assert grown.annual_revenue == pytest.approx(flat.annual_revenue)
    assert grown.net_present_value > flat.net_present_value


def test_the_service_floor_binds_both_oracles():
    """A required service level must restrict the controller and the programme alike.

    Imposed on one alone, it raises that side's cost and leaves the other's, and the
    difference between them -- which this work reports as the price of the heuristic --
    quietly absorbs the price of a contractual requirement instead.
    """
    import inspect

    from microgrid_expansion.exact import certify, lower_bound

    assert "min_service_fraction" in inspect.getsource(lower_bound.cost_optimal_dispatch), (
        "the relaxed programme ignores the service floor the controller is held to")
    assert "min_service_fraction" in inspect.getsource(certify._evaluate_rule), (
        "the controller ignores the service floor")


def test_the_cache_key_carries_the_whole_site_description():
    """A site is what the user described, not the name they gave it."""
    from microgrid_expansion.instances import _site_fingerprint
    from microgrid_expansion.sites import Site

    small = Site(name="X", census={"HH1": 150}, latitude=7.0, longitude=2.0)
    large = Site(name="X", census={"HH1": 300}, latitude=7.0, longitude=2.0)
    moved = Site(name="X", census={"HH1": 150}, latitude=9.0, longitude=2.0)
    assert _site_fingerprint(small) != _site_fingerprint(large)
    assert _site_fingerprint(small) != _site_fingerprint(moved)


def test_a_sizing_reproduces_across_processes():
    """The same inputs must give the same load, run after run and process after process.

    A tool whose selling point is a certificate cannot answer a rerun with a different
    number. This failed for a long time and silently: the appliance library draws from
    Python's global random module and seeds it only when the seed is truthy, so this
    project's default seed of zero left it unseeded, and three runs of one sizing spread over
    a tenth of a per cent — wider than several of the differences the work reports. The cache
    hid it, returning the first answer to every repetition.
    """
    import subprocess
    import sys
    import textwrap

    programme = textwrap.dedent("""
        import numpy as np
        from microgrid_expansion.demand.generator import (
            _simulate_month, load_archetype_appliances)
        rng = np.random.default_rng(0)
        minutes = _simulate_month({"1": 12}, load_archetype_appliances(), 2025, 3,
                                  seed=0, rng=rng)
        print(f"TOTAL {minutes.sum():.6f}")
    """)
    runs = []
    for _ in range(3):
        done = subprocess.run([sys.executable, "-c", programme], capture_output=True,
                              text=True, timeout=900)
        lines = [line for line in done.stdout.splitlines()
                 if line.startswith("TOTAL")]
        assert lines, (
            "the simulation produced nothing; a test comparing empty outputs "
            f"would pass without checking anything. stderr: {done.stderr[-400:]}")
        runs.append(lines[0])
    assert float(runs[0].split()[1]) > 0, "simulated load is zero: nothing is compared"
    assert len(set(runs)) == 1, f"three runs, distinct results: {set(runs)}"


def test_a_plant_is_priced_against_the_grid_it_was_sized_with():
    """The search and the economics must see the same connection.

    The certification chooses a design knowing a grid is there; if the levelised cost is then
    computed without it, a plant chosen *because* it has a grid is charged as though it had
    none. That inverted the answer once: at sixty per cent availability the same design read
    0.2326 dollars a kilowatt-hour when priced with the connection and 0.3481 without, so
    connecting a village appeared to make its electricity dearer.
    """
    import inspect

    from microgrid_expansion.ui import engine

    source = inspect.getsource(engine.size_site)
    assert "_grid_link" in source, (
        "the sizing economics do not build the grid link")
    assert source.count("grid=link") >= 1, (
        "the pricing simulation ignores the grid the search assumed")
    assert "_grid_capital_usd_yr" in source, (
        "the connection capital does not enter the life-cycle cost")


def test_the_grid_displaces_the_generator_before_the_battery():
    """Stored energy is cheaper than imported energy, which is cheaper than diesel.

    The order decides what a connection is worth. Put the grid ahead of storage and it would
    idle a battery already paid for; put it behind the generating set and it would never
    displace the fuel it exists to displace.
    """
    import numpy as np

    from microgrid_expansion.exact.simulator import (BatteryModel, Capacities, GeneratorModel,
                                                     GridLink, simulate)

    hours = 48
    demand = np.full(hours, 5.0)
    yield_ = np.zeros(hours)                 # night throughout: no photovoltaic at all
    temperature = np.full(hours, 25.0)
    plant = Capacities(pv_kw=1.0, battery_kwh=40.0, inverter_kw=10.0, generator_kw=8.0,
                       architecture="dc")
    link = GridLink(available=np.ones(hours, dtype=bool), import_usd_kwh=0.11)
    run = simulate(demand, yield_, temperature, plant, BatteryModel(), GeneratorModel(),
                   grid=link)
    assert run.discharge_kw.sum() > 0, "storage should serve before the grid"
    assert run.grid_import_kw.sum() > 0, "the grid should serve when storage runs out"
    assert run.generator_kw.sum() == pytest.approx(0.0, abs=1e-6), (
        "the generator should not start while the grid is available")


def test_the_bound_survives_a_grid_connection():
    """Proposition 1 must hold whatever the plant is allowed to draw on.

    Adding the grid to the controller alone broke it outright: the controller could import at
    eleven cents while the relaxation it is compared against could not, so the anticipative
    optimum came out four thousand dollars a year *above* the rule it is meant to minorise
    and the reported price of the heuristic went to minus forty-two per cent. A negative gap
    is not a small error; it is the certificate saying the opposite of what it means.
    """
    import numpy as np

    from microgrid_expansion.exact.lower_bound import (CapacityBox, Economics,
                                                       cost_optimal_dispatch)
    from microgrid_expansion.exact.simulator import (BatteryModel, Capacities, GeneratorModel,
                                                     GridLink, simulate)

    hours = 24 * 14
    rng = np.random.default_rng(0)
    demand = 4.0 + 2.0 * np.sin(np.arange(hours) * 2 * np.pi / 24) ** 2
    yield_ = np.clip(np.sin((np.arange(hours) % 24 - 6) * np.pi / 12), 0, None) * 0.7
    temperature = np.full(hours, 28.0)
    live = rng.random(hours) < 0.9

    # Within the admission ceiling: an array above 1.3 kilowatts per kilowatt of conversion
    # is not wirable, and the relaxation answers that with infeasibility rather than a bound.
    plant = Capacities(pv_kw=10.0, battery_kwh=20.0, inverter_kw=8.0, generator_kw=8.0,
                       architecture="dc")
    link = GridLink(available=live, capacity_kw=10.0, import_usd_kwh=0.11)
    economics = Economics(voll_usd_kwh=1.0, grid_import_usd_kwh=0.11)

    from microgrid_expansion.instances import SiteYear
    instance = SiteYear(site="essai", year=2025, demand_kw=demand, specific_yield=yield_,
                        t_amb_c=temperature, usable_fraction=np.ones(hours),
                        self_discharge=np.zeros(hours), trajectory="central",
                        maturity_months=12, seed=0)

    battery, generator = BatteryModel(), GeneratorModel()
    run = simulate(demand, yield_, temperature, plant, battery, generator, grid=link)
    rule = run.operating_cost(generator, voll_usd_kwh=1.0)

    weights = np.full(hours, 8760.0 / hours)
    relaxed = cost_optimal_dispatch(instance, CapacityBox.at(plant), economics, battery,
                                    generator, relax_commitment=True, weights=weights,
                                    terminal="free", initial_soc_fraction=0.5, grid=link)
    scale = 8760.0 / hours
    assert (relaxed.value - relaxed.capital_cost) <= rule * scale + 1e-6, (
        "the lower bound exceeds the cost under the controller: proposition 1 is "
        "violated as soon as a grid is connected")
