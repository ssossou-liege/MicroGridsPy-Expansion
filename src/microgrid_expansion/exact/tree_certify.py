"""Optimise a capacity plan over the tree against the controller that will run it.

The programme of :mod:`microgrid_expansion.model` minimises cost under perfectly
anticipative dispatch. Its solution is the right *lower* oracle but the wrong plan: run by
the controller that will actually be installed, it is not the cheapest plan available, and
reporting the gap between the two would confuse the price of myopia with the cost of having
sized for the wrong operator.

What follows searches for the plan the controller itself would prefer. It cannot enumerate:
a plan is a vector of module counts over every node of the tree, and the lattice of layer L3
was already a million points for a single year. It descends instead, one coordinate at a
time from the programme's solution, which is a strong starting point precisely because the
two objectives differ only by the price being measured. Every plan it reaches is buildable
and its cost is a simulation, so the value returned is an honest upper bound on the
rule-based optimum — and therefore the price of the heuristic it implies is an upper bound
too, which tightens as the search improves rather than drifting.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace

import numpy as np

from ..settings import ProjectSettings, default_settings
from ..timedomain.rep_days import RepDays
from ..tree.tree_model import ScenarioTree
from .tree_oracle import evaluate_plan


@dataclass
class TreeCertificate:
    """A plan, what it costs under each oracle, and the effort spent."""

    plans: dict
    traces: dict
    z_rule: float
    z_opt: float
    architecture: str
    evaluations: int
    improved_from: float

    @property
    def price_abs(self) -> float:
        return self.z_rule - self.z_opt

    @property
    def price_rel(self) -> float:
        return 100.0 * self.price_abs / max(self.z_opt, 1.0)


def _descendants(tree: ScenarioTree, node: int) -> list[int]:
    stack, found = [node], []
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(tree.children[current])
    return found


def _monotone(plans: dict, tree: ScenarioTree, fields: tuple[str, ...]) -> dict:
    """Raise every node to at least its parent's capacity.

    Capacity accumulates down the tree: a module installed at year five is still there at
    year ten, and no plan may hold less than the plan it grew from. A search that moves a
    node without imposing this describes a plant which dismantles itself between two
    milestones — which the programme forbids by construction and the descent, moving one
    coordinate at a time, does not.
    """
    fixed = dict(plans)
    for node in tree.nodes:
        parent = tree.parent[node]
        if parent is None:
            continue
        updates = {f: max(getattr(fixed[node], f), getattr(fixed[parent], f))
                   for f in fields}
        fixed[node] = replace(fixed[node], **updates)
    return fixed


#: Shared state a worker builds once, so that a candidate crossing to it carries only the
#: plan — a few dozen numbers — rather than the tree's arrays, which are megabytes and would
#: cost more to send than the evaluation saves.
_WORKER: dict = {}


def _init_worker(tree, rep, architecture, settings) -> None:
    _WORKER.update(tree=tree, rep=rep, architecture=architecture, settings=settings)


def _score(candidate) -> float:
    value, _ = evaluate_plan(candidate, _WORKER["tree"], _WORKER["rep"],
                             _WORKER["architecture"], _WORKER["settings"])
    return value


def _apply(plans: dict, tree: ScenarioTree, moves, steps: dict) -> dict:
    """Apply one or several one-coordinate moves, then restore accumulation."""
    candidate = dict(plans)
    for node, field, direction in moves:
        for descendant in _descendants(tree, node):
            candidate[descendant] = replace(
                candidate[descendant],
                **{field: max(getattr(candidate[descendant], field)
                              + direction * steps[field], 0.0)})
    return _monotone(candidate, tree, tuple(steps))


def certify_tree(plans: dict, tree: ScenarioTree, rep: dict[int, RepDays],
                 z_opt: float, architecture: str = "dc",
                 settings: ProjectSettings | None = None,
                 max_rounds: int = 6, workers: int | None = None,
                 verbose: bool = True) -> TreeCertificate:
    """Descend from the programme's plan towards the one the controller prefers.

    A round tries every one-coordinate move from the incumbent, and those moves are
    independent of one another to evaluate: nothing one of them learns changes what another
    would cost. They are therefore scored across cores. On a forty-six node tree a round is
    two hundred and seventy-six simulated plans, which the compiled controller now costs
    about thirteen seconds on one core and under one on sixteen; before it was compiled the
    same round took twelve minutes, and the descent, not the programme, set the pace.

    Scoring them in parallel is not the same as *taking* them in parallel, and the
    difference matters. Accepting only the single best move each round would turn a descent
    that used to gather many improvements per pass into steepest descent, which needs as
    many rounds as there are moves to make. The improving moves are therefore composed —
    best first, and only one to a coordinate — and the composition is kept when it beats the
    best single move, which it usually does because moves on different nodes barely interact.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor

    settings = default_settings() if settings is None else settings
    steps = {"pv_kw": settings.photovoltaic.unit_kw,
             "battery_kwh": settings.battery.unit_kwh,
             "inverter_kw": settings.inverter.unit_kw}
    if architecture == "mixed":
        # The array is divided, so the part on the load's bus is a coordinate of its own:
        # left out, the descent could only move the whole field through the ceiling on the
        # battery's bus, which is the restriction the divided array exists to lift.
        steps["pv_ac_kw"] = settings.photovoltaic.unit_kw
    workers = workers or min(os.cpu_count() or 1, 16)
    grid = [(node, field, direction) for node in tree.nodes
            for field in steps for direction in (+1.0, -1.0)]

    best_plans = _monotone(dict(plans), tree, tuple(steps))
    best, traces = evaluate_plan(best_plans, tree, rep, architecture, settings)
    started_at, evaluations, started = best, 1, time.time()

    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(tree, rep, architecture, settings)) as pool:
        for _ in range(max_rounds):
            moves = [_apply(best_plans, tree, [m], steps) for m in grid]
            values = list(pool.map(_score, moves, chunksize=4))
            evaluations += len(moves)

            improving = sorted((v, k) for k, v in enumerate(values) if v < best - 1e-6)
            if not improving:
                break

            taken, seen = [], set()
            for _, k in improving:
                node, field, _direction = grid[k]
                if (node, field) in seen:
                    continue
                seen.add((node, field))
                taken.append(grid[k])
            composed = _apply(best_plans, tree, taken, steps)
            composed_value, _ = evaluate_plan(composed, tree, rep, architecture, settings)
            evaluations += 1

            if composed_value < improving[0][0]:
                best, best_plans = composed_value, composed
            else:
                best, best_plans = improving[0][0], moves[improving[0][1]]

    best, traces = evaluate_plan(best_plans, tree, rep, architecture, settings)
    if verbose:
        print(f"    descent: {started_at:,.0f} -> {best:,.0f} $ "
              f"in {evaluations} evaluations on {workers} cores "
              f"({time.time() - started:.0f} s)", flush=True)
    return TreeCertificate(plans=best_plans, traces=traces, z_rule=best, z_opt=z_opt,
                           architecture=architecture, evaluations=evaluations,
                           improved_from=started_at)
