"""A path of the tree is one village: its regime is held, and the root's plant meets them all.

The fan nested each stage's medoids of the whole ensemble below every node of the stage
before, so along one of its paths a village could grow quickly to year five, slowly to year
ten and quickly again. The persistent tree branches over regimes -- the connection
trajectory, the growth trajectory and the cost future -- at the first milestone after the
root and holds each below its branch, and the root's own span is operated under every
regime by nodes that hold its plant and buy nothing.

Every ensemble here is synthetic and small, so that nothing is simulated: the property under
test is how outcomes are nested, not what the generator draws.
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest

from microgrid_expansion.config import ModelConfig
from microgrid_expansion.scenarios.assemble import AxisDraw, ScenarioPath
from microgrid_expansion.tree import build_tree
from microgrid_expansion.tree import reduce as reduce_

HOURS = 8760
PLATEAU = {"census": 1.0, "low": 0.3, "central": 0.6, "high": 0.9}
GROWTH = {"slow": 0.01, "central": 0.03, "fast": 0.06}


def _ensemble(n: int = 120, stage_years=(0, 5, 10, 15, 20), seed: int = 1,
              connections=("low", "central", "high"),
              growths=("slow", "central", "fast"),
              costs=("low", "central", "high"), grid_hazard: float = 0.0,
              households: int = 30) -> list[ScenarioPath]:
    """Paths drawn the way the sampler draws them: a regime held, the rest per stage."""
    from microgrid_expansion.scenarios.cost_paths import stage_costs
    from microgrid_expansion.scenarios.uncertainty_space import UncertaintySpace

    economic = UncertaintySpace().economic
    rng = np.random.default_rng(seed)
    hour = np.arange(HOURS) % 24
    shape = 0.5 + 0.8 * np.exp(-((hour - 20) / 2.5) ** 2)
    sun = np.clip(np.sin((hour - 6) / 12 * np.pi), 0.0, None)
    paths = []
    for pid in range(n):
        connection = connections[int(rng.integers(len(connections)))]
        growth = growths[int(rng.integers(len(growths)))]
        future = costs[int(rng.integers(len(costs)))]
        arrival = None
        draws, demand, pv_unit, t_amb = [], {}, {}, {}
        for index, year in enumerate(stage_years):
            if (arrival is None and grid_hazard > 0.0 and index > 0
                    and rng.random() < grid_hazard):
                arrival = index
            age = 12 + 12 * year
            connected = (households if connection == "census" else
                         int(round(households * PLATEAU[connection]
                                   * (1.0 - np.exp(-age / 30.0)))))
            level = 0.05 * connected * (1.0 + GROWTH[growth]) ** year
            demand[year] = level * shape * (1.0 + 0.2 * rng.random(HOURS)) \
                * (1.0 + 0.05 * rng.standard_normal())
            pv_unit[year] = sun * (0.75 + 0.1 * rng.random()) * (1.0 + 0.1 * rng.random(HOURS))
            t_amb[year] = 25.0 + 6.0 * sun + 0.02 * year
            draws.append(AxisDraw(
                year, "ssp245", 0.0, stage_costs(economic, year, scenario=future),
                trajectory=growth, cost_scenario=future,
                grid_connected=arrival is not None and index >= arrival,
                connection=connection, village_age_months=age,
                connected_households=connected))
        paths.append(ScenarioPath(pid, draws, demand, pv_unit, t_amb))
    return paths


def _persistent(stage_years=(0, 5, 10, 15, 20), **fields) -> ModelConfig:
    fields.setdefault("regime_fan", (1,) * len(stage_years))
    return ModelConfig(stage_years=stage_years, branching=(1,) + (2,) * (len(stage_years) - 1),
                       tree_mode="persistent", n_rep_days=2, **fields)


def _regime(data) -> tuple[str, str, str]:
    return (data.connection, data.trajectory, data.cost_scenario)


# ---------------------------------------------------------------- persistence
def test_a_tree_path_keeps_its_regime() -> None:
    """Constant from the first milestone, the stock never falling, the line never leaving.

    Twenty-seven regimes reduced to nine, a fan within each, and a grid that may arrive at
    any milestone, so that the grid split of the construction is exercised as well.
    """
    paths = _ensemble(n=150, grid_hazard=0.3)
    tree = build_tree(paths, _persistent(regime_fan=(1, 2, 1, 2, 1)))
    assert tree.tree_mode == "persistent"
    arrived = set()
    for leaf in tree.leaves:
        chain = tree.ancestors(leaf)
        regimes = {_regime(tree.node_data[n]) for n in chain if tree.parent[n] is not None}
        assert len(regimes) == 1, f"the path to leaf {leaf} changes regime"
        operating = [n for n in chain if tree.operates(n)]
        assert [tree.stage[n] for n in operating] == list(range(5))
        stock = [tree.node_data[n].connected_households for n in operating]
        assert stock == sorted(stock), f"the connected stock falls along leaf {leaf}"
        ages = [tree.node_data[n].village_age_months for n in operating]
        assert all(b > a for a, b in zip(ages, ages[1:])), "the village does not age"
        grid = [tree.node_data[n].grid_connected for n in chain]
        assert grid == sorted(grid), f"the grid leaves again along leaf {leaf}"
        arrived.update(n for n in chain if tree.node_data[n].grid_connected)
    assert arrived, "no path of the tree saw the grid arrive, so the split went untested"
    assert tree.distortion["persistence_violations"] == 0


def test_a_single_regime_tree_is_the_fan_tree() -> None:
    """With one regime there is nothing to hold, and the two builders must agree."""
    paths = _ensemble(n=40, stage_years=(0, 5, 10), connections=("census",),
                      growths=("central",), costs=("central",))
    # The fan with its features centred, as the persistent tree always has them: one regime
    # is one cost future, whose prices do not vary, and the two scalings differ exactly there.
    fan = build_tree(paths, ModelConfig(stage_years=(0, 5, 10), branching=(1, 2, 2),
                                        centre_features=True))
    held = build_tree(paths, _persistent(stage_years=(0, 5, 10), regime_fan=(1, 2, 2),
                                         root_period="root"))
    assert held.nodes == fan.nodes
    for attribute in ("parent", "stage", "prob", "disc", "n_years", "children"):
        assert getattr(held, attribute) == getattr(fan, attribute), attribute
    assert held.leaves == fan.leaves and held.reduction_error == fan.reduction_error
    for n in fan.nodes:
        a, b = fan.node_data[n], held.node_data[n]
        for array in ("demand", "pv_unit", "t_amb"):
            assert np.array_equal(getattr(a, array), getattr(b, array))
        assert a.costs == b.costs and _regime(a) == _regime(b)


def test_moving_the_root_period_below_it_keeps_the_programme_value() -> None:
    """With one regime, the operating-only node is the root's operation moved one node down.

    It carries the root's span with probability one, on the root's own outcome, and holds
    the root's plant; the root keeps the investment and operates nothing. The programme is
    therefore the same programme, and its value the same value.
    """
    from microgrid_expansion.model import build_model
    from microgrid_expansion.run import _NodeInstance
    from microgrid_expansion.settings import default_settings
    from microgrid_expansion.solve import solve
    from microgrid_expansion.timedomain import reduce_to_rep_days

    settings = default_settings()
    paths = _ensemble(n=30, stage_years=(0, 5), connections=("census",),
                      growths=("central",), costs=("central",))
    fan_cfg = ModelConfig(stage_years=(0, 5), branching=(1, 2), n_rep_days=2,
                          centre_features=True)
    values = []
    for cfg in (fan_cfg, _persistent(stage_years=(0, 5), regime_fan=(1, 2))):
        tree = build_tree(paths, cfg)
        rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), 2)
               for n in tree.nodes}
        solved = solve(build_model(tree, rep, cfg, architecture="dc", settings=settings),
                       settings, solver=cfg.solver)
        values.append(solved.objective)
    assert values[1] == pytest.approx(values[0], rel=1e-6)


def test_regime_masses_are_the_ensemble_frequencies() -> None:
    """A branch weighs what the paths of its cluster weigh, and no more."""
    paths = _ensemble(n=120)
    table = reduce_.regime_table(paths, (0, 5, 10, 15, 20))
    assert len(table.regimes) > 5, "the ensemble does not hold enough regimes to reduce"
    for branches in (5, len(table.regimes)):
        tree = build_tree(paths, _persistent(regime_branches=branches))
        reduction = reduce_.reduce_regimes(table, branches)
        held = [n for n in tree.children[0]]
        assert len(held) == len(reduction.representatives)
        for b, node in enumerate(held):
            share = sum(len(table.members[j]) for j in range(len(table.regimes))
                        if reduction.assignment[j] == b) / len(paths)
            assert tree.prob[node] == pytest.approx(share)
            assert _regime(tree.node_data[node]) == table.regimes[reduction.representatives[b]]
        assert sum(tree.prob[leaf] for leaf in tree.leaves) == pytest.approx(1.0)


# ------------------------------------------------------- the root's own span
@pytest.fixture(scope="module")
def three_regimes():
    from microgrid_expansion.run import _NodeInstance
    from microgrid_expansion.settings import default_settings
    from microgrid_expansion.timedomain import reduce_to_rep_days

    settings = default_settings()
    paths = _ensemble(n=30, stage_years=(0, 5), connections=("census",),
                      costs=("central",))
    cfg = _persistent(stage_years=(0, 5))
    tree = build_tree(paths, cfg)
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), 2)
           for n in tree.nodes}
    return cfg, settings, tree, rep


def test_operating_only_nodes_do_not_invest(three_regimes) -> None:
    """Their modules are fixed at zero, so they stand on the root's plant, in both oracles."""
    from microgrid_expansion.exact.tree_certify import certify_tree
    from microgrid_expansion.model import build_model
    from microgrid_expansion.post import extract_solution
    from microgrid_expansion.solve import solve

    cfg, settings, tree, rep = three_regimes
    held = [n for n in tree.nodes if not tree.invests_at(n)]
    assert held == tree.children[0] and len(held) == 3
    assert not tree.operates(0) and all(tree.operates(n) for n in tree.nodes if n != 0)
    assert all(tree.n_years[n] == 5 and tree.stage[n] == 0 for n in held)

    programme = build_model(tree, rep, cfg, architecture="dc", settings=settings)
    names = set(programme.model.constraints)
    assert {f"holds_b_pv_{n}" for n in held} <= names
    assert "balance_0" not in names, "the root operates although it stands for no year"
    solved = solve(programme, settings, solver=cfg.solver)
    plans = extract_solution(programme, cfg, settings)
    fields = ("pv_kw", "pv_ac_kw", "battery_kwh", "inverter_kw", "generator_kw")
    for n in held:
        for name in ("b_pv", "b_batt", "b_inv", "b_pv_ac"):
            assert float(programme.variables[name].solution.sel(node=n)) == 0.0
        assert all(getattr(plans[n], f) == getattr(plans[0], f) for f in fields)

    certificate = certify_tree(plans, tree, rep, solved.bound, architecture="dc",
                               settings=settings, max_rounds=2, scales=(1,), workers=2,
                               verbose=False)
    for n in held:
        assert all(getattr(certificate.plans[n], f) == getattr(certificate.plans[0], f)
                   for f in fields), "the descent moved an operating-only node"


