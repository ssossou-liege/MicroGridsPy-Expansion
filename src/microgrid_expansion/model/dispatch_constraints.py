"""Operating-layer constraints at every node, representative day and hour.

The physics is the one layer L3 established and validated, transposed from a single year to
the tree: sources split by destination, the hybrid inverter carrying what the coupling
architecture makes it carry, and the storage recursion closed within each representative
day because the days are not consecutive.

Only one encoding of the operating layer appears here, and it is the *cost-optimal* one.
An earlier design offered a second, "rule-faithful", which added the night-reserve floor and
claimed to reproduce the field controller. It does not: the rule trajectory sits below that
floor in four to sixty per cent of the hours depending on how the plant is sized, so
imposing it would exclude the behaviour it claims to encode; and a programme minimising over
a whole horizon is anticipative, whereas the controller is causal. The distance between the
two is the quantity this study measures, and it is measured by simulating the controller,
not by constraining a programme into resembling it.
"""
from __future__ import annotations

import linopy
import numpy as np
import xarray as xr

from .. import config
from ..config import ModelConfig
from .coords import Coords
from .investment_constraints import capacity


def add_dispatch_constraints(m: linopy.Model, v: dict, c: Coords, cfg: ModelConfig,
                             data: dict, battery, generator,
                             architecture: str = "dc",
                             opening_condition: str = "fixed") -> None:
    """Balance, conversion limits and storage dynamics on the whole tree.

    ``data`` carries, per node, the arrays of the reduced operating year: ``demand``,
    ``yield``, ``usable`` and ``retention``, each shaped ``(rday, htod)``.
    """
    ac_coupled = architecture == "ac"
    divided = architecture == "mixte"
    eta_pv = (battery.charge_efficiency * config.AC_DOUBLE_CONVERSION_EFF
              if ac_coupled else battery.charge_efficiency)
    # Array energy crossing the load's bus on its way to storage is converted twice, up by
    # the string inverter and down by the one on the battery's bus.
    eta_ac = battery.charge_efficiency * config.AC_DOUBLE_CONVERSION_EFF
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)
    big_m = float(ratings.max())

    for n in c.node:
        node = int(n)
        cap_pv, cap_batt, cap_inv, cap_gen, cap_pv_ac = capacity(v, c, node, cfg)
        block = data[node]
        demand = _grid(block["demand"], c)
        yield_ = _grid(block["yield"], c)
        usable = _grid(block["usable"], c)
        retention = _grid(block["retention"], c)

        pv_load = v["pv_load"].sel(node=node)
        pv_batt = v["pv_batt"].sel(node=node)
        gen_load = v["gen_load"].sel(node=node)
        gen_batt = v["gen_batt"].sel(node=node)
        gen_spill = v["gen_spill"].sel(node=node)
        p_dis = v["p_dis"].sel(node=node)
        curtail = v["curtail"].sel(node=node)
        ac_load = v["ac_load"].sel(node=node)
        ac_batt = v["ac_batt"].sel(node=node)
        ac_curtail = v["ac_curtail"].sel(node=node)
        unserved = v["unserved"].sel(node=node)
        p_gen = v["p_gen"].sel(node=node)
        commit = v["commit"].sel(node=node)
        soc = v["soc"].sel(node=node)

        # every kilowatt the array makes goes to the load, to the battery, or nowhere
        m.add_constraints(pv_load + pv_batt + curtail - yield_ * cap_pv == 0,
                          name=f"pv_split_{node}")
        m.add_constraints(gen_load + gen_batt + gen_spill - p_gen == 0,
                          name=f"gen_split_{node}")
        m.add_constraints(ac_load + ac_batt + ac_curtail - yield_ * cap_pv_ac == 0,
                          name=f"pv_ac_split_{node}")
        m.add_constraints(pv_load + ac_load + gen_load + p_dis + unserved == demand,
                          name=f"balance_{node}")
        m.add_constraints(unserved - demand <= 0, name=f"unserved_cap_{node}")

        m.add_constraints(p_gen - cap_gen <= 0, name=f"gen_rating_{node}")
        m.add_constraints(p_gen - big_m * commit <= 0, name=f"gen_commit_{node}")
        m.add_constraints(
            p_gen - generator.min_load_fraction * cap_gen + big_m * (1 - commit) >= 0,
            name=f"gen_min_{node}")

        # what the hybrid inverter carries is what the architecture makes it carry
        if ac_coupled:
            m.add_constraints(pv_batt + gen_batt + p_dis - cap_inv <= 0,
                              name=f"inverter_{node}")
        else:
            # The field on the load's bus reaches the load without conversion but must be
            # rectified to reach storage, so it competes there with everything else.
            m.add_constraints(pv_load + p_dis + gen_batt + ac_batt - cap_inv <= 0,
                              name=f"inverter_{node}")

        m.add_constraints(pv_batt + ac_batt + gen_batt
                          - battery.c_rate * cap_batt <= 0,
                          name=f"charge_rate_{node}")
        m.add_constraints(p_dis - battery.c_rate * cap_batt <= 0,
                          name=f"discharge_rate_{node}")

        # The storage recursion runs across the node's whole year. The pack opens where
        # the controller opens it and ends wherever its decisions leave it — free, not
        # closed and not reset. Splitting the year into independent days would hand the
        # programme a free recharge every morning; requiring it to close would constrain it
        # where the controller is not constrained, and the bound would then exceed the very
        # trajectory it is meant to minorise. Both were measured, and both broke the bound.
        opening = soc.isel(hend=slice(0, c.step.size)).assign_coords(hend=c.step) \
                     .rename({"hend": "step"})
        closing = soc.isel(hend=slice(1, None)).assign_coords(hend=c.step) \
                     .rename({"hend": "step"})
        m.add_constraints(
            closing - retention * opening - eta_pv * pv_batt - eta_ac * ac_batt
            - battery.charge_efficiency * gen_batt
            + (1.0 / battery.discharge_efficiency) * p_dis == 0,
            name=f"soc_dynamics_{node}")
        if opening_condition == "cyclic":
            # Legitimate once the day runs sunrise to sunrise: the pack is at its daily low
            # then, and requiring it to return there says only that a representative day
            # neither borrows from tomorrow nor lends to it. On a calendar day, cut through
            # the middle of the night, the same condition would be an arbitrary constraint
            # at an arbitrary hour.
            m.add_constraints(soc.isel(hend=0) - soc.isel(hend=-1) == 0,
                              name=f"soc_cyclic_{node}")
        else:
            m.add_constraints(
                soc.isel(hend=0)
                - battery.initial_soc_fraction * battery.soc_max * cap_batt == 0,
                name=f"soc_opening_{node}")

        ceiling = xr.DataArray(
            np.concatenate([np.asarray(block["usable"], dtype=float).ravel(),
                            [float(np.asarray(block["usable"]).ravel()[-1])]]),
            coords={"hend": np.arange(c.step.size + 1)}, dims="hend")
        m.add_constraints(soc - battery.soc_max * ceiling * cap_batt <= 0,
                          name=f"soc_upper_{node}")
        m.add_constraints(soc - battery.soc_min * cap_batt >= 0, name=f"soc_lower_{node}")


def _grid(values: np.ndarray, c: Coords) -> xr.DataArray:
    """Flatten a node's operating arrays onto the continuous time axis."""
    return xr.DataArray(np.asarray(values, dtype=float).ravel(),
                        coords={"step": c.step}, dims="step")
