"""Assemble Monte-Carlo paths into fully-resolved :class:`ScenarioPath` objects.

Joins the per-stage axis draws with the heavy hourly arrays (demand, specific yield,
temperature) and the per-stage cost dictionary, producing the inputs consumed by the
scenario-tree reduction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import ModelConfig
from . import cost_paths, demand_paths, pv_paths, mc_sampler
from .uncertainty_space import UncertaintySpace


@dataclass
class AxisDraw:
    """One stage's realisation across the four uncertainty families."""

    stage_year: int
    resource: str                       # SSP pathway
    policy: float                       # minimum penetration target
    costs: dict[str, float] = field(default_factory=dict)
    trajectory: str = "centrale"        # demand growth, held over the path
    cost_scenario: str = "central"      # cost future, held over the path
    #: Whether the national grid has reached the village by this milestone. A state, not an
    #: event: once the line is there it stays.
    grid_connected: bool = False


@dataclass
class ScenarioPath:
    """A complete Monte-Carlo realisation along the planning horizon."""

    path_id: int
    draws: list[AxisDraw]               # one per stage
    demand: dict[int, np.ndarray]       # stage_year -> 8760 kW
    pv_unit: dict[int, np.ndarray]      # stage_year -> 8760 kW per installed kW
    t_amb: dict[int, np.ndarray]        # stage_year -> 8760 degC


def sample_scenario_paths(
    cfg: ModelConfig,
    space: UncertaintySpace | None = None,
) -> list[ScenarioPath]:
    """Draw and fully resolve ``cfg.n_mc_paths`` scenario paths.

    Skeleton: structures the loop and delegates the heavy realisation to the
    per-axis modules (currently stubs that raise ``NotImplementedError``).
    """
    space = space or UncertaintySpace()
    rng = np.random.default_rng(cfg.seed)
    raw_paths = mc_sampler.sample_paths(cfg, space)

    site = getattr(cfg, "site", "Samionta")
    resolved: list[ScenarioPath] = []
    for pid, raw in enumerate(raw_paths):
        draws, demand, pv_unit, t_amb = [], {}, {}, {}
        for stage in raw:
            y = stage["stage_year"]
            costs = cost_paths.stage_costs(space.economic, y, rng,
                                           scenario=stage["cost_scenario"])
            draws.append(AxisDraw(y, stage["resource"], stage["policy"], costs,
                                  trajectory=stage["trajectory"],
                                  cost_scenario=stage["cost_scenario"],
                                  grid_connected=bool(stage.get("grid_connected", False))))
            demand[y] = demand_paths.simulate_stage_demand(
                space.demand, y, rng, site=site, trajectory=stage["trajectory"])
            pv_unit[y], t_amb[y] = pv_paths.simulate_stage_pv(
                stage["resource"], y, site=site, rng=rng)
        resolved.append(ScenarioPath(pid, draws, demand, pv_unit, t_amb))
    return resolved
