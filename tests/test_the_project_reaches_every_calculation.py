"""What a project declares must reach the calculation that uses it.

``config`` derives its constants from ``default_settings()`` once, when the module is
imported. That is a convenience for keeping the symbols of the formulation short, and it
becomes a defect wherever a calculation reads one of those constants instead of the project
it was handed: the figure a developer entered on the page is then carried as far as the
settings object and dropped there, and the answer describes the default village.

It is not visible in the stored results, which use the defaults throughout, and that is
precisely why it needs tests. Six readings were wrong at once. A service life and a discount
rate did not reach the annuities of the tree, so the capital of a twelve-per-cent project was
recovered at eight. The two admission ratios, which the interface offers as fields, reached
neither the programme's ceiling nor the certificate's lattice. The price of a string inverter
was frozen in a cached function, so the second project certified in one session was priced
with the first one's converters. The double-conversion penalty did not reach the simulation,
the bound or the programme. Each test below changes one declared figure and asks the
calculation whether it noticed.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion import config
from microgrid_expansion.config import ModelConfig
from microgrid_expansion.settings import default_settings


def _costs(settings) -> dict:
    """Year-0 central prices of one project, as a tree node carries them."""
    from microgrid_expansion.scenarios.cost_paths import stage_costs
    from microgrid_expansion.scenarios.uncertainty_space import EconomicAxis

    return stage_costs(EconomicAxis(), 0, scenario="central", settings=settings)


# --------------------------------------------------------------- the annuities
def test_a_shorter_service_life_changes_the_annuity() -> None:
    """A field replaced at fifteen years costs more a year than one replaced at twenty-five."""
    from microgrid_expansion.model.economics import annualised_unit_costs

    settings = default_settings()
    shorter = default_settings()
    shorter.photovoltaic = replace(shorter.photovoltaic, lifetime_years=15)

    base = annualised_unit_costs(_costs(settings), "mixed", settings)
    moved = annualised_unit_costs(_costs(shorter), "mixed", shorter)

    expected = settings.photovoltaic.cost_usd_kw * (
        config.crf(settings.economics.discount_rate, 15)
        + settings.photovoltaic.om_rate)
    assert moved[0] == pytest.approx(expected)
    assert moved[0] > base[0]


def test_the_capital_is_recovered_at_the_rate_the_nodes_are_discounted_at() -> None:
    """One rate, not two: the nodes' and the capital's cannot differ.

    Discounting a node at twelve per cent while recovering its capital at eight is not a
    conservative approximation, it is two projects averaged.
    """
    from microgrid_expansion.model.economics import annualised_unit_costs

    dearer = default_settings()
    dearer.economics = replace(dearer.economics, discount_rate=0.12)

    annuities = annualised_unit_costs(_costs(dearer), "mixed", dearer)
    expected = dearer.battery.cost_usd_kwh * (
        config.crf(0.12, dearer.battery.lifetime_years) + dearer.battery.om_rate)
    assert annuities[1] == pytest.approx(expected)


def test_a_programme_refuses_two_discount_rates() -> None:
    """The configuration may not contradict the project it is solved against."""
    from microgrid_expansion.model.economics import check_one_discount_rate

    settings = default_settings()
    settings.economics = replace(settings.economics, discount_rate=0.12)
    with pytest.raises(ValueError, match="discount"):
        check_one_discount_rate(ModelConfig(discount_rate=0.08), settings)
    check_one_discount_rate(ModelConfig(discount_rate=0.12), settings)


def test_the_tree_records_the_rate_it_discounted_at() -> None:
    """A tree is evidence; what it was discounted at travels with it."""
    from microgrid_expansion.scenarios import sample_scenario_paths
    from microgrid_expansion.tree import build_tree

    cfg = ModelConfig(site="Samionta", n_mc_paths=4, stage_years=(0, 5),
                      branching=(1, 2), n_rep_days=2, seed=0, discount_rate=0.11)
    tree = build_tree(sample_scenario_paths(cfg), cfg)
    assert tree.discount_rate == pytest.approx(0.11)
    assert tree.disc[max(tree.nodes)] == pytest.approx(1.11 ** -5)


# ----------------------------------------------------- the admission ceilings
def _one_node_coords(cfg: ModelConfig):
    from microgrid_expansion.model.coords import Coords

    return Coords(node=np.array([0]), step=np.arange(24),
                  gsize=np.arange(len(cfg.gen_catalog_kw)), parent={0: None},
                  prob=pd.Series({0: 1.0}), disc=pd.Series({0: 1.0}),
                  n_years=pd.Series({0: 1}), hour_weight=np.ones(24))


def _ceiling_coefficient(settings, name: str) -> float:
    """The coefficient the programme puts on conversion in one admission ceiling."""
    import linopy

    from microgrid_expansion.model.investment_constraints import (
        add_investment_constraints)
    from microgrid_expansion.model.variables import add_variables

    cfg = ModelConfig()
    coords = _one_node_coords(cfg)
    model = linopy.Model()
    variables = add_variables(model, coords)
    add_investment_constraints(model, variables, coords, cfg, architecture="mixed",
                              settings=settings)
    coefficients = model.constraints[name].coeffs.values.ravel()
    return float(min(coefficients))


def test_a_changed_admission_ratio_changes_the_programme_ceiling() -> None:
    """The field a converter admits is a setting, and the ceiling is where it binds."""
    settings = default_settings()
    narrower = default_settings()
    narrower.coupling = replace(narrower.coupling, dc_ac_ratio_max=0.65,
                                ac_ratio_max=0.5)

    cfg = ModelConfig()
    assert _ceiling_coefficient(settings, "array_ratio_0") == pytest.approx(
        -settings.coupling.dc_ac_ratio_max * cfg.inv_unit_kw)
    assert _ceiling_coefficient(narrower, "array_ratio_0") == pytest.approx(
        -0.65 * cfg.inv_unit_kw)
    assert _ceiling_coefficient(narrower, "array_ratio_ac_0") == pytest.approx(
        -0.5 * cfg.inv_unit_kw)


def test_a_changed_admission_ratio_changes_the_certified_lattice() -> None:
    """The lattice the certificate proves over is drawn from the same two figures."""
    from microgrid_expansion.exact.certify import Lattice

    class _Stub:
        demand_kw = np.full(48, 10.0)
        specific_yield = np.tile(np.concatenate([np.zeros(6), np.full(12, 0.5),
                                                 np.zeros(6)]), 2)

    settings = default_settings()
    narrower = default_settings()
    narrower.coupling = replace(narrower.coupling, dc_ac_ratio_max=0.65)

    wide = Lattice.around(_Stub(), settings, architecture="mixed")
    tight = Lattice.around(_Stub(), narrower, architecture="mixed")

    assert wide.ratio_max == pytest.approx(settings.coupling.dc_ac_ratio_max)
    assert tight.ratio_max == pytest.approx(0.65)
    n_inv = 10
    admitted_wide = max(n for n in range(0, 400)
                        if wide.admits(n, n_inv))
    admitted_tight = max(n for n in range(0, 400)
                         if tight.admits(n, n_inv))
    assert admitted_tight < admitted_wide


# ------------------------------------------------- the price of a string inverter
def test_a_changed_string_inverter_price_changes_what_a_design_costs() -> None:
    """And it changes it in the same session, which a cached function forbade.

    The annual cost of a string inverter was memoised at module level, keyed on nothing.
    The first project certified in a process fixed it for every project after, which is the
    shape of defect a server makes routine: two villages sized one after another, the second
    priced with the first one's converters.
    """
    from microgrid_expansion.exact.lower_bound import Economics

    cheap = default_settings()
    dear = default_settings()
    dear.coupling = replace(dear.coupling, string_inverter_cost_usd_kw=3.0 *
                            cheap.coupling.string_inverter_cost_usd_kw)

    first = Economics.from_settings(cheap, architecture="mixed")
    second = Economics.from_settings(dear, architecture="mixed")
    assert second.string_inverter_annualised() == pytest.approx(
        3.0 * first.string_inverter_annualised())
    # And again in the other order, which is what a cache would have broken.
    assert Economics.from_settings(cheap, architecture="mixed"
                                   ).string_inverter_annualised() == pytest.approx(
        first.string_inverter_annualised())


def test_the_certificates_prices_are_the_projects_prices() -> None:
    """Every price the certificate charges comes from the settings it was given."""
    from microgrid_expansion.exact.lower_bound import Economics

    dearer = default_settings()
    dearer.photovoltaic = replace(dearer.photovoltaic, cost_usd_kw=2.0 *
                                  dearer.photovoltaic.cost_usd_kw)
    dearer.economics = replace(dearer.economics, discount_rate=0.12)

    economics = Economics.from_settings(dearer, architecture="mixed")
    a_pv, _, _, _ = economics.annualised()
    expected = dearer.photovoltaic.cost_usd_kw * (
        config.crf(0.12, dearer.photovoltaic.lifetime_years)
        + dearer.photovoltaic.om_rate)
    assert a_pv == pytest.approx(expected)


# --------------------------------------------- the double-conversion penalty
def _two_days() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A plant that must store everything it makes: no load while the sun is up."""
    night = np.full(12, 4.0)
    day = np.zeros(12)
    demand = np.tile(np.concatenate([day, night]), 2)
    sun = np.tile(np.concatenate([np.full(12, 0.6), np.zeros(12)]), 2)
    return demand, sun, np.full(48, 25.0)


