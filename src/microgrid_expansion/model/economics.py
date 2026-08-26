"""Objective: expected discounted cost over the scenario tree.

Investment is charged where it is made, at the prices of that node's cost future, and
operation is charged for the years the node stands for. Both are discounted to the base
year and weighted by the node's path probability, so what is minimised is an expectation
over the tree rather than the cost of any one future.

Each asset is annualised over its own service life rather than the horizon's, for the
reason layer L3 established: a ten-year inverter charged at a twenty-five-year factor looks
two fifths cheaper than it is, and that is exactly the bias which produces oversized
converters.
"""
from __future__ import annotations

import linopy
import numpy as np

from .. import config
from ..config import ModelConfig
from .coords import Coords
from .investment_constraints import capacity


def annualised_unit_costs(costs: dict, architecture: str, settings) -> tuple[float, ...]:
    """Annual cost of one unit of each capacity at a node's prices."""
    conversion = (0.0 if architecture == "dc" else costs["capex_conv_ac"])
    return (
        costs["capex_pv"] * (config.crf(n=config.PV_LIFETIME_Y) + config.PV_OM_RATE)
        + conversion * (config.crf(n=config.CONV_LIFETIME_Y) + config.CONV_OM_RATE),
        costs["capex_batt"] * (config.crf(n=config.BATT_LIFETIME_Y) + config.BATT_OM_RATE),
        costs["capex_inv"] * (config.crf(n=config.INV_LIFETIME_Y) + config.INV_OM_RATE),
        costs["capex_ge"] * (config.crf(n=config.GEN_LIFETIME_Y) + config.GEN_OM_RATE),
    )


def add_objective(m: linopy.Model, v: dict, c: Coords, cfg: ModelConfig, data: dict,
                  generator, fuel_minorant: tuple[float, float],
                  architecture: str = "dc", settings=None) -> None:
    """Expected discounted cost of the plan and of operating it."""
    from ..settings import default_settings

    settings = default_settings() if settings is None else settings
    voll = settings.economics.value_of_lost_load_usd_kwh
    degradation = settings.battery.degradation_usd_kwh()
    fuel_0, fuel_1 = fuel_minorant

    total = 0.0
    for n in c.node:
        node = int(n)
        block = data[node]
        weight = float(c.prob[node]) * float(c.disc[node])
        years = float(c.n_years[node])
        cap_pv, cap_batt, cap_inv, cap_gen = capacity(v, c, node, cfg)
        a_pv, a_batt, a_inv, a_gen = annualised_unit_costs(
            block["costs"], architecture, settings)

        capital = (a_pv * cap_pv + a_batt * cap_batt + a_inv * cap_inv + a_gen * cap_gen)

        # Representative days stand for many days each; the weights carry that, and the
        # operating cost is annualised inside the objective rather than scaled after it.
        day_weight = _hour_weights(c)
        fuel = block["costs"]["fuel_price"]
        operating = (
            (day_weight * fuel * fuel_1 * v["p_gen"].sel(node=node)).sum()
            + (day_weight * fuel * fuel_0 * v["commit"].sel(node=node)).sum()
            + (day_weight * degradation * v["p_dis"].sel(node=node)).sum()
            + (day_weight * voll * v["unserved"].sel(node=node)).sum()
        )
        total = total + weight * years * (capital + operating)

    m.add_objective(total)


def _hour_weights(c: Coords):
    """Days each hour of the compressed year stands for."""
    import xarray as xr
    return xr.DataArray(np.asarray(c.hour_weight, dtype=float),
                        coords={"step": c.step}, dims="step")
