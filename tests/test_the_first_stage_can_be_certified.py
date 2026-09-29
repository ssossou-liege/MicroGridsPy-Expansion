"""The year-0 plant, and the machinery that would prove it optimal.

The reference year is certified by exhaustion. A plan over the tree cannot be: it is a
capacity vector at each of forty-six nodes, and the product of forty-six lattices is not a
set anyone enumerates. But the plan is not what is decided -- only the root is bought -- so
the object to certify is a single design, and that is a problem the size of the reference
year's.

These tests hold the three pieces that make it possible: a programme that can be confined
to a box of year-0 plants, a costless bound that never exceeds what that programme finds,
and a descent that leaves the root where it was put.
"""
from __future__ import annotations

import pytest

from microgrid_expansion.config import ModelConfig
from microgrid_expansion.exact.certify import Lattice
from microgrid_expansion.exact.first_stage import (
    FirstStageCertificate,
    FreeBound, RootBox, TreeWeights, _box_of, _root_of, free_bound_for)
from microgrid_expansion.run import _NodeInstance
from microgrid_expansion.scenarios import sample_scenario_paths
from microgrid_expansion.settings import default_settings
from microgrid_expansion.timedomain import reduce_to_rep_days
from microgrid_expansion.tree import build_tree


@pytest.fixture(scope="module")
def tiny():
    """Three nodes and two representative days: the shape, not the size, is what is tested."""
    cfg = ModelConfig(stage_years=(0, 5), branching=(1, 2), n_mc_paths=20, n_rep_days=2)
    settings = default_settings()
    tree = build_tree(sample_scenario_paths(cfg), cfg)
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    lattice = Lattice.around(_NodeInstance(tree.node_data[0], settings), settings,
                             architecture="dc")
    return cfg, settings, tree, rep, lattice


# ------------------------------------------------------------------ the box
def test_splitting_a_box_loses_no_plant(tiny) -> None:
    """A branch that drops a design drops the proof with it."""
    _, _, _, _, lattice = tiny
    box = RootBox.around(lattice)
    seen = box.n_points
    left, right = box.split()
    assert left.n_points + right.n_points == seen
    assert left.n_pv[1] < right.n_pv[0] or left.n_batt[1] < right.n_batt[0] \
        or left.n_inv[1] < right.n_inv[0] or left.n_pv_ac[1] < right.n_pv_ac[0] \
        or set(left.generator_ratings).isdisjoint(right.generator_ratings), \
        "the two halves overlap, so a design would be examined twice"


def test_splitting_terminates_at_a_single_plant(tiny) -> None:
    """Split enough times and a box must become one design, or the search never ends."""
    _, _, _, _, lattice = tiny
    box = RootBox.around(lattice)
    for _ in range(200):
        if box.is_singleton:
            break
        box = box.split()[0]
    assert box.is_singleton, "splitting did not converge to a single plant"
    assert box.n_points == 1


def test_a_box_of_one_names_the_plant_it_holds(tiny) -> None:
    _, _, _, _, lattice = tiny
    root = {"pv_kw": 10.0, "pv_ac_kw": 0.0, "battery_kwh": 25.0,
            "inverter_kw": 5.0, "generator_kw": 8.0}
    box = _box_of(root, lattice)
    assert box.is_singleton
    low = box.corner(low=True)
    assert low["b_pv"] * lattice.pv_unit_kw == pytest.approx(root["pv_kw"])
    assert low["b_batt"] * lattice.batt_unit_kwh == pytest.approx(root["battery_kwh"])
    assert low["generator_kw"] == root["generator_kw"]


