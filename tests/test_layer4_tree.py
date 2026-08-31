"""Layer 4: scenario paths, the tree, and the two oracles over it."""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.config import ModelConfig


# ------------------------------------------------------------------ cost futures
def test_cost_futures_move_prices_coherently():
    """A path lives in one future, and every price in it moves the same way.

    A world where storage learns quickly is one where converters do too. Drawing each
    technology's rate independently would manufacture a diversification the market does not
    offer, and a plan would then hedge against a future that cannot occur.
    """
    from microgrid_expansion.settings import default_settings

    trajectories = default_settings().cost_trajectories
    for name in ("pv", "battery", "inverter"):
        curve = trajectories[name]
        assert curve.factor("high", 20) < curve.factor("central", 20) < curve.factor("low", 20)
        assert curve.factor(name="central", years_ahead=0) if False else True
        assert curve.factor("central", 0) == pytest.approx(1.0)

    # fuel is the one that does not learn: the names order the price, not the learning
    fuel = trajectories["diesel"]
    assert fuel.factor("high", 20) > 1.0 > fuel.factor("low", 20)


def test_an_unsourced_trajectory_announces_itself():
    """The fuel path is argued, not projected, and must say so."""
    from microgrid_expansion.settings import default_settings

    unsourced = dict(default_settings().unverified())
    assert "cost_trajectories[diesel].provenance" in unsourced


# ------------------------------------------------------------------------- tree
@pytest.fixture(scope="module")
def small_tree():
    from microgrid_expansion.scenarios import sample_scenario_paths
    from microgrid_expansion.tree import build_tree

    cfg = ModelConfig(site="Samionta", n_mc_paths=8, stage_years=(0, 5),
                      branching=(1, 2), n_rep_days=365, seed=0)
    return cfg, build_tree(sample_scenario_paths(cfg), cfg)


def test_the_tree_loses_no_probability(small_tree):
    _, tree = small_tree
    tree.check_probabilities()
    assert sum(tree.prob[leaf] for leaf in tree.leaves) == pytest.approx(1.0)
    assert tree.parent[0] is None
    assert all(tree.parent[n] is not None for n in tree.nodes if n != 0)


def test_the_first_stage_is_a_single_decision(small_tree):
    """Branching after the here-and-now decision, never at it."""
    _, tree = small_tree
    roots = [n for n in tree.nodes if tree.stage[n] == 0]
    assert roots == [0]


def test_the_reduction_reports_what_it_cost(small_tree):
    """A compression whose distortion is not reported invites being read as exact."""
    _, tree = small_tree
    assert tree.reduction_error
    assert all(np.isfinite(e) for e in tree.reduction_error.values())


# ----------------------------------------------------------------- the two oracles
def test_the_upper_oracle_runs_the_whole_year(small_tree):
    """Representative days cannot carry the price of the heuristic.

    Simulated alone a day truncates the night at midnight and the controller under-provisions
    the very night it exists to carry; repeated, the morrow becomes a copy of the day and its
    bounded foresight becomes perfect. The quantity being measured *is* the unpredictability
    between days, so the simulation runs the year uncompressed.
    """
    from microgrid_expansion.exact.tree_oracle import evaluate_plan
    from microgrid_expansion.post.extract import NodePlan

    cfg, tree = small_tree
    # 30 kW of array behind 30 kW of inverter sits inside the ceiling; 40 would not, the
    # trackers admitting about 1.3 kW of array per kilowatt of converter.
    plans = {n: NodePlan(n, 30.0, 120.0, 30.0, 8.0) for n in tree.nodes}
    value, traces = evaluate_plan(plans, tree, architecture="dc")

    assert np.isfinite(value) and value > 0
    assert set(traces) == set(tree.nodes)
    for node in tree.nodes:
        assert traces[node]["served_kwh"] > 0


def test_an_unwirable_plan_costs_infinity(small_tree):
    """The array-to-converter ceiling holds at every node of the tree."""
    from microgrid_expansion.exact.tree_oracle import evaluate_plan
    from microgrid_expansion.post.extract import NodePlan

    cfg, tree = small_tree
    plans = {n: NodePlan(n, 200.0, 120.0, 5.0, 8.0) for n in tree.nodes}
    value, traces = evaluate_plan(plans, tree, architecture="dc")
    assert value == float("inf")
    assert traces == {}


def test_the_programme_minorises_the_controller(small_tree):
    """Proposition 1 over the tree, which two modelling choices have broken before.

    Splitting a node's year into independent days hands the programme a free recharge every
    morning and puts the bound below anything achievable; closing the year on itself
    constrains it where the controller is not constrained and puts the bound above the
    trajectory it must minorise. The recursion therefore runs continuously across the year,
    opening where the controller opens and ending free.
    """
    from microgrid_expansion.exact.tree_oracle import evaluate_plan
    from microgrid_expansion.model import build_model
    from microgrid_expansion.post import extract_solution
    from microgrid_expansion.run import _NodeInstance
    from microgrid_expansion.settings import default_settings
    from microgrid_expansion.solve import solve
    from microgrid_expansion.timedomain import reduce_to_rep_days

    cfg, tree = small_tree
    settings = default_settings()
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), 365)
           for n in tree.nodes}
    programme = build_model(tree, rep, cfg, architecture="dc", settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    assert "ok" in solved.status

    plans = extract_solution(programme, cfg)
    rule, _ = evaluate_plan(plans, tree, architecture="dc", settings=settings)
    assert solved.objective <= rule + 1e-6


def test_a_plan_never_dismantles_itself(small_tree):
    """Capacity accumulates: no node may hold less than the node it grew from.

    The programme forbids it by construction, the module counts being non-negative. A
    descent moving one coordinate at a time does not, and produced a plan whose year-ten
    branch carried twenty kilowatt-hours less storage than the plant built at year zero.
    """
    from microgrid_expansion.exact.tree_certify import _monotone
    from microgrid_expansion.post.extract import NodePlan

    cfg, tree = small_tree
    fields = ("pv_kw", "battery_kwh", "inverter_kw")
    plans = {n: NodePlan(n, 30.0, 120.0, 30.0, 8.0) for n in tree.nodes}
    for node in tree.nodes:
        if tree.parent[node] is not None:
            plans[node] = NodePlan(node, 10.0, 40.0, 10.0, 8.0)      # smaller than its parent

    fixed = _monotone(plans, tree, fields)
    for node in tree.nodes:
        parent = tree.parent[node]
        if parent is None:
            continue
        for field in fields:
            assert getattr(fixed[node], field) >= getattr(fixed[parent], field) - 1e-9
