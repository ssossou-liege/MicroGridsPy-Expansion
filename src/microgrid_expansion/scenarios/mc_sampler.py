"""Monte-Carlo sampling of complete uncertainty paths.

Draws ``cfg.n_mc_paths`` independent paths. Each path assigns, at every stage, a
draw from each of the four uncertainty families. The heavy hourly arrays (demand,
specific yield) are attached by :mod:`microgrid_expansion.scenarios.assemble`.
"""
from __future__ import annotations

import numpy as np

from ..config import ModelConfig
from .uncertainty_space import UncertaintySpace


def draw_axis_values(
    space: UncertaintySpace,
    stage_year: int,
    rng: np.random.Generator,
) -> dict:
    """Draw one realisation of the four families at a single stage."""
    resource = rng.choice(space.resource.pathways, p=space.resource.probabilities)
    policy = rng.choice(space.policy.penetration_levels, p=space.policy.probabilities)
    return {
        "stage_year": stage_year,
        "resource": str(resource),
        "policy": float(policy),
        # demand and economic draws are resolved lazily in assemble.py
    }


def draw_path(space: UncertaintySpace, stage_years, rng: np.random.Generator) -> list[dict]:
    """Draw one coherent path over the horizon.

    Two of the four families are drawn *once* and held: the growth trajectory and the cost
    future. A village that grows does not stop growing between two milestones, and a world
    in which storage learns quickly is one in which converters do too; redrawing either at
    each stage would manufacture a mean reversion neither the reference sites nor the
    learning literature supports. The pathway and the policy target are redrawn per stage,
    being genuinely exogenous events rather than persistent states.
    """
    from .cost_paths import draw_cost_scenario
    from .demand_paths import draw_trajectory

    trajectory = draw_trajectory(rng)
    cost_scenario = draw_cost_scenario(rng)
    stages = []
    for year in stage_years:
        stage = draw_axis_values(space, year, rng)
        stage["trajectory"] = trajectory
        stage["cost_scenario"] = cost_scenario
        stages.append(stage)
    return stages


def sample_paths(cfg: ModelConfig, space: UncertaintySpace) -> list[list[dict]]:
    """Return ``n_mc_paths`` paths, each a list of per-stage axis draws."""
    rng = np.random.default_rng(cfg.seed)
    return [draw_path(space, cfg.stage_years, rng) for _ in range(cfg.n_mc_paths)]
