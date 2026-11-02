"""What the tree is worth, and how far the year-0 plant depends on weighing futures equally.

The answer this work reports is the root of the scenario tree: the plant to build now,
before the demand has declared itself. Three questions have been owed about that answer and
none of them could be asked while the weighting of the futures lived in a default argument.

*How much is the tree worth?* Against a plant chosen some other way -- certified on one
assumed trajectory, or taken from the mean-value problem -- the stochastic root is worth the
difference in expected cost. That is the value of the stochastic solution, VSS(x) =
EEV(x) - RP, and it is the number that says whether drawing a tree at all was justified.

*How much would it be worth to know?* If the growth trajectory were known in advance the
plant could be sized for it exactly, and the expected cost would fall to the average of the
three costs of knowing. The gap, RP - sum_t p_t RP_t, is the value of perfect information
on growth: an upper bound on what any survey of this community could buy.

*How much does the answer depend on the weights?* They are not estimated and cannot be: two
reference villages cannot say that a community is likelier to grow slowly than quickly. So
the honest treatment is not to defend a weighting but to show how much the plant moves when
it changes -- and to measure, first, how much it moves when nothing changes but the seed.
A root that shifts less than the sampling noise is not a finding.

Every quantity is computed under both oracles, and they do not mean the same thing. The
programme is the deterministic equivalent under perfectly anticipative dispatch: its value
is exact to the solver's tolerance, and the ordering sum_t p_t RP_t <= RP <= EEV(x) is a
theorem it must satisfy. The automaton is the coordinated descent against the controller
that will actually run, so each of its values is an upper bound and their differences are
estimates rather than bounds -- the ordering may fail there, and if it does this says so
rather than repairing it.

Nothing here writes over the repository's own tree summaries. The cases are a study of the
decision, not a replacement for it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from ..config import ModelConfig
from ..model import build_model
from ..paths import RESULTS_DIR
from ..post import extract_solution
from ..run import _NodeInstance
from ..scenarios import sample_scenario_paths
from ..scenarios import space_from_settings
from ..settings import ProjectSettings, default_settings
from ..solve import solve
from ..timedomain import reduce_to_rep_days
from ..tree import build_tree
from ..tree.tree_model import ScenarioTree
from .certify import Lattice
from .first_stage import _box_of, _root_of
from .tree_certify import certify_tree

#: The three growth trajectories, in the order the weights are given.
TRAJECTORY_WEIGHTS = {
    "thirds": (1 / 3, 1 / 3, 1 / 3),
    "slow_half": (0.5, 0.25, 0.25),
    "central_half": (0.25, 0.5, 0.25),
    "fast_half": (0.25, 0.25, 0.5),
    "slow_known": (1.0, 0.0, 0.0),
    "central_known": (0.0, 1.0, 0.0),
    "fast_known": (0.0, 0.0, 1.0),
}


@dataclass
class Case:
    """One tree to draw and cost, and what it is being asked."""

    name: str
    weights: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3)
    seed: int = 0
    #: A plant to hold the root at, in kilowatts and kilowatt-hours. ``None`` leaves the
    #: root free, which is the stochastic problem itself.
    fixed_root: dict[str, float] | None = None
    #: Where the fixed plant came from, carried into the report so that a reader is not
    #: left to infer it from four numbers.
    fixed_root_from: str = ""
    note: str = ""


def _settings_with(weights: tuple[float, float, float]) -> ProjectSettings:
    settings = default_settings()
    settings.trajectory_weights.slow = float(weights[0])
    settings.trajectory_weights.central = float(weights[1])
    settings.trajectory_weights.fast = float(weights[2])
    settings.validate()
    return settings


def _mean_value_space(settings: ProjectSettings):
    """The uncertainty space with every axis collapsed onto its central value.

    The classical mean-value problem is not "the central trajectory with everything else
    still random": it is the one future in which no uncertainty is uncertain. Each axis is
    therefore made degenerate -- the growth trajectory, the cost future, the resource
    pathway and the policy target -- and the grid is left as the settings describe it,
    since a line that is already in is not an uncertainty to collapse.
    """
    space = space_from_settings(settings)
    middle = lambda values: len(values) // 2                      # noqa: E731

    resource = replace(space.resource, probabilities=tuple(
        1.0 if i == middle(space.resource.pathways) else 0.0
        for i in range(len(space.resource.pathways))))
    policy = replace(space.policy, probabilities=tuple(
        1.0 if i == middle(space.policy.penetration_levels) else 0.0
        for i in range(len(space.policy.penetration_levels))))
    demand = replace(space.demand, trajectory_probabilities=(0.0, 1.0, 0.0))
    economic = replace(space.economic, scenario_probabilities=(0.0, 1.0, 0.0))
    return replace(space, demand=demand, economic=economic, resource=resource,
                   policy=policy)


def _chain_of(tree: ScenarioTree, leaf: int) -> tuple[ScenarioTree, dict[int, int]]:
    """The single path from the root to one leaf, as a tree in its own right.

    A scenario known in advance is a chain: the same operating years, the same discounting
    and the same years each milestone stands for, but nothing to hedge, because there is
    nothing left to find out. Solved on it, the programme is the cost of having known, and
    the probability-weighted sum of those costs over the leaves is the wait-and-see value.

    The decomposition is exact rather than approximate: every node of the tree is on the
    path of each leaf below it, and the leaf probabilities under a node sum to that node's
    own, so the costs reassemble into the tree's expectation term for term. The chains are
    carved from one draw, which is what makes the difference between them and the tree
    readable at this sample size.
    """
    path = tree.ancestors(leaf)
    renumbered = {old: new for new, old in enumerate(path)}
    chain = ScenarioTree(
        nodes=list(range(len(path))),
        stage={renumbered[n]: tree.stage[n] for n in path},
        parent={renumbered[n]: (renumbered[tree.parent[n]]
                                if tree.parent[n] is not None else None) for n in path},
        children={renumbered[n]: ([renumbered[path[i + 1]]] if i + 1 < len(path) else [])
                  for i, n in enumerate(path)},
        # Certain, every one of them: the whole point of the chain is that no branch is
        # left to take.
        prob={renumbered[n]: 1.0 for n in path},
        disc={renumbered[n]: tree.disc[n] for n in path},
        n_years={renumbered[n]: tree.n_years[n] for n in path},
        leaves=[renumbered[leaf]],
        node_data={renumbered[n]: tree.node_data[n] for n in path},
        reduction_error=dict(tree.reduction_error),
    )
    return chain, renumbered


def wait_and_see(cfg: ModelConfig, weights: tuple[float, float, float],
                 seed: int, verbose: bool = True) -> dict:
    """What the plant would cost if the whole future were known before it was built.

    One deterministic problem per leaf, weighted by that leaf's probability. The gap to the
    stochastic value is the value of perfect information on everything the tree carries at
    once -- growth, costs, resource, policy and the arrival of the line -- and it bounds
    what any foreknowledge whatever could be worth here.
    """
    started = time.perf_counter()
    settings = _settings_with(weights)
    cfg = replace(cfg, seed=seed)
    tree = build_tree(sample_scenario_paths(cfg, space_from_settings(settings)), cfg)
    tree.check_probabilities()
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    architecture = settings.coupling.architectures()[0]
    built = time.perf_counter() - started

    by_leaf = {}
    for leaf in tree.leaves:
        chain, renumbered = _chain_of(tree, leaf)
        chain_rep = {renumbered[n]: rep[n] for n in tree.ancestors(leaf)}
        programme = build_model(chain, chain_rep, cfg, architecture=architecture,
                                settings=settings)
        solved = solve(programme, settings, solver=cfg.solver)
        if solved.objective == float("inf"):
            raise RuntimeError(f"leaf {leaf}: no plan for a future that is known")
        plans = extract_solution(programme, cfg)
        certificate = certify_tree(plans, chain, chain_rep, solved.bound,
                                   architecture=architecture, settings=settings,
                                   verbose=False)
        by_leaf[str(leaf)] = {
            "probability": float(tree.prob[leaf]),
            "programme": {"expected_usd": float(solved.objective),
                          "bound_usd": float(solved.bound),
                          "root": _root_of(plans, chain)},
            "automaton": {"expected_usd": float(certificate.z_rule),
                          "root": _root_of(certificate.plans, chain)},
        }
        if verbose:
            print(f"    leaf {leaf:3d}  p={tree.prob[leaf]:.4f}  "
                  f"programme {solved.objective:>11,.0f} $   "
                  f"automaton {certificate.z_rule:>11,.0f} $", flush=True)

    out = {"weights": list(weights), "seed": seed, "leaves": len(by_leaf),
           "seconds_building": round(built, 1),
           "seconds_total": round(time.perf_counter() - started, 1),
           "by_leaf": by_leaf}
    for oracle in ("programme", "automaton"):
        out[oracle] = {"wait_and_see": sum(v["probability"] * v[oracle]["expected_usd"]
                                           for v in by_leaf.values())}
    return out


#: A capacity has grown when it has grown at all. Counts are integers of half a kilowatt
#: and of five kilowatt-hours, so nothing a plan actually does hides under this.
GREW_BY = 1e-6

#: The capacities an extension can consist of.
CAPACITIES = ("pv_kw", "pv_ac_kw", "battery_kwh", "inverter_kw", "generator_kw")


def _first_extension(plans: dict, tree, cfg: ModelConfig) -> dict:
    """When the plan first adds capacity, and how probable each date is.

    Read along paths rather than over nodes, because a date is a thing that happens to a
    village and a village lives on one path. A path that never extends is counted as such
    and kept out of the average date: folded in as a zero it would report an early
    extension, and dropped silently it would report the average date of the futures that
    did extend as though it were the average date.
    """
    years = tuple(cfg.stage_years)
    extends = {}
    for node in tree.nodes:
        parent = tree.parent[node]
        if parent is None:
            continue
        extends[node] = any(
            float(getattr(plans[node], part, 0.0))
            > float(getattr(plans[parent], part, 0.0)) + GREW_BY for part in CAPACITIES)

    by_year: dict[int, float] = {}
    never = 0.0
    for leaf in tree.leaves:
        first = next((n for n in tree.ancestors(leaf) if extends.get(n)), None)
        probability = float(tree.prob[leaf])
        if first is None:
            never += probability
            continue
        year = years[tree.stage[first]]
        by_year[year] = by_year.get(year, 0.0) + probability

    extended = sum(by_year.values())
    return {
        "probability_by_year": {str(y): round(by_year[y], 4) for y in sorted(by_year)},
        "earliest_year": min(by_year) if by_year else None,
        "never_pct": round(100.0 * never, 2),
        "expected_year_when_it_happens": (
            round(sum(y * p for y, p in by_year.items()) / extended, 2)
            if extended > 0 else None),
    }


def _unserved(tree, unserved_kwh: dict[int, float], demand_kwh: dict[int, float]) -> dict:
    """Energy the plant does not serve over the horizon, expected over the tree.

    Weighted by probability and by the years each node stands for, and not discounted: this
    is energy, and a kilowatt-hour a household does not get in year fifteen is not worth
    less to that household than one in year one. The denominator is each oracle's own
    demand, because they do not read the same year -- the programme dispatches the
    representative days it was reduced to, the automaton runs the eight thousand hours.
    """
    short = served = 0.0
    for node in tree.nodes:
        weight = float(tree.prob[node]) * float(tree.n_years[node])
        short += weight * float(unserved_kwh[node])
        served += weight * float(demand_kwh[node])
    return {"unserved_kwh": round(short, 1), "demand_kwh": round(served, 1),
            "share_pct": round(100.0 * short / served, 4) if served > 0 else None}


def _programme_unserved(programme, cfg: ModelConfig) -> dict[int, float]:
    """Unserved energy per node and per year, read off the solved programme."""
    import numpy as np
    import xarray as xr

    v, c = programme.variables, programme.coords
    days = xr.DataArray(np.asarray(c.hour_weight, dtype=float),
                        coords={"step": c.step}, dims="step")
    solution = v["unserved"].solution
    return {int(n): float((solution.sel(node=int(n)) * days).sum()) for n in c.node}


def run_case(case: Case, cfg: ModelConfig, mean_value: bool = False,
             verbose: bool = True) -> dict:
    """Draw the tree this case asks for, and cost it under both oracles."""
    started = time.perf_counter()
    settings = _settings_with(case.weights)
    cfg = replace(cfg, seed=case.seed)
    space = _mean_value_space(settings) if mean_value else space_from_settings(settings)

    tree = build_tree(sample_scenario_paths(cfg, space), cfg)
    tree.check_probabilities()
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    root_node = min(tree.nodes)
    # The demand the programme actually dispatches, node by node: the representative days
    # it was reduced to, weighted by the days each stands for.
    rep_demand = {n: float((rep[n].demand.sum(axis=1) * rep[n].weight).sum())
                  for n in tree.nodes}
    built = time.perf_counter() - started

    box = None
    if case.fixed_root is not None:
        lattice = Lattice.around(_NodeInstance(tree.node_data[root_node], settings),
                                 settings, architecture="dc")
        box = _box_of(case.fixed_root, lattice)

    outcomes = []
    for architecture in settings.coupling.architectures():
        at = time.perf_counter()
        programme = build_model(tree, rep, cfg, architecture=architecture,
                                settings=settings, root_box=box)
        solved = solve(programme, settings, solver=cfg.solver)
        if solved.objective == float("inf"):
            continue
        plans = extract_solution(programme, cfg)
        solved_in = time.perf_counter() - at

        at = time.perf_counter()
        certificate = certify_tree(
            plans, tree, rep, solved.bound, architecture=architecture, settings=settings,
            fixed_nodes=frozenset({root_node}) if box is not None else frozenset(),
            verbose=False)
        traces = certificate.traces
        outcomes.append({
            "architecture": architecture,
            # The value reached and the bound that guarantees it, kept apart. They coincide
            # when the solver closes the gap, and when they do not the difference is the
            # room left in every comparison drawn from this case.
            "programme": {"expected_usd": float(solved.objective),
                          "bound_usd": float(solved.bound),
                          "root": _root_of(plans, tree),
                          "unserved": _unserved(tree, _programme_unserved(programme, cfg),
                                                rep_demand),
                          "first_extension": _first_extension(plans, tree, cfg),
                          "seconds": round(solved_in, 1)},
            "automaton": {"expected_usd": float(certificate.z_rule),
                          "root": _root_of(certificate.plans, tree),
                          "unserved": _unserved(
                              tree, {n: t["unserved_kwh"] for n, t in traces.items()},
                              {n: t["served_kwh"] + t["unserved_kwh"]
                               for n, t in traces.items()}),
                          "first_extension": _first_extension(certificate.plans, tree, cfg),
                          "seconds": round(time.perf_counter() - at, 1),
                          "evaluations": certificate.evaluations},
        })
        if verbose:
            print(f"    {architecture:5s} programme {solved.objective:>11,.0f} $   "
                  f"automaton {certificate.z_rule:>11,.0f} $", flush=True)

    if not outcomes:
        raise RuntimeError(f"{case.name}: no coupling architecture admits a feasible plan")

    # The architecture is a decision like any other and the cheapest plan wins it, judged
    # under the controller that will run, which is the automaton.
    best = min(outcomes, key=lambda o: o["automaton"]["expected_usd"])
    return {
        **{k: v for k, v in asdict(case).items()},
        "mean_value": mean_value,
        "nodes": len(tree.nodes), "leaves": len(tree.leaves),
        "reduction_error": {str(k): round(float(v), 4)
                            for k, v in tree.reduction_error.items()},
        "seconds_building": round(built, 1),
        "seconds_total": round(time.perf_counter() - started, 1),
        **best,
    }


#: The capacities a reader looks at first, and how to read them off a root.
PARTS = (("array", lambda r: r["pv_kw"] + r["pv_ac_kw"], "kW"),
         ("storage", lambda r: r["battery_kwh"], "kWh"),
         ("conversion", lambda r: r["inverter_kw"], "kW"),
         ("generator", lambda r: r["generator_kw"], "kW"))

#: Left to right, from the future held certain at one end to the other.
ORDER = ("slow_known", "slow_half", "thirds", "central_half", "central_known",
         "fast_half", "fast_known")


def draw_figure(stored: dict, path: Path, oracle: str = "automaton") -> Path:
    """The year-0 plant against the weighting, over the noise of the draw.

    The band is what the same question answers when nothing changes but the seed. A root
    that moves inside it has not moved: it is the sampling, and reading a trend across it
    would be reading the random number generator.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cases = stored.get("cases", {})
    noise = [c for name, c in cases.items() if name.startswith("noise_seed")]
    shown = [name for name in ORDER
             if name in cases or (name == "thirds" and noise)]
    if not shown:
        raise RuntimeError("no weighted cases to draw")

    fig, axes = plt.subplots(1, len(PARTS), figsize=(13, 3.6), constrained_layout=True)
    for ax, (label, read, unit) in zip(axes, PARTS):
        values = []
        for name in shown:
            case = cases.get(name) or noise[0]
            values.append(read(case[oracle]["root"]))
        if noise:
            spread = [read(c[oracle]["root"]) for c in noise]
            ax.axhspan(min(spread), max(spread), color="#1f77b4", alpha=0.13, lw=0,
                       label="seed to seed" if ax is axes[0] else None)
        ax.plot(range(len(shown)), values, "o-", color="#1f77b4", lw=1.6, ms=5)
        ax.set_xticks(range(len(shown)))
        ax.set_xticklabels([n.replace("_", "\n") for n in shown], fontsize=7.5)
        ax.set_title(f"{label} [{unit}]", fontsize=10)
        # A capacity that never moves is drawn against a scale that says so. Left to fit
        # itself, the axis spreads one value over a decimal range and a flat line acquires
        # the look of a measurement.
        if max(values) - min(values) < 1e-9:
            ax.set_ylim(0.0, 1.3 * max(values) if max(values) > 0 else 1.0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", alpha=0.25, lw=0.6)
    if noise:
        axes[0].legend(fontsize=8, frameon=False, loc="best")
    fig.suptitle(f"{stored.get('site', '')}: the year-0 plant against the weighting of "
                 f"growth, under the {oracle}", fontsize=11)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def derive(stored: dict) -> dict:
    """The three questions, answered from the cases that have been run.

    Under the programme every term is exact to the solver's tolerance and the ordering
    sum_t p_t RP_t <= RP <= EEV(x) is a theorem: the left is the cost of knowing the
    growth, the middle the cost of weighing the futures, the right the cost of committing
    to one plant before weighing anything. Under the automaton each term is an upper bound
    from a descent, so the differences are estimates and the ordering may fail. Where it
    does this says so, because a descent that stopped early on one case and late on another
    is a fact about the search, not about the village.
    """
    cases = stored.get("cases", {})
    weights = stored.get("weights_for_evpi") or TRAJECTORY_WEIGHTS["thirds"]
    out: dict = {"weights_for_evpi": list(weights)}

    for oracle in ("programme", "automaton"):
        here: dict = {}
        reference = cases.get("noise_seed0") or cases.get("thirds")
        if reference is None:
            continue
        rp = reference[oracle]["expected_usd"]
        here["RP"] = rp
        # What the stochastic plant does to the village, beside what it costs it. A
        # comparison of expected costs alone would let a plant buy its saving out of
        # somebody's evenings.
        here["RP_unserved"] = reference[oracle].get("unserved")
        here["RP_first_extension"] = reference[oracle].get("first_extension")

        # The value of the stochastic solution, one per plant the root was held at.
        vss = {}
        for name, case in cases.items():
            if not name.startswith("fixed_"):
                continue
            eev = case[oracle]["expected_usd"]
            vss[case.get("fixed_root_from") or name] = {
                "EEV": eev, "VSS": eev - rp,
                "VSS_pct": 100.0 * (eev - rp) / max(rp, 1.0),
                "ordering_holds": eev >= rp - 1e-6,
                "unserved": case[oracle].get("unserved"),
                "first_extension": case[oracle].get("first_extension"),
            }
        if vss:
            here["vss"] = vss

        # The value of perfect information on growth, from the three futures held certain.
        known = {t: cases.get(f"{t}_known") for t in ("slow", "central", "fast")}
        if all(known.values()):
            wait_and_see = sum(w * known[t][oracle]["expected_usd"]
                               for w, t in zip(weights, ("slow", "central", "fast")))
            here["RP_by_trajectory"] = {t: known[t][oracle]["expected_usd"]
                                        for t in known}
            here["wait_and_see"] = wait_and_see
            here["EVPI_growth"] = rp - wait_and_see
            here["EVPI_growth_pct"] = 100.0 * (rp - wait_and_see) / max(rp, 1.0)
            here["ordering_holds"] = wait_and_see <= rp + 1e-6

        # And if everything were known, not only the growth. Carved from the one tree the
        # stochastic value was computed on, so the difference is a difference between two
        # readings of the same draw, which the trajectory-wise version above is not.
        everything = stored.get("wait_and_see_everything")
        if everything and oracle in everything:
            total = everything[oracle]["wait_and_see"]
            here["wait_and_see_everything"] = total
            here["EVPI_total"] = rp - total
            here["EVPI_total_pct"] = 100.0 * (rp - total) / max(rp, 1.0)
            here["ordering_holds_total"] = total <= rp + 1e-6

        # What the same question answers when only the seed moves.
        spread = [c[oracle]["expected_usd"] for name, c in cases.items()
                  if name.startswith("noise_seed")]
        if len(spread) > 1:
            here["noise_usd"] = {"min": min(spread), "max": max(spread),
                                 "span": max(spread) - min(spread),
                                 "span_pct": 100.0 * (max(spread) - min(spread))
                                 / max(min(spread), 1.0)}
        out[oracle] = here
    return out


def _said(unserved: dict | None, extension: dict | None) -> str:
    """The two indicators in one line, for the sheet a reader reads before the file."""
    parts = []
    if unserved:
        parts.append(f"unserved {unserved['share_pct']:.3f} % "
                     f"({unserved['unserved_kwh']:,.0f} kWh over the horizon)")
    if extension:
        if extension["earliest_year"] is None:
            parts.append("no path extends")
        else:
            dates = ", ".join(f"year {y} with p={p:.2f}"
                              for y, p in extension["probability_by_year"].items())
            parts.append(f"first extension {dates}; never on {extension['never_pct']:.0f} %"
                         " of paths")
    return "   ".join(parts)


def _head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def noise_cases(seeds: tuple[int, ...]) -> list[Case]:
    """The same question asked several times, to find out what an answer is worth."""
    return [Case(name=f"noise_seed{s}", weights=TRAJECTORY_WEIGHTS["thirds"], seed=s,
                 note="default weights; the spread over these is the sampling noise")
            for s in seeds]


def weight_cases(seed: int) -> list[Case]:
    """One tree per weighting, all on the reference seed."""
    return [Case(name=name, weights=w, seed=seed,
                 note="half the mass on one trajectory" if "half" in name
                      else "that trajectory known in advance" if "known" in name else "")
            for name, w in TRAJECTORY_WEIGHTS.items() if name != "thirds"]


def main(argv: list[str] | None = None) -> int:
    defaults = ModelConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--question", default="noise",
                        choices=["noise", "weights", "mean-value", "fixed",
                                 "wait-and-see", "figure", "summary"],
                        help="which block of cases to run")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2],
                        help="for the noise block")
    parser.add_argument("--seed", type=int, default=defaults.seed,
                        help="the reference seed every other block runs on")
    parser.add_argument("--fix", type=float, nargs=5, action="append", default=None,
                        metavar=("PV_KW", "PV_AC_KW", "BATT_KWH", "INV_KW", "GEN_KW"),
                        help="hold the root at this plant; repeatable")
    parser.add_argument("--fix-name", action="append", default=None,
                        help="where each --fix plant came from, in the same order")
    parser.add_argument("--rep-days", type=int, default=defaults.n_rep_days)
    parser.add_argument("--mc-paths", type=int, default=defaults.n_mc_paths)
    parser.add_argument("--stage-years", type=int, nargs="+",
                        default=list(defaults.stage_years))
    parser.add_argument("--branching", type=int, nargs="+",
                        default=list(defaults.branching))
    parser.add_argument("--solver", default=defaults.solver)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = ModelConfig(solver=args.solver, n_rep_days=args.rep_days,
                      n_mc_paths=args.mc_paths, seed=args.seed,
                      stage_years=tuple(args.stage_years),
                      branching=tuple(args.branching))
    cfg.site = args.site
    cfg.validate()

    out_default = RESULTS_DIR / f"summary_value_of_tree_{args.site.lower()}.json"
    if args.question == "summary":
        source = args.out or out_default
        stored = json.loads(source.read_text())
        stored["derived"] = derive(stored)
        source.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        for oracle, block in stored["derived"].items():
            if not isinstance(block, dict) or "RP" not in block:
                continue
            print(f"\n== {oracle} ==")
            print(f"   RP {block['RP']:,.0f} $   {_said(block.get('RP_unserved'), block.get('RP_first_extension'))}")
            for name, v in (block.get("vss") or {}).items():
                print(f"   EEV({name:20s}) {v['EEV']:>12,.0f} $   "
                      f"VSS {v['VSS']:>10,.0f} $ ({v['VSS_pct']:6.2f} %)"
                      f"{'' if v['ordering_holds'] else '   ORDERING FAILS'}")
                print(f"        {_said(v.get('unserved'), v.get('first_extension'))}")
            if "EVPI_growth" in block:
                print(f"   wait and see {block['wait_and_see']:,.0f} $   "
                      f"EVPI(growth) {block['EVPI_growth']:,.0f} $ "
                      f"({block['EVPI_growth_pct']:.2f} %)"
                      f"{'' if block['ordering_holds'] else '   ORDERING FAILS'}")
            if "EVPI_total" in block:
                print(f"   everything known {block['wait_and_see_everything']:,.0f} $   "
                      f"EVPI(total) {block['EVPI_total']:,.0f} $ "
                      f"({block['EVPI_total_pct']:.2f} %)"
                      f"{'' if block['ordering_holds_total'] else '   ORDERING FAILS'}")
            if "noise_usd" in block:
                n = block["noise_usd"]
                print(f"   seed to seed {n['span']:,.0f} $ ({n['span_pct']:.2f} %)")
        print(f"\nwritten {source}")
        return 0

    if args.question == "figure":
        source = args.out or out_default
        drawn = draw_figure(json.loads(source.read_text()),
                            source.with_name(f"value_of_tree_{args.site.lower()}.png"))
        print(f"written {drawn}")
        return 0

    if args.question == "wait-and-see":
        out = args.out or out_default
        stored = json.loads(out.read_text()) if out.exists() else {}
        stored.setdefault("site", args.site)
        stored["wait_and_see_everything"] = wait_and_see(
            cfg, TRAJECTORY_WEIGHTS["thirds"], args.seed)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        print(f"written {out}")
        return 0

    mean_value = args.question == "mean-value"
    if args.question == "noise":
        cases = noise_cases(tuple(args.seeds))
    elif args.question == "weights":
        cases = weight_cases(args.seed)
    elif mean_value:
        cases = [Case(name="mean_value", weights=TRAJECTORY_WEIGHTS["central_known"],
                      seed=args.seed,
                      note="every axis degenerate at its central value; its root is the "
                           "plant the mean-value problem would build")]
    else:
        if not args.fix:
            parser.error("--question fixed needs at least one --fix")
        names = args.fix_name or [f"given_{i}" for i in range(len(args.fix))]
        cases = [
            Case(name=f"fixed_{name}", weights=TRAJECTORY_WEIGHTS["thirds"],
                 seed=args.seed, fixed_root_from=name,
                 fixed_root={"pv_kw": pv, "pv_ac_kw": pv_ac, "battery_kwh": batt,
                             "inverter_kw": inv, "generator_kw": gen})
            for name, (pv, pv_ac, batt, inv, gen) in zip(names, args.fix)]

    out = args.out or out_default
    stored = json.loads(out.read_text()) if out.exists() else {}
    stored.setdefault("site", args.site)
    stored["commit"] = _head()
    stored["config"] = {"n_mc_paths": cfg.n_mc_paths, "n_rep_days": cfg.n_rep_days,
                        "stage_years": list(cfg.stage_years),
                        "branching": list(cfg.branching), "solver": cfg.solver}
    stored.setdefault("cases", {})

    for case in cases:
        print(f"  {case.name} weights={case.weights} seed={case.seed}", flush=True)
        stored["cases"][case.name] = run_case(case, cfg, mean_value=mean_value)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(stored, indent=2), encoding="utf-8")
        print(f"  written {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
