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


def extract_solution(programme, cfg) -> dict[int, NodePlan]:
    """Installed capacity at every node, accumulated along its path from the root."""
    v, c = programme.variables, programme.coords
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)
    added = {name: np.asarray(v[name].solution, dtype=float)
             for name in ("b_pv", "b_batt", "b_inv")}
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
            pv_kw=cfg.pv_unit_kw * sum(added["b_pv"][k] for k in chain),
            battery_kwh=cfg.batt_unit_kwh * sum(added["b_batt"][k] for k in chain),
            inverter_kw=cfg.inv_unit_kw * sum(added["b_inv"][k] for k in chain),
            generator_kw=float(ratings @ chosen[index[node]]),
        )
    return plans
