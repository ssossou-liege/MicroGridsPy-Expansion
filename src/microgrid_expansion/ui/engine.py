"""What the interface asks the engine to do, and what it gets back.

Kept apart from the routes so that the work is testable without a server, and so that the
routes stay a thin translation between HTTP and these two calls.
"""
from __future__ import annotations

from typing import Any

from ..settings import ProjectSettings, default_settings
from . import schema
from .jobs import Job


def settings_from(overrides: dict[str, Any]) -> ProjectSettings:
    return schema.apply(default_settings(), dict(overrides or {}))


def size_site(job: Job, overrides: dict[str, Any]) -> dict:
    """Certify the sizing of one site over a reference year."""
    from ..exact.certify import Lattice, certify_exhaustive
    from ..instances import build_site_year

    settings = settings_from(overrides)
    job.total = 3

    job.stage = "construction de la demande et de la ressource"
    instance = build_site_year(settings.site, settings.year,
                               trajectory=settings.demand_trajectory,
                               maturity_months=settings.maturity_months)
    job.done = 1

    job.stage = "délimitation de l'ensemble admissible"
    lattice = Lattice.around(instance, settings)
    job.done = 2

    job.stage = f"certification sur {lattice.size:,} dimensionnements".replace(",", " ")
    result = certify_exhaustive(instance, lattice, settings, verbose=False)
    job.done = 3

    # The certificate settles which plant is cheapest; what it costs a customer is a second
    # question, answered by running the certified design once more and pricing its life.
    from ..post.economics import assets_from_settings, life_cycle_cost
    from ..exact.simulator import BatteryModel, GeneratorModel, simulate

    design = result.design
    battery = BatteryModel.from_spec(settings.battery)
    unit = min(settings.generators,
               key=lambda g: abs(g.rating_kw - design.generator_kw))
    generator = GeneratorModel.from_spec(unit, settings.economics.diesel_price_usd_l)
    dispatch = simulate(instance.demand_kw, instance.specific_yield, instance.t_amb_c,
                        design, battery, generator)
    operating = dispatch.operating_cost(
        generator, degradation_usd_kwh=settings.battery.degradation_usd_kwh(),
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh)
    served = instance.demand_kwh - float(dispatch.unserved_kw.sum())
    target = (settings.economics.tariff_usd_kwh
              if settings.economics.tariff_is_target else None)
    cost = life_cycle_cost(
        {"pv": design.pv_total_kw, "battery": design.battery_kwh,
         "inverter": design.inverter_kw, "generator": design.generator_kw,
         "conversion": design.pv_ac_kw},
        operating, served, horizon_years=settings.economics.horizon_years,
        discount_rate=settings.economics.discount_rate, tariff_target_usd_kwh=target,
        assets=assets_from_settings(settings, architecture="ac"))

    return {
        "site": settings.site,
        "trajectory": settings.demand_trajectory,
        "architecture": lattice.architecture,
        "lattice_size": lattice.size,
        "design": {"pv_kw": design.pv_kw, "pv_ac_kw": design.pv_ac_kw,
                   "battery_kwh": design.battery_kwh,
                   "inverter_kw": design.inverter_kw,
                   "generator_kw": design.generator_kw},
        "design_opt": {"pv_kw": result.design_opt.pv_kw,
                       "battery_kwh": result.design_opt.battery_kwh,
                       "inverter_kw": result.design_opt.inverter_kw,
                       "generator_kw": result.design_opt.generator_kw},
        "z_rule_usd_yr": result.z_rule,
        "z_opt_usd_yr": result.z_opt,
        "price_rel_pct": result.price_rel,
        "price_abs_usd_yr": result.price_abs,
        "proven": result.proven,
        "simulations": result.simulations,
        "relaxations": result.relaxations,
        "pruned_points": result.pruned_points,
        "enumerated_points": result.enumerated_points,
        "seconds": result.seconds,
        "lcoe_usd_kwh": cost.lcoe_usd_kwh,
        "npc_usd": cost.net_present_cost,
        "subsidy_fraction": cost.subsidy_fraction,
        "subsidy_usd": cost.subsidy_usd,
        "tariff_target_usd_kwh": target,
        "energy_served_kwh": served,
        "unserved_kwh": instance.demand_kwh - served,
    }


def plan_expansion(job: Job, overrides: dict[str, Any]) -> dict:
    """Build the scenario tree and descend to the expansion plan."""
    from ..config import ModelConfig
    from ..exact.tree_certify import certify_tree
    from ..model import build_model
    from ..post import expected_npc_lcoe, extract_solution, node_kpis
    from ..run import _NodeInstance
    from ..scenarios import sample_scenario_paths
    from ..solve import solve
    from ..timedomain import reduce_to_rep_days
    from ..tree import build_tree

    settings = settings_from(overrides)
    cfg = ModelConfig(solver=settings.solver.name)
    job.total = 4

    job.stage = "tirage et réduction des scénarios"
    tree = build_tree(sample_scenario_paths(cfg), cfg)
    job.done = 1

    job.stage = f"compression du domaine temporel sur {len(tree.nodes)} nœuds"
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    job.done = 2

    architecture = settings.coupling.architectures()[0]
    job.stage = "résolution du programme équivalent-déterministe"
    programme = build_model(tree, rep, cfg, architecture=architecture, settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    if solved.objective == float("inf"):
        raise RuntimeError("aucun plan admissible sous ces réglages")
    plans = extract_solution(programme, cfg)
    job.done = 3

    job.stage = "descente vers le plan que l'automate préfère"
    certificate = certify_tree(plans, tree, rep, solved.objective,
                               architecture=architecture, settings=settings, verbose=False)
    traces = certificate.traces
    expected = expected_npc_lcoe(certificate.plans, tree, traces,
                                 discount_rate=settings.economics.discount_rate)
    expected.update({
        "architecture": architecture,
        "expected_rule_cost_usd": certificate.z_rule,
        "expected_optimal_cost_usd": solved.objective,
        "price_of_heuristic_usd": certificate.z_rule - solved.objective,
        "price_of_heuristic_pct": 100.0 * (certificate.z_rule - solved.objective)
        / max(solved.objective, 1.0),
        "search_evaluations": certificate.evaluations,
    })
    job.done = 4

    root = certificate.plans[0]
    return {
        "site": settings.site,
        "architecture": architecture,
        "nodes": len(tree.nodes),
        "leaves": len(tree.leaves),
        "stages": sorted(set(tree.stage.values())),
        "reduction_error": tree.reduction_error,
        "root_plan": {"pv_kw": root.pv_kw, "pv_ac_kw": getattr(root, "pv_ac_kw", 0.0),
                      "battery_kwh": root.battery_kwh, "inverter_kw": root.inverter_kw,
                      "generator_kw": root.generator_kw},
        "expected": expected,
        "bound_usd": solved.objective,
        "rule_usd": certificate.z_rule,
        "per_node": [node_kpis(certificate.plans, n, tree, traces)
                     for n in tree.nodes],
    }