def test_a_flat_channel_does_not_decide_the_medoid() -> None:
    """Within one cost future the prices do not vary, and the medoid must not see them.

    Their spread is a few units of rounding rather than zero. Divided by it, the prices became
    a constant of order 1e15, every distance of the expanded form cancelled to zero, and the
    reduction returned the first outcome of the list whatever the others were. The centred
    scaling returns the outcome nearest to all the others, found here by brute force.
    """
    # Thirty outcomes at year 0, priced at the project's 151.2 $/kW: whether a column of one
    # value has a spread of exactly zero depends on the value and on how many there are, and
    # here it does not.
    paths = _ensemble(n=30, stage_years=(0, 5), connections=("census",),
                      growths=("central",), costs=("central",))
    raw = reduce_.raw_stage_features(paths, 0)
    assert 0.0 < raw[:, 6].std() < 1e-9, "the price channel is not flat in floating point"
    features, _ = reduce_._scaled(raw, centred=True)
    gaps = np.linalg.norm(features[:, None, :] - features[None, :, :], axis=2)
    nearest = int(np.argmin(gaps.sum(axis=0)))
    assert nearest != 0, "the brute-force medoid is the first outcome, so this proves nothing"
    assert reduce_.reduce_stage(paths, 0, 1, centred=True).representatives == [nearest]
    assert reduce_.reduce_stage(paths, 0, 1, centred=False).representatives == [0]