def test_the_double_conversion_penalty_reaches_the_simulation() -> None:
    """A field on the load's bus pays a second conversion, at the declared efficiency.

    The plant below has no generator and starts empty, so every kilowatt-hour the night
    consumes has crossed the load's bus twice: what the penalty takes is what the village
    does without.
    """
    from microgrid_expansion.exact.simulator import BatteryModel, Capacities, simulate

    demand, sun, temperature = _two_days()
    empty = BatteryModel(initial_soc_fraction=0.0)
    design = Capacities(pv_kw=0.0, battery_kwh=60.0, inverter_kw=20.0,
                        generator_kw=0.0, pv_ac_kw=5.0, architecture="mixed")
    lossy = default_settings()
    lossy.coupling = replace(lossy.coupling, ac_double_conversion_efficiency=0.5)

    kind = simulate(demand, sun, temperature, design, empty)
    harsh = simulate(demand, sun, temperature, design, empty,
                     coupling=lossy.coupling)
    assert float(harsh.unserved_kw.sum()) > float(kind.unserved_kw.sum()) + 1.0


# ------------------------------------------------------- the generating sets
def test_the_generating_sets_a_project_catalogues_are_the_ones_it_is_costed_with() -> None:
    """The last cache that answered about the default village.

    ``_generator_models`` was memoised on the fuel price alone and built its models from
    ``default_settings()``, so the first catalogue certified in a session was the catalogue
    every later project got. It matters in exactly the dimension the search arbitrates
    over: a quarter more fuel per kilowatt-hour separates the ends of this catalogue, and
    the generating set is chosen from a discrete list where that quarter decides.
    """
    from microgrid_expansion.exact.certify import _generator_catalogue

    settings = default_settings()
    thirsty = default_settings()
    thirsty.generators = tuple(
        replace(spec, fuel_l_per_h={load: 1.6 * litres
                                    for load, litres in spec.fuel_l_per_h.items()})
        for spec in thirsty.generators)

    base = _generator_catalogue(settings.generators, 1.2)
    moved = _generator_catalogue(thirsty.generators, 1.2)
    assert set(base) == set(moved), "the two catalogues no longer offer the same ratings"
    for rating in sorted(base):
        assert base[rating] != moved[rating], (
            f"the {rating:.0f} kW set is costed with the same fuel curve under both "
            "projects, so the catalogue did not reach the evaluation")
        assert (moved[rating].efficiency(0.75)
                < base[rating].efficiency(0.75)), rating


def test_two_projects_in_one_session_keep_their_own_generating_sets() -> None:
    """The defect was the cache, so the order of the two calls is the test."""
    from microgrid_expansion.exact.certify import _generator_catalogue

    settings = default_settings()
    thirsty = default_settings()
    thirsty.generators = tuple(
        replace(spec, fuel_l_per_h={load: 1.6 * litres
                                    for load, litres in spec.fuel_l_per_h.items()})
        for spec in thirsty.generators)

    first = dict(_generator_catalogue(thirsty.generators, 1.2))
    second = _generator_catalogue(settings.generators, 1.2)
    again = _generator_catalogue(thirsty.generators, 1.2)
    assert first != second
    assert again == first, "the catalogue asked for second was served to the first"
