"""End-to-end orchestrator: sample, reduce, build, solve, evaluate, report.

Run with::

    python -m microgrid_expansion.run --site Samionta

The pipeline mirrors the formulation and the method layer L3 established. A Monte-Carlo
ensemble is drawn over the four uncertainty families and reduced into a scenario tree; each
node's operating year is compressed into representative days; the deterministic-equivalent
programme gives the *lower* oracle — what a plan would cost under perfectly anticipative
dispatch — and the controller, simulated node by node, gives the *upper* one. The difference
between them is the price of the heuristic, now an expectation over futures rather than a
number for one year.

Both coupling architectures are carried through and the cheaper is reported, as at layer L3:
the two constrain the same variables differently, so a single programme cannot hold both.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .config import ModelConfig
from .exact.tree_certify import certify_tree
from .exact.tree_oracle import evaluate_plan
from .model import build_model
from .paths import RESULTS_DIR
from .post import extract_solution, expected_npc_lcoe, node_kpis
from .post.report import write_report
from .scenarios import sample_scenario_paths, space_from_settings
from .settings import ProjectSettings, default_settings
from .solve import solve
from .timedomain import reduce_to_rep_days
from .tree import build_tree


class _NodeInstance:
    """Adapter presenting a node's arrays the way the time-domain reduction expects."""

    def __init__(self, data, settings):
        from .resource.yield_model import battery_self_discharge, battery_usable_fraction
        self.demand_kw = data.demand
        self.specific_yield = data.pv_unit
        self.t_amb_c = data.t_amb
        chemistry = settings.battery.chemistry
        self.usable_fraction = battery_usable_fraction(data.t_amb, chemistry)
        self.self_discharge = battery_self_discharge(data.t_amb, chemistry)


def run(cfg: ModelConfig, out_dir: Path = RESULTS_DIR, verbose: bool = True,
        settings: "ProjectSettings | None" = None) -> dict:
    """Execute the pipeline and return the certified plan with its indicators.

    The village is named twice -- the configuration carries it because the tree is drawn
    before a settings object exists, and the project declares it because it *is* the
    project -- and the two may not disagree. Nothing on this path reads ``settings.site``
    today, which is why the disagreement was harmless and why it would not have stayed so:
    the customers to connect, and therefore the balance of plant, are read from the
    project's site.
    """
    cfg.validate()
    settings = default_settings() if settings is None else settings
    if settings.site != cfg.site:
        raise ValueError(
            f"the configuration is for {cfg.site!r} and the project describes "
            f"{settings.site!r}; one village per run, named once")

    # Over the uncertainty the settings describe, as the interface does. Left to the
    # library's defaults the two paths answered the same project differently.
    paths = sample_scenario_paths(cfg, space_from_settings(settings), settings)
    tree = build_tree(paths, cfg)
    tree.check_probabilities()
    if verbose:
        print(f"tree: {tree.tree_mode}, node year {cfg.node_year}, {len(tree.nodes)} nodes, "
              f"{len(tree.leaves)} leaves, distortion per stage "
              + ", ".join(f"{y}:{e:.3f}" for y, e in tree.reduction_error.items())
              + f", {tree.distortion.get('persistence_violations')} paths not persistent",
              flush=True)

    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings),
                                 cfg.n_rep_days) for n in tree.nodes}

    outcomes = []
    for architecture in settings.coupling.architectures():
        programme = build_model(tree, rep, cfg, architecture=architecture,
                                settings=settings)
        solved = solve(programme, settings, solver=cfg.solver)
        if solved.objective == float("inf"):
            if verbose:
                print(f"  couplage {architecture} : aucun plan admissible", flush=True)
            continue
        if verbose:
            print(f"  couplage {architecture} : borne {solved.objective:,.0f} $ "
                  f"({solved.seconds:.0f} s)", flush=True)
        # The programme's plan is optimal for a dispatch nobody will run. Descend from it
        # towards the plan the controller itself prefers, or the gap reported would be the
        # cost of having sized for the wrong operator rather than the price of myopia.
        certificate = certify_tree(extract_solution(programme, cfg, settings), tree, rep,
                                   solved.objective, architecture=architecture,
                                   settings=settings, verbose=verbose)
        outcomes.append((certificate.z_rule, solved.objective, architecture,
                         certificate.plans, certificate.traces, certificate))

    if not outcomes:
        raise RuntimeError("no coupling architecture admits a feasible plan")

    upper, lower, architecture, plans, traces, certificate = min(outcomes,
                                                                 key=lambda o: o[0])
    kpis = [node_kpis(plans, n, tree, traces) for n in tree.nodes]
    expected = expected_npc_lcoe(plans, tree, traces,
                                 discount_rate=settings.economics.discount_rate)
    expected.update({
        "architecture": architecture,
        "expected_rule_cost_usd": upper,
        "expected_optimal_cost_usd": lower,
        "price_of_heuristic_usd": upper - lower,
        "price_of_heuristic_pct": 100.0 * (upper - lower) / max(lower, 1.0),
        "search_evaluations": certificate.evaluations,
        "cost_of_the_programme_plan_usd": certificate.improved_from,
    })
    written = write_report(plans, kpis, expected, tree, out_dir,
                           stem=f"summary_tree_{cfg.site.lower()}", node_year=cfg.node_year)
    if verbose:
        root = plans[0]
        array = f"{root.pv_kw:.1f} kW"
        if getattr(root, "pv_ac_kw", 0.0) > 0:
            array += f" + {root.pv_ac_kw:.1f} kW on the load bus"
        print(f"\nfirst-stage plan: PV {array} | "
              f"battery {root.battery_kwh:.0f} kWh | conversion {root.inverter_kw:.1f} kW | "
              f"generator {root.generator_kw:.0f} kW   (coupling {architecture})")
        print(f"price of the heuristic : {expected['price_of_heuristic_usd']:,.0f} $ "
              f"({expected['price_of_heuristic_pct']:.1f} %)")
        print(f"expected levelised cost: {expected['expected_lcoe_usd_kwh']:.4f} $/kWh")
        print(f"written {written}")
    return {"expected": expected, "plans": plans, "tree": tree, "report": written}


