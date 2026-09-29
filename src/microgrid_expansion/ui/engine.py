"""What the interface asks the engine to do, and what it gets back.

Kept apart from the routes so that the work is testable without a server, and so that the
routes stay a thin translation between HTTP and these calls.

The interface asks one question of the engine -- what should this community build now -- and
``size`` answers it. The two halves of that answer, the scenario tree and the certified
reference year, remain separate functions because they are separately testable and because
the command line still runs them one at a time.
"""
from __future__ import annotations

from typing import Any

from ..settings import ProjectSettings, default_settings
from . import schema
from .jobs import Job


def settings_from(overrides: dict[str, Any]) -> ProjectSettings:
    return schema.apply(default_settings(), dict(overrides or {}))


def size_site(job: Job, overrides: dict[str, Any],
              step: int = 0, total_steps: int = 3) -> dict:
    """Certify the sizing of one site over a reference year.

    ``step`` and ``total_steps`` let this run as part of a longer piece of work without the
    progress it reports jumping back to zero halfway through.
    """
    from ..exact.certify import Lattice, certify_exhaustive
    from ..instances import build_site_year

    settings = settings_from(overrides)
    job.total = total_steps

    job.announce("job.build")
    instance = build_site_year(settings.site, settings.year,
                               trajectory=settings.demand_trajectory,
                               maturity_months=settings.maturity_months)
    job.done = step + 1

    job.announce("job.lattice")
    lattice = Lattice.around(instance, settings)
    job.done = step + 2

    job.announce("job.certify", n=f"{lattice.size:,}".replace(",", "\u202f"))
    result = certify_exhaustive(instance, lattice, settings, verbose=False)
    job.done = step + 3

    # The certificate settles which plant is cheapest; what it costs a customer is a second
    # question, answered by running the certified design once more and pricing its life.
    from ..exact.certify import _grid_link
    from ..exact.simulator import BatteryModel, GeneratorModel, simulate
    from ..post.appraisal import price_certified_design

    design = result.design
    battery = BatteryModel.from_spec(settings.battery)
    unit = min(settings.generators,
               key=lambda g: abs(g.rating_kw - design.generator_kw))
    generator = GeneratorModel.from_spec(unit, settings.economics.diesel_price_usd_l)
    # The same connection the search was run against. Priced without it, a plant the search
    # chose *because* it has a grid is charged as though it had none: at sixty per cent
    # availability that turned a levelised cost of 0.21 into 0.35, on the same design.
    link = _grid_link(instance, settings)
    dispatch = simulate(instance.demand_kw, instance.specific_yield, instance.t_amb_c,
                        design, battery, generator, grid=link)
    priced = price_certified_design(instance, design, settings, dispatch, generator)
    cost, finance = priced.cost, priced.finance
    served = priced.energy_served_kwh
    unsubsidised = priced.finance_unsubsidised

    return {
        "site": settings.site,
        "binding_ceilings": list(priced.binding_ceilings),
        "battery_life_years": priced.battery_life_years,
        "infrastructure_usd": priced.infrastructure_usd,
        "trajectory": settings.demand_trajectory,
        "currency": _currency(settings),
        "finance": finance.to_dict(),
        "finance_unsubsidised": {"irr": unsubsidised.irr,
                                 "payback_years": unsubsidised.payback_years,
                                 "net_present_value_usd": unsubsidised.net_present_value},
        "dispatch": _dispatch_traces(instance, dispatch),
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
        "tariff_target_usd_kwh": cost.tariff_target_usd_kwh,
        "energy_served_kwh": served,
        "unserved_kwh": instance.demand_kwh - served,
    }


