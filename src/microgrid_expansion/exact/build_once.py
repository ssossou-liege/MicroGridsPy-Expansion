r"""What the possibility of extending is worth, and the fixed cost that would remove it.

The programme charges an extension for the equipment it installs and for nothing else. In
the field an extension is a campaign: a container is booked, cleared through customs,
trucked inland and a team is mobilised to install what arrives. The operator's own ledger
puts that between nothing, when the equipment travels with another site's container, and
about fifteen thousand dollars for a dedicated campaign -- three to five thousand of sea
freight a line, 4 939 of clearance on a container, up to 3 400 of inland transport and
about a thousand of installation.

A model that leaves it out prefers many small extensions to one large one, and the solved
trees show exactly that: half the nodes after the root add something, and some of those
additions are three and a half kilowatts of array. The question is not whether that is
untidy but whether it changes the plant to build now, which is the only answer the work
reports.

The test here is a bound rather than a correction, and the distinction decides what may be
claimed afterwards. One extreme of the fixed cost is priced exactly -- a park built once and
never touched, which no fixed cost can make worse -- and compared with the flexible plan the
model chooses today. The difference is what flexibility is worth, V = C1 - RP, and dividing
it by the discounted number of extensions the flexible plan makes gives the fixed cost at
which building once becomes the cheaper policy:

    F* = V / N_d ,    N_d = sum of p(n) d(n) over the nodes that extend.

Read it as what it is. Above F* the flexible plan is more expensive than building once, so
if F* lies far above what a campaign can cost, no fixed cost reverses the strategy and the
model's answer stands. That excludes a reversal; it does not exclude the root growing a
little, because a fixed cost would group the small late extensions and bring some of their
capacity forward. A park *built once* is the limit of grouping, not a small correction to it.

Both oracles are run and they do not mean the same thing. The programme's RP and C1 are
exact to the solver's tolerance, so V and F* under the programme are exact. The automaton's
are upper bounds reached by a descent, so its V is a difference of two estimates and its
F* an estimate; where the two disagree the programme's is the one that bounds anything.

The park built once is expressed in the programme without a new formulation. Capacity
accumulates as additions per node, so forbidding every addition after the root -- and
holding the generator at the root's rating -- is exactly the policy, with the root itself
left free to be whatever the park should be. Under the automaton it needs no new code
either: a move on a node propagates to that node's descendants, so a descent allowed to
move the root alone moves the whole tree together and the park stays uniform.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from ..config import ModelConfig
from ..model import build_model
from ..paths import RESULTS_DIR
from ..post import extract_solution
from ..run import _NodeInstance
from ..scenarios import sample_scenario_paths, space_from_settings
from ..settings import ProjectSettings, default_settings
from ..solve import solve
from ..timedomain import reduce_to_rep_days
from ..tree import build_tree
from ..tree.tree_model import ScenarioTree
from .first_stage import _root_of
from .tree_certify import certify_tree
from .tree_value import _head

#: The fixed costs the after-the-fact comparison is drawn at, in dollars. The ends are the
#: operator's: nothing when the equipment rides in another site's container, and about
#: fifteen thousand for a campaign mobilised for one village. Thirty thousand is beyond
#: anything the ledger shows and is there to say where the crossing would have to be.
FIXED_COSTS_USD = (0.0, 5_000.0, 10_000.0, 15_000.0, 30_000.0)

#: The capacities, how to read each off a plan, and what one unit of it costs at a node.
PARTS = (("pv_kw", "capex_pv"), ("pv_ac_kw", "capex_pv"), ("battery_kwh", "capex_batt"),
         ("inverter_kw", "capex_inv"))


def _grown(plan, parent) -> dict[str, float]:
    """What a node installs that its parent did not have."""
    out = {}
    for field, _price in PARTS:
        added = getattr(plan, field, 0.0) - getattr(parent, field, 0.0)
        if added > 1e-9:
            out[field] = float(added)
    if plan.generator_kw > parent.generator_kw + 1e-9:
        # A set is replaced and not added to: two machines on one bus is a different
        # plant, so an upgrade buys the whole new rating.
        out["generator_kw"] = float(plan.generator_kw)
    return out


def _equipment_usd(grown: dict[str, float], costs: dict, architecture: str) -> float:
    """What an extension spends on equipment, at the node's own prices.

    The prices are the node's and not the base year's, the cost trajectory having already
    been applied to them, and the array on the load's bus buys the string inverters that
    put it there exactly as it does in the objective.
    """
    total = 0.0
    for field, price in PARTS:
        if field not in grown:
            continue
        unit = costs[price]
        if field == "pv_ac_kw" and architecture == "mixed":
            unit += costs["capex_conv_ac"]
        total += grown[field] * unit
    if "generator_kw" in grown:
        total += grown["generator_kw"] * costs["capex_ge"]
    return total


def extensions(plans: dict, tree: ScenarioTree, architecture: str) -> dict:
    """Where the plan extends, how often, and what each extension buys.

    ``n`` counts extensions the way a path meets them: the probability-weighted number of
    nodes at which something is installed, which is the number of campaigns an operator
    following this plan expects to mount. ``n_discounted`` weights each by the factor the
    objective discounts that node's spending with, so that a fixed cost per campaign can be
    added to a present value without changing conventions.
    """
    root = min(tree.nodes)
    nodes, spends = [], []
    for node in sorted(tree.nodes):
        parent = tree.parent[node]
        if parent is None:
            continue
        grown = _grown(plans[node], plans[parent])
        if not grown:
            continue
        spend = _equipment_usd(grown, tree.node_data[node].costs, architecture)
        nodes.append({"node": node, "stage": tree.stage[node],
                      "probability": float(tree.prob[node]),
                      "discount": float(tree.disc[node]),
                      "added": {k: round(v, 3) for k, v in grown.items()},
                      "equipment_usd": round(spend, 1)})
        spends.append(spend)
    spends.sort()
    return {
        "nodes_after_the_root": len(tree.nodes) - 1,
        "nodes_that_extend": len(nodes),
        "n": round(sum(x["probability"] for x in nodes), 4),
        "n_discounted": round(sum(x["probability"] * x["discount"] for x in nodes), 4),
        "equipment_usd": {
            "least": round(spends[0], 1) if spends else 0.0,
            "median": round(spends[len(spends) // 2], 1) if spends else 0.0,
            "most": round(spends[-1], 1) if spends else 0.0,
            "total_if_every_node_were_visited": round(sum(spends), 1),
        },
        "root": root,
        "where": nodes,
    }


def hold_the_park(programme, tree: ScenarioTree) -> None:
    """Forbid every addition after the root, which is the park built once.

    Exact rather than approximate, and it is worth saying why in one line: the programme's
    decision variables are modules *added* at a node, with installed capacity accumulated
    along the path, so a park that is never extended is the set of plans whose additions
    after the root are all zero. The generator is upgraded rather than accumulated, so it
    is held at the root's rating instead.
    """
    model, v, c = programme.model, programme.variables, programme.coords
    root = int(min(tree.nodes))
    after = [int(n) for n in c.node if int(n) != root]
    for module in ("b_pv", "b_batt", "b_inv", "b_pv_ac"):
        if module not in v:
            continue
        for node in after:
            model.add_constraints(v[module].sel(node=node) == 0,
                                  name=f"built_once_{module}_{node}")
    for node in after:
        model.add_constraints(
            v["z_ge"].sel(node=node) - v["z_ge"].sel(node=root) == 0,
            name=f"built_once_gen_{node}")


def _solved(tree, rep, cfg: ModelConfig, settings: ProjectSettings, architecture: str,
            built_once: bool, fixed_nodes: frozenset[int] | None = None,
            verbose: bool = True) -> dict:
    """One policy under both oracles: the programme, then the descent from its plan."""
    at = time.perf_counter()
    programme = build_model(tree, rep, cfg, architecture=architecture, settings=settings)
    if built_once:
        hold_the_park(programme, tree)
    solved = solve(programme, settings, solver=cfg.solver)
    if solved.objective == float("inf"):
        raise RuntimeError("no feasible plan under this policy")
    plans = extract_solution(programme, cfg)
    programme_seconds = time.perf_counter() - at

    at = time.perf_counter()
    certificate = certify_tree(plans, tree, rep, solved.bound, architecture=architecture,
                               settings=settings,
                               fixed_nodes=fixed_nodes or frozenset(), verbose=verbose)
    return {
        "architecture": architecture,
        "programme": {"expected_usd": float(solved.objective),
                      "bound_usd": float(solved.bound),
                      "root": _root_of(plans, tree),
                      "extensions": extensions(plans, tree, architecture),
                      "seconds": round(programme_seconds, 1)},
        "automaton": {"expected_usd": float(certificate.z_rule),
                      "root": _root_of(certificate.plans, tree),
                      "extensions": extensions(certificate.plans, tree, architecture),
                      "evaluations": certificate.evaluations,
                      "seconds": round(time.perf_counter() - at, 1)},
    }


def after_the_fact(flexible: float, built_once: float, n_discounted: float,
                   fixed_costs=FIXED_COSTS_USD) -> dict:
    """The comparison a fixed cost per campaign would make, without re-solving anything.

    Charging the flexible plan ``F`` for each extension it makes is an upper bound on what
    the plan would cost were the fixed cost in the model, because a model that knew about
    the fixed cost would reorganise its extensions to pay it less often. So the crossing
    this reports is the earliest one: below it, building once is certainly not cheaper.
    """
    rows = []
    for f in fixed_costs:
        charged = flexible + f * n_discounted
        rows.append({"fixed_cost_usd": f,
                     "flexible_charged_usd": round(charged, 1),
                     "built_once_usd": round(built_once, 1),
                     "cheaper": "built once" if built_once < charged else "flexible"})
    value = built_once - flexible
    return {
        "V_usd": round(value, 1),
        "V_pct_of_flexible": round(100.0 * value / flexible, 3) if flexible else None,
        "n_discounted": n_discounted,
        "F_star_usd": round(value / n_discounted, 1) if n_discounted else None,
        "table": rows,
    }


def draw_figure(stored: dict, path: Path, oracle: str = "programme") -> Path:
    """Expected cost against the fixed cost of a campaign, for the two policies."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    block = stored["derived"][oracle]
    flexible = stored["flexible"][oracle]["expected_usd"]
    once = stored["built_once"][oracle]["expected_usd"]
    n_d = block["n_discounted"]
    star = block["F_star_usd"]

    top = max(FIXED_COSTS_USD[-1], 1.25 * star if star else 0.0)
    f = np.linspace(0.0, top, 200)
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.plot(f / 1000.0, (flexible + f * n_d) / 1000.0, lw=2.0,
            label=f"flexible plan, charged F per extension (N_d = {n_d:.2f})")
    ax.axhline(once / 1000.0, lw=2.0, ls="--", color="C1",
               label="park built once, no extension to charge")
    if star is not None and 0.0 <= star <= top:
        ax.axvline(star / 1000.0, lw=1.0, color="0.4")
        ax.annotate(f"F* = {star / 1000.0:,.1f} k$", (star / 1000.0, once / 1000.0),
                    textcoords="offset points", xytext=(8, -16), fontsize=9)
    ax.axvspan(0.0, 15.0, color="0.85", zorder=0)
    ax.annotate("what a campaign can cost, on the operator's ledger", (0.4, 0.04),
                xycoords="axes fraction", fontsize=8, color="0.3")
    ax.set_xlabel("fixed cost of one extension campaign [thousand $]")
    ax.set_ylabel("expected discounted cost [thousand $]")
    ax.set_title(f"{stored['site']}: is it worth being able to extend? "
                 f"({oracle}, seed {stored['config']['seed']})")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    defaults = ModelConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--rep-days", type=int, default=defaults.n_rep_days)
    parser.add_argument("--mc-paths", type=int, default=defaults.n_mc_paths)
    parser.add_argument("--stage-years", type=int, nargs="+",
                        default=list(defaults.stage_years))
    parser.add_argument("--branching", type=int, nargs="+",
                        default=list(defaults.branching))
    parser.add_argument("--solver", default=defaults.solver)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--figure-only", action="store_true",
                        help="redraw the figure from the stored record")
    args = parser.parse_args(argv)

    out = args.out or RESULTS_DIR / f"summary_build_once_{args.site.lower()}.json"
    if args.figure_only:
        drawn = draw_figure(json.loads(out.read_text()),
                            out.with_name(f"build_once_{args.site.lower()}.png"))
        print(f"written {drawn}")
        return 0

    cfg = ModelConfig(solver=args.solver, n_rep_days=args.rep_days,
                      n_mc_paths=args.mc_paths, seed=args.seed,
                      stage_years=tuple(args.stage_years),
                      branching=tuple(args.branching))
    cfg.site = args.site
    cfg.validate()
    settings = default_settings()

    started = time.perf_counter()
    tree = build_tree(
        sample_scenario_paths(cfg, space_from_settings(settings), settings), cfg)
    tree.check_probabilities()
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    root = min(tree.nodes)
    print(f"tree: {len(tree.nodes)} nodes, {len(tree.leaves)} leaves "
          f"({time.perf_counter() - started:.0f} s)", flush=True)

    architecture = settings.coupling.architectures()[0]

    print("\n## the flexible plan, which is what the model chooses today", flush=True)
    flexible = _solved(tree, rep, cfg, settings, architecture, built_once=False)

    print("\n## the park built once, root free and every addition after it forbidden",
          flush=True)
    # The descent moves the root alone; a move on the root propagates to its descendants,
    # so the park stays uniform without the certifier needing to know about this study.
    built_once = _solved(tree, rep, cfg, settings, architecture, built_once=True,
                         fixed_nodes=frozenset(tree.nodes) - {root})

    derived = {}
    for oracle in ("programme", "automaton"):
        block = after_the_fact(flexible[oracle]["expected_usd"],
                              built_once[oracle]["expected_usd"],
                              flexible[oracle]["extensions"]["n_discounted"])
        block["n"] = flexible[oracle]["extensions"]["n"]
        block["nodes_that_extend"] = flexible[oracle]["extensions"]["nodes_that_extend"]
        derived[oracle] = block

    stored = {
        "site": args.site,
        "commit": _head(),
        "architecture": architecture,
        "config": {"seed": cfg.seed, "n_mc_paths": cfg.n_mc_paths,
                   "n_rep_days": cfg.n_rep_days, "stage_years": list(cfg.stage_years),
                   "branching": list(cfg.branching), "solver": cfg.solver},
        "prices_usd": {"array_per_kw": settings.photovoltaic.cost_usd_kw,
                       "storage_per_kwh": settings.battery.cost_usd_kwh,
                       "conversion_per_kw": settings.inverter.cost_usd_kw,
                       "generator_per_kva": settings.generators[0].cost_usd_kva,
                       "string_inverter_per_kw":
                           settings.coupling.string_inverter_cost_usd_kw},
        "flexible": flexible,
        "built_once": built_once,
        "derived": derived,
        "seconds_total": round(time.perf_counter() - started, 1),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    for oracle in ("programme", "automaton"):
        block, d = flexible[oracle], derived[oracle]
        print(f"\n== {oracle} ==")
        print(f"   RP {block['expected_usd']:>11,.0f} $   root "
              f"{block['root']['pv_kw'] + block['root']['pv_ac_kw']:.1f} kW field, "
              f"{block['root']['battery_kwh']:.0f} kWh, "
              f"{block['root']['inverter_kw']:.1f} kW")
        once = built_once[oracle]
        print(f"   C1 {once['expected_usd']:>11,.0f} $   root "
              f"{once['root']['pv_kw'] + once['root']['pv_ac_kw']:.1f} kW field, "
              f"{once['root']['battery_kwh']:.0f} kWh, "
              f"{once['root']['inverter_kw']:.1f} kW")
        print(f"   V  {d['V_usd']:>11,.0f} $ ({d['V_pct_of_flexible']:.2f} %)   "
              f"extensions: {d['nodes_that_extend']} nodes, "
              f"N {d['n']:.2f}, N_d {d['n_discounted']:.2f}   "
              f"F* {d['F_star_usd']:,.0f} $")
        for row in d["table"]:
            print(f"      F {row['fixed_cost_usd']:>7,.0f} $   flexible "
                  f"{row['flexible_charged_usd']:>11,.0f} $   built once "
                  f"{row['built_once_usd']:>11,.0f} $   -> {row['cheaper']}")

    drawn = draw_figure(stored, out.with_name(f"build_once_{args.site.lower()}.png"))
    print(f"\nwritten {out}\nwritten {drawn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