# ------------------------------------------------------------------ distortion
def test_the_distortion_report_is_complete() -> None:
    """Five measures in both nestings, on one ensemble, and none lost in the persistent one."""
    paths = _ensemble(n=120)
    fan = build_tree(paths, ModelConfig(n_rep_days=2))
    held = build_tree(paths, _persistent())
    measures = ("stage", "regime", "coverage", "plausibility", "persistence_violations")
    for tree in (fan, held):
        assert set(measures) <= set(tree.distortion)
        assert set(tree.distortion["stage"]) == {0, 5, 10, 15, 20}
        assert tree.distortion["coverage"] >= 0.0 and tree.distortion["plausibility"] >= 0.0
        assert tree.reduction_error
    assert held.distortion["persistence_violations"] == 0
    assert held.distortion["regime"] is not None and held.distortion["regime"] >= 0.0
    # The fan's stage measure is its reduction error, read on the same scale.
    for year, error in fan.reduction_error.items():
        assert fan.distortion["stage"][year] == pytest.approx(error)
    # Twenty-seven regimes over sixteen leaves of three, two, two and two medoids: some of
    # the fan's paths cannot keep one regime.
    assert fan.distortion["persistence_violations"] > 0


def test_a_tree_of_every_regime_has_no_regime_distortion() -> None:
    paths = _ensemble(n=60, connections=("census",), costs=("central",))
    tree = build_tree(paths, _persistent())
    assert tree.distortion["regime"] == 0.0
    assert len(tree.children[0]) == tree.distortion["regimes"] == 3


