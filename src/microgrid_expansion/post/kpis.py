"""Key performance indicators: net present cost and levelised cost of electricity.

Net-present-cost accounting:
capital cost, O&M, fuel, periodic battery replacement and end-of-horizon salvage,
annualised through the capital recovery factor. KPIs are reported per node and as the
probability-weighted expectation over the tree.

Brownfield / replacement accounting: existing capacity (C^g_0) is sunk and carries no
capital charge; only added modules and generator upgrades are costed. Each asset carries
a vintage so that battery replacement, generator resale/transfer (V^ge_s) and
end-of-horizon salvage are timed and depreciated from the installation date, not from
year 0.
"""
from __future__ import annotations

from .. import config
from ..tree.tree_model import ScenarioTree


def node_kpis(plans: dict, node: int, tree: ScenarioTree, simulated: dict) -> dict:
    """What the plant at one node delivers, and what it costs to deliver it.

    ``simulated`` carries the controller's own trajectory at this node — the upper oracle —
    so the indicators describe the plant as it will actually be run rather than as a
    programme would run it.
    """
    plan = plans[node]
    trace = simulated[node]
    served = trace["served_kwh"]
    return {
        "node": node,
        "stage": tree.stage[node],
        "probability": tree.prob[node],
        "pv_kw": plan.pv_kw,
        "pv_ac_kw": getattr(plan, "pv_ac_kw", 0.0),
        "battery_kwh": plan.battery_kwh,
        "inverter_kw": plan.inverter_kw,
        "generator_kw": plan.generator_kw,
        "annual_cost_usd": trace["annual_cost_usd"],
        "energy_served_kwh": served,
        "unserved_kwh": trace["unserved_kwh"],
        "lpsp_pct": 100.0 * trace["unserved_kwh"] / max(served + trace["unserved_kwh"], 1e-9),
        "solar_penetration_pct": 100.0 * (1.0 - trace["generator_kwh"] / max(served, 1e-9)),
        "fuel_litres": trace["fuel_litres"],
    }


def expected_npc_lcoe(plans: dict, tree: ScenarioTree, simulated: dict,
                      discount_rate: float | None = None) -> dict:
    """Expected net present cost and levelised cost over the tree.

    Both are expectations over the leaves, and both are ratios of expectations rather than
    expectations of ratios: the operator pays the expected cost and sells the expected
    energy, and averaging a levelised cost over scenarios would weight a cheap kilowatt-hour
    in a large year the same as a dear one in a small year.
    """
    rate = config.DISCOUNT_RATE if discount_rate is None else discount_rate
    cost = 0.0
    energy = 0.0
    for node in tree.nodes:
        trace = simulated[node]
        weight = tree.prob[node] * tree.disc[node] * tree.n_years[node]
        cost += weight * trace["annual_cost_usd"]
        energy += weight * trace["served_kwh"]
    return {
        "expected_npc_usd": cost,
        "expected_energy_kwh": energy,
        "expected_lcoe_usd_kwh": cost / max(energy, 1e-9),
        "discount_rate": rate,
    }
