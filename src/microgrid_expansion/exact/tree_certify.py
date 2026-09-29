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

from .. import config
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


def _moved(current: float, field: str, direction: float, step: float,
           ratings: tuple[float, ...]) -> float:
    """One coordinate stepped, in the units that coordinate is actually sold in.

    Array, storage and conversion come in modules and move by however many the current
    scale calls for. The generating set does not: it is one machine chosen from a
    catalogue, so it moves to the next rating up or down and to nothing in between. Stepped
    in kilowatts it would land between catalogue entries and describe a plant nobody can
    buy.
    """
    if field != "generator_kw":
        return max(current + direction * step, 0.0)
    if not ratings:
        return current
    here = min(range(len(ratings)), key=lambda k: abs(ratings[k] - current))
    return ratings[min(max(here + int(direction), 0), len(ratings) - 1)]


def _admit(plans: dict, architecture: str, settings: ProjectSettings) -> dict:
    """Raise conversion until every node's array is one its converter admits.

    Without this the descent cannot grow the array at all, and the reason is not a detail:
    every certified optimum sits *exactly* on the admission ceiling -- 1.300 of a maximum
    1.3 on the battery's bus, 1.000 of 1.0 on the load's. From there one more module of
    array is inadmissible, so the plan costs infinity and the move is never taken; one more
    module of conversion admits nothing extra yet, so it only costs money and is never taken
    either. The pair is improving and neither half of it is, which a search moving one
    coordinate at a time cannot see.

    Repairing is better than enumerating the pairs. Raising the converter to what the array
    needs turns every inadmissible move into the feasible joint move it was reaching for,
    and it does so for the two buses at once; a move that lowers conversion below its array
    is simply undone, scores as no change, and is discarded like any other.
    """
    import math

    ratio_dc = (config.DC_AC_RATIO_MAX if architecture in ("dc", "mixed")
                else config.AC_RATIO_MAX)
    ratio_ac = config.AC_RATIO_MAX
    unit = settings.inverter.unit_kw
    out = dict(plans)
    for node, plan in out.items():
        needed = plan.pv_kw / ratio_dc
        if architecture == "mixed" and ratio_ac > 0:
            needed = max(needed, getattr(plan, "pv_ac_kw", 0.0) / ratio_ac)
        if needed > plan.inverter_kw + 1e-9:
            out[node] = replace(plan,
                                inverter_kw=math.ceil(needed / unit - 1e-9) * unit)
    return out


def _apply(plans: dict, tree: ScenarioTree, moves, steps: dict,
           ratings: tuple[float, ...] = (), architecture: str = "dc",
           settings: ProjectSettings | None = None) -> dict:
    """Apply one or several one-coordinate moves, then restore accumulation."""
    candidate = dict(plans)
    for node, field, direction in moves:
        for descendant in _descendants(tree, node):
            candidate[descendant] = replace(
                candidate[descendant],
                **{field: _moved(getattr(candidate[descendant], field), field,
                                 direction, steps[field], ratings)})
    candidate = _monotone(candidate, tree, tuple(steps))
    if settings is not None:
        # Conversion follows the array up, and accumulation is restored after it: raising a
        # node's converter must not leave it below its parent's.
        candidate = _monotone(_admit(candidate, architecture, settings),
                              tree, tuple(steps))
    return candidate


def certify_tree(plans: dict, tree: ScenarioTree, rep: dict[int, RepDays],
                 z_opt: float, architecture: str = "dc",
                 settings: ProjectSettings | None = None,
                 max_rounds: int = 12, workers: int | None = None,
                 fixed_nodes: frozenset[int] = frozenset(),
                 scales: tuple[int, ...] = (8, 4, 2, 1),
                 verbose: bool = True) -> TreeCertificate:
    """Descend from the programme's plan towards the one the controller prefers.

    A round tries every one-coordinate move from the incumbent, and those moves are
    independent of one another to evaluate: nothing one of them learns changes what another
    would cost. They are therefore scored across cores. On a forty-six node tree a round is
    a few hundred simulated plans, which the compiled controller costs about thirteen
    seconds on one core and under one on sixteen; before it was compiled the same round took
    twelve minutes, and the descent, not the programme, set the pace.

    Scoring them in parallel is not the same as *taking* them in parallel, and the
    difference matters. Accepting only the single best move each round would turn a descent
    that used to gather many improvements per pass into steepest descent, which needs as
    many rounds as there are moves to make. The improving moves are therefore composed —
    best first, and only one to a coordinate — and the composition is kept when it beats the
    best single move, which it usually does because moves on different nodes barely interact.

    ``scales`` is what lets the descent travel. One module at a time it can cross only a few
    modules before its rounds run out, and the plant the controller prefers is not a few
    modules from the one the programme picked: on the reference year the rule-based optimum
    carries seven to fifteen per cent more storage than the cost-optimal one, on every
    instance measured. So the neighbourhood starts eight modules wide and halves each time
    it stops paying, which is the coarse-then-fine shape the single-year certification has
    always used and this descent did not. It costs nothing worth counting: a descent runs in
    seconds against the programme's minutes, so a tenfold more thorough one is still free.

    ``fixed_nodes`` holds nodes the descent may not move. Pinning the root is what makes
    this an upper oracle for one year-0 plant rather than for the plan as a whole: the
    value it returns is then the cost of the best plan *rooted at that plant* the descent
    can find, which is what a branch-and-bound on the first stage needs from it.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor

    settings = default_settings() if settings is None else settings
    base = {"pv_kw": settings.photovoltaic.unit_kw,
            "battery_kwh": settings.battery.unit_kwh,
            "inverter_kw": settings.inverter.unit_kw}
    if architecture == "mixed":
        # The array is divided, so the part on the load's bus is a coordinate of its own:
        # left out, the descent could only move the whole field through the ceiling on the
        # battery's bus, which is the restriction the divided array exists to lift.
        base["pv_ac_kw"] = settings.photovoltaic.unit_kw
    # The set is a coordinate too. Left out, a plan was stuck with whatever rating the
    # programme happened to choose under anticipative dispatch -- and the controller, which
    # cannot see tomorrow's cloud, is exactly the operator that would want a different one.
    ratings = tuple(sorted(g.rating_kw for g in settings.generators))
    base["generator_kw"] = 0.0                       # stepped by catalogue index, not by size

    workers = workers or min(os.cpu_count() or 1, 16)
    grid = [(node, field, direction) for node in tree.nodes if node not in fixed_nodes
            for field in base for direction in (+1.0, -1.0)]

    best_plans = _monotone(dict(plans), tree, tuple(base))
    for node in fixed_nodes:
        best_plans[node] = plans[node]
    best_plans = _monotone(best_plans, tree, tuple(base))
    best, traces = evaluate_plan(best_plans, tree, rep, architecture, settings)
    started_at, evaluations, started = best, 1, time.time()

    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker,
                             initargs=(tree, rep, architecture, settings)) as pool:
        # Coarse first. A scale that stops paying is halved rather than abandoned, so the
        # descent crosses the distance at eight modules a step and settles it at one.
        for scale in sorted(set(scales), reverse=True):
            steps = {f: size * scale for f, size in base.items()}
            for _ in range(max_rounds):
                moves = [_apply(best_plans, tree, [m], steps, ratings, architecture,
                                settings) for m in grid]
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
                composed = _apply(best_plans, tree, taken, steps, ratings,
                                  architecture, settings)
                composed_value, _ = evaluate_plan(composed, tree, rep, architecture,
                                                  settings)
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
