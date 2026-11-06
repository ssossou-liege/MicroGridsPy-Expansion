"""Read a solved tree programme back into capacities per node."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class NodePlan:
    """The plant standing at one node of the tree."""

    node: int
    pv_kw: float
    battery_kwh: float
    inverter_kw: float
    generator_kw: float
    #: Array on the load's bus; zero unless the field is divided between the two.
    pv_ac_kw: float = 0.0


def extract_solution(programme, cfg, settings=None) -> dict[int, NodePlan]:
    """Capacity standing at every node: what was already there, plus what the plan adds.

    The plant on the ground comes from ``settings``, the same object the programme was
    built from, rather than as a figure each caller passes. Nine callers read a solution
    and one of them forgetting would report a brownfield plan as its extension alone, with
    the village apparently running on the modules the plan buys.
    """
    from ..model.investment_constraints import installed_base

    base = installed_base(None if settings is None
                          else getattr(settings, "installed", None))
    v, c = programme.variables, programme.coords
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)
    added = {name: np.asarray(v[name].solution, dtype=float)
             for name in ("b_pv", "b_batt", "b_inv", "b_pv_ac")}
    chosen = np.asarray(v["z_ge"].solution, dtype=float)
    index = {int(n): k for k, n in enumerate(c.node)}

    plans = {}
    for node in c.node:
        node = int(node)
        chain, cursor = [], node
        while cursor is not None:
            chain.append(index[cursor])
            cursor = c.parent[cursor]
        plans[node] = NodePlan(
            node=node,
            pv_kw=base[0] + cfg.pv_unit_kw * sum(added["b_pv"][k] for k in chain),
            battery_kwh=base[1] + cfg.batt_unit_kwh * sum(added["b_batt"][k]
                                                          for k in chain),
            inverter_kw=base[2] + cfg.inv_unit_kw * sum(added["b_inv"][k] for k in chain),
            # The chosen rating is the whole set, the standing one having been a floor on
            # the choice rather than something to build on.
            generator_kw=float(ratings @ chosen[index[node]]),
            pv_ac_kw=base[4] + cfg.pv_unit_kw * sum(added["b_pv_ac"][k] for k in chain),
        )
    return plans
