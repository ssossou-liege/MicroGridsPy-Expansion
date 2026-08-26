"""Investment-layer constraints: capacity accumulation, and what a converter admits.

Capacity accumulates from the parent node, so a plan is a sequence of additions rather than
a sequence of unrelated sizings, and non-anticipativity is structural: a variable indexed by
node cannot see the branch it does not belong to.

The generator is a single active unit drawn from a catalogue, upgraded rather than
accumulated: two generating sets on one bus is a different plant, not a bigger one.
"""
from __future__ import annotations

import linopy
import numpy as np

from .. import config
from ..config import ModelConfig
from .coords import Coords


def add_investment_constraints(m: linopy.Model, v: dict, c: Coords,
                               cfg: ModelConfig, architecture: str = "dc") -> None:
    """Capacity recursions, the generator state, and the array-to-converter ceiling."""
    ratio = (config.DC_AC_RATIO_MAX if architecture == "dc" else config.AC_RATIO_MAX)
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)

    m.add_constraints(v["z_ge"].sum("gsize") == 1, name="one_generator")

    for n in c.node:
        parent = c.parent[int(n)]
        cap_pv = _accumulated(v, c, int(n), "b_pv", cfg.pv_unit_kw)
        cap_batt = _accumulated(v, c, int(n), "b_batt", cfg.batt_unit_kwh)
        cap_inv = _accumulated(v, c, int(n), "b_inv", cfg.inv_unit_kw)
        cap_gen = sum(float(r) * v["z_ge"].sel(node=int(n), gsize=k)
                      for k, r in enumerate(ratings))

        # An array is admitted by its converter and by nothing else. Under direct-current
        # coupling the conversion is bought with the hybrid inverter, so this ceiling is
        # the only thing standing between the plan and free photovoltaic capacity.
        m.add_constraints(cap_pv - ratio * cap_inv <= 0, name=f"array_ratio_{int(n)}")

        # The generating set is replaced on upgrade, never shrunk: a plant does not sell
        # its generator back.
        if parent is not None:
            parent_gen = sum(float(r) * v["z_ge"].sel(node=int(parent), gsize=k)
                             for k, r in enumerate(ratings))
            m.add_constraints(cap_gen - parent_gen >= 0, name=f"gen_monotone_{int(n)}")


def _accumulated(v: dict, c: Coords, node: int, module: str, unit: float):
    """Installed capacity at a node: the modules added along the path from the root."""
    chain, cursor = [], node
    while cursor is not None:
        chain.append(cursor)
        cursor = c.parent[cursor]
    return unit * sum(v[module].sel(node=int(k)) for k in chain)


def capacity(v: dict, c: Coords, node: int, cfg: ModelConfig):
    """The four capacities at a node, as linear expressions."""
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)
    return (_accumulated(v, c, node, "b_pv", cfg.pv_unit_kw),
            _accumulated(v, c, node, "b_batt", cfg.batt_unit_kwh),
            _accumulated(v, c, node, "b_inv", cfg.inv_unit_kw),
            sum(float(r) * v["z_ge"].sel(node=node, gsize=k)
                for k, r in enumerate(ratings)))
