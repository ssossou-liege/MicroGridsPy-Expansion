"""Declare the linopy decision variables on the coordinate system.

Investment decisions live on the node; operating decisions on the node, the representative
day and the hour. Each source is split by destination rather than aggregated into a single
balance, for the reason layer L3 established: the aggregated balance cannot say which flows
cross the hybrid inverter, and that is precisely what the two coupling architectures
disagree about.
"""
from __future__ import annotations

import linopy
import numpy as np

from .coords import Coords


def add_variables(m: linopy.Model, c: Coords, relax_commitment: bool = True) -> dict:
    """Add every variable to ``m`` and return them by name."""
    node = {"node": c.node}
    grid = {"node": c.node, "step": c.step}

    v: dict = {}
    # --- investment: modules added at each node, and the generator state
    v["b_pv"] = m.add_variables(lower=0, coords=node, integer=True, name="b_pv")
    v["b_batt"] = m.add_variables(lower=0, coords=node, integer=True, name="b_batt")
    v["b_inv"] = m.add_variables(lower=0, coords=node, integer=True, name="b_inv")
    v["z_ge"] = m.add_variables(coords={"node": c.node, "gsize": c.gsize},
                                binary=True, name="z_ge")

    # --- operating: every flow named by where it goes
    for name in ("pv_load", "pv_batt", "gen_load", "gen_batt", "gen_spill",
                 "p_dis", "curtail"):
        v[name] = m.add_variables(lower=0.0, coords=grid, name=name)
    v["unserved"] = m.add_variables(lower=0.0, coords=grid, name="unserved")
    v["p_gen"] = m.add_variables(lower=0.0, coords=grid, name="p_gen")
    v["soc"] = m.add_variables(
        lower=0.0, coords={"node": c.node, "hend": np.arange(c.step.size + 1)},
        name="soc")
    if relax_commitment:
        v["commit"] = m.add_variables(lower=0.0, upper=1.0, coords=grid, name="commit")
    else:
        v["commit"] = m.add_variables(coords=grid, binary=True, name="commit")
    return v
