"""Holding the root still can only cost more, and the study has to show that it does.

The value of the stochastic solution is a difference between two numbers the same tree
produces: the expected cost with the root free, and the expected cost with the root held at
some plant chosen another way. Confining a variable cannot lower an optimum, so the second
is never below the first, and under the deterministic-equivalent programme that is a
theorem rather than a tendency. A study that reported a negative value of the stochastic
solution would be reporting a solver gap or a bug, and this is what tells the two apart.

The wait-and-see side of the ledger is deliberately not asserted. The cost of knowing the
growth is computed on three trees drawn with the weight on one trajectory each, and those
are different draws from the tree whose cost they are compared with. The ordering holds for
the expectations and not necessarily for four finite samples of them, so the study reports
whether it held rather than requiring it to.
"""
from __future__ import annotations

import pytest

from microgrid_expansion.config import ModelConfig
from microgrid_expansion.exact.tree_value import Case, TRAJECTORY_WEIGHTS, derive, run_case

TINY = dict(stage_years=(0, 5), branching=(1, 2), n_mc_paths=20, n_rep_days=2)


@pytest.fixture(scope="module")
def free_and_held():
    """One small tree, costed with its root free and then held at a smaller plant."""
    cfg = ModelConfig(**TINY)
    cfg.site = "Samionta"
    free = run_case(Case(name="free", weights=TRAJECTORY_WEIGHTS["thirds"]), cfg,
                    verbose=False)
    root = dict(free["programme"]["root"])
    # Deliberately not the plant the tree chose: a plant held at the optimum would satisfy
    # the inequality by equality and prove nothing. Two thirds of the storage is a plant a
    # developer might well build on the strength of a single trajectory.
    held = {**root, "battery_kwh": max(round(root["battery_kwh"] * 2 / 3), 1.0)}
    fixed = run_case(Case(name="held", weights=TRAJECTORY_WEIGHTS["thirds"],
                          fixed_root=held, fixed_root_from="two thirds of the storage"),
                     cfg, verbose=False)
    return free, fixed, held


def test_holding_the_root_cannot_lower_the_expected_cost(free_and_held) -> None:
    """Under the programme it is a theorem: a confined optimum is never the better one."""
    free, fixed, _ = free_and_held
    assert fixed["programme"]["expected_usd"] >= free["programme"]["expected_usd"] - 1e-6, (
        "the value of the stochastic solution came out negative under the exact oracle, "
        "which is a solver gap or a bug and never a finding")


def test_the_root_is_actually_held_where_it_was_put(free_and_held) -> None:
    """A constraint nobody applied would make the test above pass by accident.

    Held to the nearest module rather than to the figure asked for: a root is a count of
    modules and a plant between two of them cannot be built, so the box rounds. What has
    to be true is that it rounded the plant given and did not drift back to the plant the
    tree would have chosen.
    """
    from microgrid_expansion.settings import default_settings

    free, fixed, held = free_and_held
    unit = default_settings().battery.unit_kwh
    got = fixed["programme"]["root"]["battery_kwh"]
    assert abs(got - held["battery_kwh"]) <= unit / 2 + 1e-9, (
        f"the storage was pinned at {held['battery_kwh']} and came back {got}")
    assert got != free["programme"]["root"]["battery_kwh"], (
        "the pin put the root back where the tree wanted it, so it tests nothing")
    for part in ("pv_kw", "pv_ac_kw", "inverter_kw", "generator_kw"):
        assert fixed["programme"]["root"][part] == pytest.approx(held[part], abs=1e-6), (
            f"the programme moved {part}, which nothing asked it to move")


def test_the_study_reports_the_value_and_says_whether_the_ordering_held(free_and_held)\
        -> None:
    """The arithmetic a reader is handed, and the check that comes with it."""
    free, fixed, _ = free_and_held
    stored = {"cases": {"noise_seed0": free, "fixed_two_thirds": fixed}}
    derived = derive(stored)

    for oracle in ("programme", "automaton"):
        block = derived[oracle]
        entry = block["vss"]["two thirds of the storage"]
        assert entry["VSS"] == pytest.approx(entry["EEV"] - block["RP"], rel=1e-9)
        assert isinstance(entry["ordering_holds"], bool), (
            "the study must say whether the ordering held, not assume it")
    assert derived["programme"]["vss"]["two thirds of the storage"]["ordering_holds"]


def test_the_interface_prices_a_held_root_the_same_way_the_study_does() -> None:
    """One pinning, used twice, or the page and the study would answer differently.

    Pricing a plant the reader did not choose means two things at once: the programme must
    be confined to it, and the descent must be forbidden from walking away from it. Either
    one alone is a plausible-looking answer to a different question -- a programme pinned
    and a descent free prices the best plan near that plant, not that plant.
    """
    import inspect

    from microgrid_expansion.ui import engine

    source = inspect.getsource(engine.plan_expansion)
    assert "root_box=box" in source, "the programme is not confined to the plant given"
    assert "fixed_nodes=frozenset({0})" in source, (
        "the descent may walk the root away from the plant it was asked to price")
    assert "_box_of" in source, "the plant is not resolved onto the lattice"

    priced = inspect.getsource(engine.cost_if_built)
    assert "fixed_root=root" in priced, "the plant given never reaches the planner"