# ------------------------------------------------------------------ the costless bound
def test_the_costless_bound_never_exceeds_the_programme(tiny) -> None:
    """A bound that overstates prunes the optimum, which is worse than no bound at all."""
    from microgrid_expansion.model import build_model
    from microgrid_expansion.solve import solve

    cfg, settings, tree, rep, lattice = tiny
    free = free_bound_for(tree, rep, lattice, settings, "dc")

    whole = RootBox.around(lattice)
    programme = build_model(tree, rep, cfg, architecture="dc", settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    assert free.of(whole) <= solved.bound + 1e-6, (
        "the free bound exceeds the programme over the whole lattice")

    # And over a restricted box, where the capital term does the work.
    tall = RootBox(n_pv=(lattice.n_pv[1] // 2, lattice.n_pv[1]), n_batt=lattice.n_batt,
                   n_inv=lattice.n_inv, n_pv_ac=(0, 0),
                   generator_ratings=tuple(lattice.generator_ratings))
    confined = build_model(tree, rep, cfg, architecture="dc", settings=settings,
                           root_box=tall)
    assert free.of(tall) <= solve(confined, settings, solver=cfg.solver).bound + 1e-6


def test_the_capital_floor_is_charged_over_the_whole_horizon(tiny) -> None:
    """A module bought at the root is paid for at every node after it.

    This is why the floor bites so much harder on a tree than on a single year, and it is
    the whole reason a first-stage search is tractable at all.
    """
    _, _, tree, _, _ = tiny
    weights = TreeWeights.of(tree)
    assert weights.total > weights.root, "the horizon weighs no more than its first stage"
    assert weights.total == pytest.approx(sum(weights.per_node.values()))


# ------------------------------------------------------------------ confining the root
def test_confining_the_root_can_only_raise_the_programme(tiny) -> None:
    """A restriction that lowered the objective would not be a restriction."""
    from microgrid_expansion.model import build_model
    from microgrid_expansion.solve import solve

    cfg, settings, tree, rep, lattice = tiny
    free = solve(build_model(tree, rep, cfg, architecture="dc", settings=settings),
                 settings, solver=cfg.solver)
    forced = RootBox(n_pv=(lattice.n_pv[1] - 2, lattice.n_pv[1]), n_batt=lattice.n_batt,
                     n_inv=lattice.n_inv, n_pv_ac=(0, 0),
                     generator_ratings=tuple(lattice.generator_ratings))
    confined = solve(build_model(tree, rep, cfg, architecture="dc", settings=settings,
                                 root_box=forced), settings, solver=cfg.solver)
    assert confined.objective >= free.objective - 1e-6


def test_the_descent_leaves_a_pinned_root_where_it_was_put(tiny) -> None:
    """Pinning the root is what makes the descent an oracle for one year-0 plant."""
    from microgrid_expansion.exact.tree_certify import certify_tree
    from microgrid_expansion.model import build_model
    from microgrid_expansion.post import extract_solution
    from microgrid_expansion.solve import solve

    cfg, settings, tree, rep, _ = tiny
    programme = build_model(tree, rep, cfg, architecture="dc", settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    plans = extract_solution(programme, cfg)
    before = _root_of(plans, tree)

    certificate = certify_tree(plans, tree, rep, solved.bound, architecture="dc",
                               settings=settings, max_rounds=2,
                               fixed_nodes=frozenset({min(tree.nodes)}), verbose=False)
    after = _root_of(certificate.plans, tree)
    assert after == before, "the descent moved the root it was told to leave alone"


# ------------------------------------------------------------------ the solver's own bound
def test_a_bound_is_taken_from_the_solver_and_not_from_its_incumbent(tiny) -> None:
    """A mixed-integer solve stops at a tolerance; its incumbent is not a lower bound.

    The two differ by around a hundredth of a per cent on this tree -- small enough to pass
    unnoticed, large enough to prune the box the optimum was in.
    """
    from microgrid_expansion.model import build_model
    from microgrid_expansion.solve import solve

    cfg, settings, tree, rep, _ = tiny
    solved = solve(build_model(tree, rep, cfg, architecture="dc", settings=settings),
                   settings, solver=cfg.solver)
    assert solved.bound <= solved.objective + 1e-9, (
        "the value used as a lower bound sits above the incumbent")
    if solved.dual_bound == solved.dual_bound:            # a dual bound was available
        assert solved.bound == pytest.approx(min(solved.dual_bound, solved.objective))


# ------------------------------------------------------------------ what a proof requires
def test_a_plant_the_descent_cannot_exclude_is_not_counted_as_excluded() -> None:
    """The descent bounds a rooted plan from above; it never bounds one from below.

    So a plant whose programme bound sits below the incumbent may still beat it, and a
    search that drops such a plant reports a proof it has not got. This is the hinge of the
    whole scheme: closing these is closing the descent's own gap, and the certificate says
    how many are left rather than rounding them away.
    """
    import inspect

    from microgrid_expansion.exact import first_stage

    source = inspect.getsource(first_stage.certify_first_stage)
    assert "unresolved.append" in source, (
        "a single plant that survives its bound is dropped rather than carried")
    assert "proven = not open_bounds" in source, (
        "the proof does not account for the plants still open")
    assert "unresolved" in inspect.getsource(first_stage.FirstStageCertificate), (
        "the certificate does not report what it failed to settle")


def test_the_certificate_reports_no_proof_while_anything_is_open() -> None:
    certificate = FirstStageCertificate(
        root={"pv_kw": 1.0}, z_rule=100.0, lower_bound=90.0, proven=False,
        boxes_opened=3, boxes_pruned_free=1, boxes_pruned_programme=1,
        programmes_solved=3, descents=1, unresolved=2, lattice_size=10, seconds=1.0)
    assert not certificate.proven
    assert certificate.gap_abs == pytest.approx(10.0)
    assert certificate.gap_rel == pytest.approx(10.0)
    assert "unresolved" in certificate.summary()


# ------------------------------------------------------------------ the descent's reach
def test_the_set_is_a_coordinate_and_moves_between_ratings_only() -> None:
    """Frozen at the programme's choice, the set was one thing the descent could not fix.

    And the programme chooses it under anticipative dispatch — which is exactly the
    operator whose preferences the descent exists to correct. Stepped in kilowatts it would
    land between catalogue entries and describe a plant nobody sells, so it steps by rating.
    """
    from microgrid_expansion.exact.tree_certify import _moved

    ratings = (8.0, 12.0, 16.0)
    assert _moved(8.0, "generator_kw", +1.0, 0.0, ratings) == 12.0
    assert _moved(12.0, "generator_kw", -1.0, 0.0, ratings) == 8.0
    assert _moved(16.0, "generator_kw", +1.0, 0.0, ratings) == 16.0, "ran off the catalogue"
    assert _moved(8.0, "generator_kw", -1.0, 0.0, ratings) == 8.0, "ran off the catalogue"
    # A rating not in the catalogue snaps to the nearest one before stepping.
    assert _moved(11.0, "generator_kw", +1.0, 0.0, ratings) == 16.0
    # Everything else is modules, and moves by however many the scale asks for.
    assert _moved(30.0, "battery_kwh", +1.0, 5.0, ratings) == 35.0
    assert _moved(2.5, "battery_kwh", -1.0, 5.0, ratings) == 0.0, "capacity went negative"


def test_the_descent_starts_coarse_and_settles_fine() -> None:
    """One module at a time it cannot cross the distance it has to cross.

    The rule-based optimum carries seven to fifteen per cent more storage than the
    cost-optimal one on every reference-year instance measured, which is several modules,
    and a few rounds of single-module moves do not get there from here.
    """
    import inspect

    from microgrid_expansion.exact.tree_certify import certify_tree

    scales = inspect.signature(certify_tree).parameters["scales"].default
    assert len(scales) > 1, "the descent has a single scale and cannot travel"
    assert max(scales) >= 4, "the coarsest step is too small to cross several modules"
    assert min(scales) == 1, "the descent never settles at a single module"
    source = inspect.getsource(certify_tree)
    assert "sorted(set(scales), reverse=True)" in source, "coarse does not come first"
