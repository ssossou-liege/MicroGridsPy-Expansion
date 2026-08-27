"""The upper oracle over a scenario tree: the controller, run node by node.

Layer L3 established that the rule-based controller has no formulation a solver can absorb —
it is an algorithm, and the distance between it and an anticipative programme is the very
quantity this study measures. The tree changes the accounting but not that fact: what a plan
costs under the deployed controller is a probability-weighted sum of simulations, one per
node, each over the representative days that node stands for.

Nothing here optimises. It evaluates a plan, which is what an upper oracle does.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import config
from ..settings import ProjectSettings, default_settings
from ..timedomain.rep_days import RepDays
from ..tree.tree_model import ScenarioTree
from .simulator import BatteryModel, Capacities, Controller, GeneratorModel, simulate

HOURS_PER_DAY = 24


@dataclass
class NodeTrace:
    """What the controller did at one node, and what it cost over a year there."""

    annual_cost_usd: float
    served_kwh: float
    unserved_kwh: float
    generator_kwh: float
    fuel_litres: float
    feasible: bool


def simulate_node(plan, year: dict, costs: dict, settings: ProjectSettings,
                  architecture: str, controller: Controller) -> NodeTrace:
    """Run the controller over a node's whole operating year, uncompressed."""
    battery = BatteryModel.from_spec(settings.battery)
    unit = min(settings.generators,
               key=lambda g: abs(g.rating_kw - plan.generator_kw))
    generator = GeneratorModel.from_spec(unit, costs["fuel_price"])
    capacities = Capacities(pv_kw=plan.pv_kw, battery_kwh=plan.battery_kwh,
                            inverter_kw=plan.inverter_kw,
                            generator_kw=plan.generator_kw,
                            pv_ac_kw=getattr(plan, "pv_ac_kw", 0.0),
                            architecture=architecture)

    if architecture == "mixte":
        admissible = capacities.admissible(config.DC_AC_RATIO_MAX, config.AC_RATIO_MAX)
    else:
        ratio = config.DC_AC_RATIO_MAX if architecture == "dc" else config.AC_RATIO_MAX
        admissible = capacities.admissible(ratio)
    if not admissible:
        return NodeTrace(float("inf"), 0.0, 0.0, 0.0, 0.0, False)

    degradation = settings.battery.degradation_usd_kwh()
    voll = settings.economics.value_of_lost_load_usd_kwh
    trace = _simulate_year(year["demand"], year["yield"], year["t_amb"],
                           capacities, battery, generator, controller)
    operating = (trace["fuel"] * costs["fuel_price"]
                 + trace["discharge"] * degradation
                 + trace["unserved"] * voll)
    fuel = trace["fuel"]
    served = trace["demand"] - trace["unserved"]
    unserved = trace["unserved"]
    thermal = trace["generator"]

    from ..model.economics import annualised_unit_costs
    a_pv, a_batt, a_inv, a_gen, a_pv_ac = annualised_unit_costs(costs, architecture,
                                                                settings)
    capital = (a_pv * plan.pv_kw + a_pv_ac * capacities.pv_ac_kw
               + a_batt * plan.battery_kwh
               + a_inv * plan.inverter_kw + a_gen * plan.generator_kw)
    return NodeTrace(annual_cost_usd=capital + operating, served_kwh=served,
                     unserved_kwh=unserved, generator_kwh=thermal, fuel_litres=fuel,
                     feasible=True)


#: A representative day cannot carry the price of the heuristic, and the failure is not one
#: of resolution but of kind. Simulated in isolation the day truncates the night at
#: midnight: the controller's look-ahead runs off the end of the array and it under-provisions
#: the very night it exists to carry, which on the reference site inflated the price from
#: about five per cent to twelve. Repeating the day removes that artefact but introduces the
#: opposite one — the morrow becomes an exact copy of the day, so the controller's bounded
#: foresight is suddenly perfect and the price collapses to one per cent. The quantity being
#: measured *is* the unpredictability from one day to the next, and a representative day
#: erases it by construction.
#:
#: The upper oracle therefore runs the full operating year at every node. It can afford to:
#: a year of simulation costs some fifty milliseconds, so a plan over a tree of fifty nodes
#: is evaluated in a couple of seconds, and the search spends thousands of them. Compression
#: is imposed on the programme, which cannot solve eight thousand hours at fifty nodes; it
#: is not imposed on the simulation, and imposing it there would compress away the answer.


def _simulate_year(demand, yield_, temperature, capacities, battery, generator,
                   controller) -> dict:
    """Run the controller over a node's whole operating year."""
    dispatch = simulate(demand, yield_, temperature, capacities, battery, generator,
                        controller)
    return {
        "fuel": float(dispatch.fuel_litres.sum()),
        "discharge": float(dispatch.discharge_kw.sum()),
        "unserved": float(dispatch.unserved_kw.sum()),
        "generator": float(dispatch.generator_kw.sum()),
        "demand": float(np.asarray(demand, dtype=float).sum()),
    }


def evaluate_plan(plans: dict, tree: ScenarioTree, rep: dict[int, RepDays] | None = None,
                  architecture: str = "dc",
                  settings: ProjectSettings | None = None) -> tuple[float, dict]:
    """Expected discounted cost of a plan under the deployed controller.

    Returns the expectation and the per-node traces, the latter being what the indicators
    are computed from so that they describe the plant as it will be run.
    """
    settings = default_settings() if settings is None else settings
    controller = Controller(reserve_multiplier=settings.controller.reserve_multiplier,
                            lookahead_hours=settings.controller.lookahead_hours,
                            generator_setpoint=settings.controller.generator_setpoint)

    total = 0.0
    traces: dict[int, dict] = {}
    for node in tree.nodes:
        data = tree.node_data[node]
        year = {"demand": data.demand, "yield": data.pv_unit, "t_amb": data.t_amb}
        trace = simulate_node(plans[node], year, data.costs,
                              settings, architecture, controller)
        if not trace.feasible:
            return float("inf"), {}
        weight = tree.prob[node] * tree.disc[node] * tree.n_years[node]
        total += weight * trace.annual_cost_usd
        traces[node] = {
            "annual_cost_usd": trace.annual_cost_usd,
            "served_kwh": trace.served_kwh,
            "unserved_kwh": trace.unserved_kwh,
            "generator_kwh": trace.generator_kwh,
            "fuel_litres": trace.fuel_litres,
        }
    return total, traces