def test_a_priced_plant_is_never_mistaken_for_an_answer() -> None:
    """The page follows one job at a time, so what comes back has to be told apart.

    The sizing and this share a progress bar and a poller, and the poller ends by writing
    whatever came back into the result and drawing the sizing page from it. A priced plant
    answers about a plant already on that page; taken for a result it would replace the
    answer with the question, and the reader would be shown the certified plant as though
    the tree had chosen it.
    """
    from pathlib import Path as _Path

    from microgrid_expansion.ui import server

    static = _Path(server.__file__).parent / "static" / "app.js"
    script = static.read_text(encoding="utf-8")
    assert 'job.kind === "cost_if_built"' in script, (
        "the poller does not tell a priced plant from a sizing")
    assert 'registry.start("cost_if_built"' in _Path(server.__file__).read_text(
        encoding="utf-8"), "the job is started under a kind the page does not expect"
    assert "/api/cost-if-built" in _Path(server.__file__).read_text(encoding="utf-8")


def test_a_plant_sitting_on_the_converter_ceiling_can_still_be_held() -> None:
    """A certified plant is not always on the lattice, and rounding it up is infeasible.

    Where the array's split between the two buses is derived rather than searched, the part
    the hybrid inverter admits lands exactly on the ratio ceiling, which falls between two
    modules more often than not. Rounded to the nearest module it rises a quarter of a
    kilowatt above the ceiling it was sitting on, and the programme asked to hold the root
    there has no feasible plan -- not because the plant cannot be built, but because its
    arithmetic was off the grid. The field is rounded instead of its parts.
    """
    from microgrid_expansion.config import DC_AC_RATIO_MAX
    from microgrid_expansion.exact.certify import Lattice
    from microgrid_expansion.exact.first_stage import _box_of

    lattice = Lattice(pv_unit_kw=0.5, batt_unit_kwh=5.0, inv_unit_kw=2.5,
                      generator_ratings=(8.0, 12.0, 16.0),
                      n_pv=(0, 500), n_batt=(0, 200), n_inv=(1, 100))
    # The reference-year park certified on the fast trajectory: 1.3 kW of array per kW of
    # inverter is 61.75 kW, which is not a whole number of half-kilowatt modules.
    plant = {"pv_kw": 61.75, "pv_ac_kw": 46.75, "battery_kwh": 245.0,
             "inverter_kw": 47.5, "generator_kw": 12.0}
    box = _box_of(plant, lattice)

    on_battery_bus = box.n_pv[0] * lattice.pv_unit_kw
    inverter = box.n_inv[0] * lattice.inv_unit_kw
    assert on_battery_bus <= DC_AC_RATIO_MAX * inverter + 1e-9, (
        "the pinned array exceeds what its converter admits, so no plan can hold it")
    field = (box.n_pv[0] + box.n_pv_ac[0]) * lattice.pv_unit_kw
    assert field == pytest.approx(plant["pv_kw"] + plant["pv_ac_kw"], abs=1e-9), (
        "the field lost or gained capacity on the way onto the lattice")


def test_a_plant_its_converter_cannot_admit_is_refused_in_words() -> None:
    """Told here, where the plant is read, and not as an infeasible programme later."""
    from microgrid_expansion.exact.certify import Lattice
    from microgrid_expansion.exact.first_stage import _box_of

    lattice = Lattice(pv_unit_kw=0.5, batt_unit_kwh=5.0, inv_unit_kw=2.5,
                      generator_ratings=(8.0,), n_pv=(0, 500), n_batt=(0, 200),
                      n_inv=(1, 100))
    with pytest.raises(ValueError, match="no plan can hold a root there"):
        _box_of({"pv_kw": 100.0, "pv_ac_kw": 0.0, "battery_kwh": 100.0,
                 "inverter_kw": 10.0, "generator_kw": 8.0}, lattice)


def test_the_chains_reassemble_into_the_tree_they_were_carved_from() -> None:
    """The wait-and-see value is a decomposition, so its arithmetic has to close.

    Every node lies on the path of each leaf beneath it, and those leaves' probabilities
    sum to that node's own, so one plan costed over the tree and the same plan costed over
    the chains have to come to the same number. If they do not, the value of perfect
    information is being read as the gap between two differently weighted objects, and
    whatever the mismatch is would be reported as a thing worth knowing.
    """
    from microgrid_expansion.exact.tree_oracle import evaluate_plan
    from microgrid_expansion.exact.tree_value import _chain_of
    from microgrid_expansion.post.extract import NodePlan
    from microgrid_expansion.run import _NodeInstance
    from microgrid_expansion.scenarios import sample_scenario_paths, space_from_settings
    from microgrid_expansion.settings import default_settings
    from microgrid_expansion.timedomain import reduce_to_rep_days
    from microgrid_expansion.tree import build_tree

    cfg = ModelConfig(**TINY)
    cfg.site = "Samionta"
    settings = default_settings()
    tree = build_tree(sample_scenario_paths(cfg, space_from_settings(settings)), cfg)
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}

    # One plant, standing at every node, so that what is compared is the weighting and not
    # a difference between two plans. Converter enough for the field it carries.
    def plant(node: int) -> NodePlan:
        return NodePlan(node=node, pv_kw=40.0, battery_kwh=200.0, inverter_kw=40.0,
                        generator_kw=8.0, pv_ac_kw=0.0)

    architecture = settings.coupling.architectures()[0]
    over_the_tree, _ = evaluate_plan({n: plant(n) for n in tree.nodes}, tree, rep,
                                     architecture, settings)

    over_the_chains = 0.0
    for leaf in tree.leaves:
        chain, renumbered = _chain_of(tree, leaf)
        chain_rep = {renumbered[n]: rep[n] for n in tree.ancestors(leaf)}
        cost, _ = evaluate_plan({n: plant(n) for n in chain.nodes}, chain, chain_rep,
                                architecture, settings)
        over_the_chains += float(tree.prob[leaf]) * cost

    assert over_the_chains == pytest.approx(over_the_tree, rel=1e-9), (
        "the chains do not reassemble into the tree, so the wait-and-see value is "
        "weighted differently from the stochastic value it is subtracted from")