def _configuration(args) -> tuple[ModelConfig, "ProjectSettings"]:
    """The project and the tree configuration for one command line, agreeing on everything.

    Assembled in one place so that it can be tested without running the pipeline. Three
    figures were carried twice and reconciled nowhere: the village, the horizon and the
    discount rate. The project is the source of all three, and the configuration holds the
    copies the tree needs before a settings object exists.
    """
    settings = default_settings()
    settings.site = args.site
    cfg = ModelConfig(site=settings.site, solver=args.solver, n_rep_days=args.rep_days,
                      n_mc_paths=args.mc_paths, seed=args.seed,
                      stage_years=tuple(args.stage_years),
                      branching=tuple(args.branching),
                      horizon_years=settings.economics.horizon_years,
                      discount_rate=settings.economics.discount_rate,
                      network_loss_fraction=args.network_loss,
                      tree_mode=getattr(args, "tree_mode", "fan"),
                      node_year=getattr(args, "node_year", "first"))
    cfg.validate()
    return cfg, settings


def main(argv: list[str] | None = None) -> int:
    # Taken from the configuration rather than repeated here. Repeated, they drifted: the
    # command line kept three stages branching two ways, seven nodes, while the
    # configuration had moved to five stages and forty-six, so running the module with no
    # arguments quietly built a different tree from the one the library builds — and wrote
    # it over the stored results under the same name.
    defaults = ModelConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--solver", default=defaults.solver,
                        choices=["highs", "gurobi"])
    parser.add_argument("--rep-days", type=int, default=defaults.n_rep_days,
                        help="days per node in the programme; 365 or more is the whole "
                             "year, under which the two oracles are directly comparable")
    parser.add_argument("--mc-paths", type=int, default=defaults.n_mc_paths)
    parser.add_argument("--stage-years", type=int, nargs="+",
                        default=list(defaults.stage_years))
    parser.add_argument("--branching", type=int, nargs="+",
                        default=list(defaults.branching))
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--network-loss", type=float,
                        default=defaults.network_loss_fraction,
                        help="share of the energy injected that the distribution network "
                             "consumes; it decides the demand every node is sized for")
    parser.add_argument("--tree-mode", default=defaults.tree_mode,
                        choices=["fan", "persistent"],
                        help="nest the stage medoids as a fan, or branch over regimes and "
                             "hold each one along its paths")
    parser.add_argument("--node-year", default=defaults.node_year,
                        choices=["first", "last"],
                        help="the year of its span whose demand a node carries")
    args = parser.parse_args(argv)

    cfg, settings = _configuration(args)
    run(cfg, settings=settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