def plan_expansion(job: Job, overrides: dict[str, Any],
                   step: int = 0, total_steps: int = 4) -> dict:
    """Build the scenario tree and descend to the expansion plan.

    ``step`` and ``total_steps`` place its four stages inside a longer run, as above.
    """
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
    job.total = total_steps

    job.announce("job.sample")
    tree = build_tree(sample_scenario_paths(cfg), cfg)
    job.done = step + 1

    job.announce("job.reduce", n=len(tree.nodes))
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    job.done = step + 2

    architecture = settings.coupling.architectures()[0]
    job.announce("job.solve")
    programme = build_model(tree, rep, cfg, architecture=architecture, settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    if solved.objective == float("inf"):
        raise RuntimeError("no feasible plan under these settings")
    # The dispatch gap is measured against what the anticipative programme can be *proven*
    # to cost, not against the best plan its solver happened to reach before stopping at a
    # tolerance. The two differ by about a hundredth of a per cent here, and only the first
    # is a bound.
    lower = solved.bound
    plans = extract_solution(programme, cfg)
    job.done = step + 3

    job.announce("job.descend")
    certificate = certify_tree(plans, tree, rep, lower,
                               architecture=architecture, settings=settings, verbose=False)
    traces = certificate.traces
    from ..exact.certify import _infrastructure_usd_yr

    expected = expected_npc_lcoe(certificate.plans, tree, traces,
                                 discount_rate=settings.economics.discount_rate,
                                 infrastructure_usd_yr=_infrastructure_usd_yr(settings))
    expected.update({
        "architecture": architecture,
        "expected_rule_cost_usd": certificate.z_rule,
        "expected_optimal_cost_usd": lower,
        "expected_optimal_mip_gap": solved.mip_gap,
        "price_of_heuristic_usd": certificate.z_rule - lower,
        "price_of_heuristic_pct": 100.0 * (certificate.z_rule - lower)
        / max(lower, 1.0),
        "search_evaluations": certificate.evaluations,
    })
    job.done = step + 4

    root = certificate.plans[0]
    return {
        "site": settings.site,
        "currency": _currency(settings),
        "architecture": architecture,
        "nodes": len(tree.nodes),
        "leaves": len(tree.leaves),
        "stages": sorted(set(tree.stage.values())),
        "reduction_error": tree.reduction_error,
        "root_plan": {"pv_kw": root.pv_kw, "pv_ac_kw": getattr(root, "pv_ac_kw", 0.0),
                      "battery_kwh": root.battery_kwh, "inverter_kw": root.inverter_kw,
                      "generator_kw": root.generator_kw},
        "expected": expected,
        "bound_usd": lower,
        "rule_usd": certificate.z_rule,
        "per_node": [node_kpis(certificate.plans, n, tree, traces)
                     for n in tree.nodes],
    }


def size(job: Job, overrides: dict[str, Any]) -> dict:
    """What this community should build now, and what that commits it to.

    A developer has one decision to make and has to make it this year: how much array, how
    much storage, how much conversion and what generating set to buy, before knowing which
    way the demand will go. Everything else the tool computes exists to inform that one
    purchase, which is why it is answered once rather than offered as two studies between
    which the reader is left to arbitrate.

    Two pieces of work answer it, and they answer different halves.

    The scenario tree gives the decision itself. It carries every trajectory the demand may
    take, costs each of them under the plant that would be bought at its root, and returns
    the root that the whole tree agrees on. That root is the answer: it is sized for the
    futures the community may have and not for the one that happens to be drawn.

    The reference year gives the decision its standing. It is certified by exhaustion, so it
    is the only part of the answer proven optimal, and it is where the tariff, the return and
    the hour-by-hour dispatch are computed -- a year has hours, a tree has representative
    days. Read together they say what to build and what it will cost to run.

    The two designs need not coincide, and where they part it is worth reading. The tree
    sizes for a demand that grows; the reference year sizes for the demand as it is. A tree
    root materially above the certified plant is the cost of the growth being provided for.
    """
    plan = plan_expansion(job, overrides, step=0, total_steps=7)
    certificate = size_site(job, overrides, step=4, total_steps=7)

    root, certified = plan["root_plan"], certificate["design"]
    parts = ("pv_kw", "battery_kwh", "inverter_kw", "generator_kw")
    agreement = {k: {"first_stage": round(float(root.get(k, 0.0)), 3),
                     "reference_year": round(float(certified.get(k, 0.0)), 3),
                     "difference": round(float(root.get(k, 0.0))
                                         - float(certified.get(k, 0.0)), 3)}
                 for k in parts}

    return {
        "site": plan["site"],
        "currency": plan["currency"],
        "architecture": plan["architecture"],
        "plant": root,
        # Said plainly, because it is the standing of the answer and not a detail of it: the
        # reference year is optimal among every design the lattice holds, by exhaustion; the
        # year-0 decision is the root of a coordinated descent over the tree, and no bound
        # has been closed on it. Certifying it is the open piece of this work.
        "proven": {"reference_year": bool(certificate["proven"]), "first_stage": False},
        "expected": plan["expected"],
        "tree": {"nodes": plan["nodes"], "leaves": plan["leaves"],
                 "stages": plan["stages"], "reduction_error": plan["reduction_error"],
                 "bound_usd": plan["bound_usd"], "rule_usd": plan["rule_usd"],
                 "per_node": plan["per_node"]},
        "reference": certificate,
        "agreement": agreement,
    }


def _dispatch_traces(instance, dispatch) -> dict:
    """What the controller did, at two resolutions a reader can hold.

    The year is 8 760 hours; sending it whole would be a megabyte of numbers to draw a line
    nobody can read. Two views answer the questions a developer actually asks of a dispatch:
    one week at full resolution, to see the shape of a day and how the night is carried, and
    the monthly energy split, to see what the plant runs on over a year.

    The week shown is the one whose generator runs most, since a plant is judged on its worst
    stretch rather than its easiest.
    """
    import numpy as np

    demand = np.asarray(instance.demand_kw, dtype=float)
    n = demand.size
    gen = np.asarray(dispatch.generator_kw, dtype=float)
    pv_load = np.asarray(dispatch.pv_to_load_kw, dtype=float)
    discharge = np.asarray(dispatch.discharge_kw, dtype=float)
    charge = np.asarray(dispatch.charge_kw, dtype=float)
    soc = np.asarray(dispatch.soc_kwh, dtype=float)[:n]
    curtailed = np.asarray(dispatch.curtailed_kw, dtype=float)
    unserved = np.asarray(dispatch.unserved_kw, dtype=float)

    week = 24 * 7
    if n >= week:
        totals = [gen[i:i + week].sum() for i in range(0, n - week + 1, 24)]
        start = int(np.argmax(totals)) * 24
    else:
        start = 0
    sl = slice(start, min(start + week, n))
    r = lambda a: [round(float(x), 3) for x in a[sl]]        # noqa: E731

    months = np.minimum((np.arange(n) // 730), 11)           # 730 h ≈ one twelfth of a year
    def by_month(values):
        return [round(float(values[months == m].sum()), 1) for m in range(12)]

    return {
        "week_start_hour": int(start),
        "hours": list(range(int(start), int(start) + len(r(demand)))),
        "demand": r(demand), "pv_load": r(pv_load), "discharge": r(discharge),
        "generator": r(gen), "charge": r(charge), "soc": r(soc),
        "unserved": r(unserved),
        "monthly": {"pv_load": by_month(pv_load), "discharge": by_month(discharge),
                    "generator": by_month(gen), "curtailed": by_month(curtailed),
                    "unserved": by_month(unserved)},
        "soc_max_kwh": round(float(soc.max()), 1),
    }


def fetch_resource(job: Job, site_name: str, first_year: int = 2016,
                   last_year: int = 2025) -> dict:
    """Obtain the meteorological series for a described site's coordinates.

    A community the tool has never seen has no irradiance record, and this is the one part
    of describing a site that cannot be done from local knowledge alone: it needs a
    reanalysis, and therefore a network and an account. The failure is reported as what it
    is rather than as a modelling error, because a developer working from a field office
    needs to know it is the connection that failed and not their site description.
    """
    from ..resource.era5 import download_era5
    from ..sites import get_site, save_site
    from dataclasses import replace

    site = get_site(site_name)
    if site.latitude is None or site.longitude is None:
        raise ValueError("the site has no coordinates; place it on the map first")

    job.total = 2
    job.announce("job.reanalysis", lat=f"{site.latitude:.4f}", lon=f"{site.longitude:.4f}")
    try:
        path = download_era5(site, first_year, last_year)
    except ImportError as exc:
        raise RuntimeError("the Climate Data Store client is not installed "
                           "(pip install cdsapi)") from exc
    except Exception as exc:                      # noqa: BLE001 - reported to the page
        raise RuntimeError(
            f"the reanalysis could not be fetched: {exc}. Check the connection and the "
            "~/.cdsapirc credentials file."
        ) from exc
    job.done = 1

    job.announce("job.store")
    save_site(replace(site, irradiance_file=path.name))
    job.done = 2
    return {"site": site.name, "file": path.name,
            "years": [first_year, last_year],
            "latitude": site.latitude, "longitude": site.longitude}


def describe_archetypes(site_name: str, lang: str = "en") -> dict:
    """The archetypes in force for a site, with the note on where they come from."""
    from ..demand import archetypes as A
    from .i18n import t

    local, adjusted = A.for_site(site_name)
    labels = {"0": "arch.0", "1": "arch.1", "2": "arch.2", "3": "arch.3"}

    def rendered(a):
        record = a.to_dict()
        key = labels.get(a.cluster)
        if key:
            record["label"] = t(key, lang)
        return record

    return {"archetypes": [rendered(a) for a in local],
            "shipped": [rendered(a) for a in A.shipped()],
            "adjusted": adjusted, "note": t("arch.note", lang)}


def _currency(settings) -> dict:
    """What the page needs to restate a dollar amount in the currency of the country.

    The conversion is sent rather than applied, so every figure crossing the wire stays in
    the unit the model computed it in and only the display changes. A result exported today
    and reopened after the rate has moved is then still the same result.
    """
    c = settings.currency
    return {"code": c.local_code, "per_usd": round(c.local_per_usd, 6),
            "note": c.rate_note}