# ------------------------------------------------------------- the node's year
def test_the_last_year_moves_only_the_demand(monkeypatch) -> None:
    """Under ``last`` a node's demand is the village at the end of its span, and only that.

    The demand is replaced by a marker of the year it was asked for, and the draw it takes
    from the stream is kept, so the yield, the temperature and the prices of the two runs can
    be compared value for value.
    """
    from microgrid_expansion.scenarios import assemble, demand_paths

    def marker(axis, stage_year, rng, **kwargs):
        rng.integers(0, 4)
        return np.full(HOURS, float(kwargs["base_maturity_months"] + 12 * stage_year))

    monkeypatch.setattr(demand_paths, "simulate_stage_demand", marker)
    runs = {}
    for year in ("first", "last"):
        cfg = ModelConfig(stage_years=(0, 5, 10), branching=(1, 2, 2), n_mc_paths=3,
                          node_year=year, horizon_years=25)
        runs[year] = assemble.sample_scenario_paths(cfg)
    spans = {0: 5, 5: 5, 10: 15}
    for first, last in zip(runs["first"], runs["last"]):
        for a, b in zip(first.draws, last.draws):
            y = a.stage_year
            assert a.village_age_months == 12 + 12 * y
            assert b.village_age_months == 12 + 12 * (y + spans[y] - 1)
            assert np.all(first.demand[y] == a.village_age_months)
            assert np.all(last.demand[y] == b.village_age_months)
            assert np.array_equal(first.pv_unit[y], last.pv_unit[y])
            assert np.array_equal(first.t_amb[y], last.t_amb[y])
            assert a.costs == b.costs and a.resource == b.resource

    with pytest.raises(ValueError, match="two operating years"):
        ModelConfig(node_year="both").validate()


def test_the_tree_shapes_are_refused_when_they_do_not_fit() -> None:
    for wrong in (dict(tree_mode="ladder"), dict(node_year="middle"),
                  dict(tree_mode="persistent", regime_fan=(2, 1, 1, 1, 1)),
                  dict(tree_mode="persistent", regime_fan=(1, 1)),
                  dict(tree_mode="persistent", root_period="nobody")):
        with pytest.raises(ValueError):
            ModelConfig(**wrong).validate()


@pytest.mark.parametrize("branches, fan, nodes", [
    (9, (1, 1, 1, 1, 1), 46), (6, (1, 1, 1, 1, 1), 31), (9, (1, 1, 2, 1, 1), 73),
    (3, (1, 1, 2, 2, 2), 49)])
def test_the_tree_has_the_size_section_9_6_gives(branches, fan, nodes) -> None:
    """``1 + R + R (f1 + f1 f2 + f1 f2 f3 + f1 f2 f3 f4)``, all but the root operating."""
    paths = _ensemble(n=400, seed=3)
    tree = build_tree(paths, _persistent(regime_branches=branches, regime_fan=fan))
    assert len(tree.nodes) == nodes
    assert sum(1 for n in tree.nodes if tree.operates(n)) == nodes - 1
    products = list(itertools.accumulate(fan[1:], lambda a, b: a * b))
    assert nodes == 1 + branches + branches * sum(products)
