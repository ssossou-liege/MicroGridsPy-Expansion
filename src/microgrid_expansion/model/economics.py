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
from .investment_constraints import added_capacity


def check_one_discount_rate(cfg: ModelConfig, settings) -> float:
    """The single rate the tree and the capital are both charged at.

    Two rates were in use, and nothing said so. The nodes were discounted at
    ``cfg.discount_rate``, which the interface sets from the project, while the capital was
    recovered at the rate ``config`` had read from the defaults when it was imported. A
    project at twelve per cent was therefore solved as a twelve-per-cent future and an
    eight-per-cent plant, which is not a conservative reading of either.

    The project's own figure is the one that governs; the configuration carries a copy
    because the tree is drawn before a settings object exists, and a copy that disagrees is
    refused here rather than averaged.
    """
    declared = float(settings.economics.discount_rate)
    carried = float(getattr(cfg, "discount_rate", declared))
    if abs(declared - carried) > 1e-12:
        raise ValueError(
            f"the project discounts at {declared:.4f} and the configuration at "
            f"{carried:.4f}; one rate decides both the tree and the capital, and it is "
            "the project's")
    return declared


def check_tree_discount_rate(tree, settings) -> float:
    """The same check between a drawn tree and the project it is costed against.

    The tree carries the rate its own discount factors were computed at, so a tree drawn
    for one project and solved against another is caught here rather than producing a
    plausible expectation over the wrong arithmetic.
    """
    declared = float(settings.economics.discount_rate)
    carried = tree.discount_rate
    if carried is not None and abs(declared - carried) > 1e-12:
        raise ValueError(
            f"the tree was discounted at {float(carried):.4f} and this project discounts "
            f"at {declared:.4f}; it would have to be drawn again")
    return declared


def annualised_unit_costs(costs: dict, architecture: str, settings) -> tuple[float, ...]:
    """Annual cost of one unit of each capacity at a node's prices.

    Five figures under the divided array: the part of the field on the load's bus buys the
    string inverters that put it there, which the part on the battery's bus does not.

    Every life, maintenance rate and discount rate is read from ``settings``. Read from
    ``config`` instead, as this did, the function took the node's *prices* from the project
    and everything it multiplied them by from the defaults: a field declared to last fifteen
    years was recovered over twenty-five, and the error was invisible because the stored
    results never move those figures.
    """
    rate = float(settings.economics.discount_rate)
    coupling = settings.coupling
    generator = max(settings.generators, key=lambda g: g.rating_kw)
    a_conv = config.crf(rate, coupling.lifetime_years) + coupling.om_rate
    a_pv = (config.crf(rate, settings.photovoltaic.lifetime_years)
            + settings.photovoltaic.om_rate)
    conversion = (0.0 if architecture in ("dc", "mixed") else costs["capex_conv_ac"])
    return (
        costs["capex_pv"] * a_pv + conversion * a_conv,
        costs["capex_batt"] * (config.crf(rate, settings.battery.lifetime_years)
                               + settings.battery.om_rate),
        costs["capex_inv"] * (config.crf(rate, settings.inverter.lifetime_years)
                              + settings.inverter.om_rate),
        costs["capex_ge"] * (config.crf(rate, generator.lifetime_years)
                             + generator.om_rate),
        costs["capex_pv"] * a_pv + costs["capex_conv_ac"] * a_conv,
    )


def add_objective(m: linopy.Model, v: dict, c: Coords, cfg: ModelConfig, data: dict,
                  generator, fuel_minorant: tuple[float, float],
                  architecture: str = "dc", settings=None) -> None:
    """Expected discounted cost of the plan and of operating it."""
    from ..settings import default_settings

    settings = default_settings() if settings is None else settings
    voll = settings.economics.value_of_lost_load_usd_kwh
    fuel_0, fuel_1 = fuel_minorant

    total = 0.0
    for n in c.node:
        node = int(n)
        block = data[node]
        weight = float(c.prob[node]) * float(c.disc[node])
        years = float(c.n_years[node])
        if years <= 0.0:
            # A persistent root stands for no year: its plant is charged at the nodes that
            # operate its span, each holding it and each carrying its regime's mass.
            continue
        # What the plan buys, not what the plant is: the array, the storage and the
        # conversion already standing were bought years ago and are not bought again. On
        # bare ground the two coincide, which is why every figure computed before this is
        # unchanged by it.
        cap_pv, cap_batt, cap_inv, cap_gen, cap_pv_ac = added_capacity(
            v, c, node, cfg, getattr(settings, "installed", None))
        a_pv, a_batt, a_inv, a_gen, a_pv_ac = annualised_unit_costs(
            block["costs"], architecture, settings)

        # No throughput charge on the storage. Its capital is recovered over its service
        # life just above; charging its wear as well, as this once did, paid for the same
        # pack twice -- once in ``a_batt`` and once per kilowatt-hour discharged. The
        # simulation the plan is certified against drops the same term, so the programme
        # stays below it.
        capital = (a_pv * cap_pv + a_pv_ac * cap_pv_ac + a_batt * cap_batt
                   + a_inv * cap_inv + a_gen * cap_gen)

        # Representative days stand for many days each; the weights carry that, and the
        # operating cost is annualised inside the objective rather than scaled after it.
        day_weight = _hour_weights(c)
        fuel = block["costs"]["fuel_price"]
        # Imported energy is paid for and injected energy is earned, at the tariffs the
        # connection carries. Both belong here rather than only in the simulation: the
        # programme is the lower bound, and a bound that cannot import prices the plant above
        # what a controller that can import achieves.
        grid = getattr(settings, "grid", None)
        import_price = grid.import_usd_kwh if grid is not None and grid.connected else 0.0
        export_price = grid.export_usd_kwh if grid is not None and grid.connected else 0.0
        operating = (
            (day_weight * fuel * fuel_1 * v["p_gen"].sel(node=node)).sum()
            + (day_weight * fuel * fuel_0 * v["commit"].sel(node=node)).sum()
            + (day_weight * voll * v["unserved"].sel(node=node)).sum()
            + (day_weight * import_price * v["grid_load"].sel(node=node)).sum()
            - (day_weight * export_price * v["grid_export"].sel(node=node)).sum()
        )
        total = total + weight * years * (capital + operating)

    m.add_objective(total)


def _hour_weights(c: Coords):
    """Days each hour of the compressed year stands for."""
    import xarray as xr
    return xr.DataArray(np.asarray(c.hour_weight, dtype=float),
                        coords={"step": c.step}, dims="step")
