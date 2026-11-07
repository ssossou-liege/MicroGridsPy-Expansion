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


def draw_path(space: UncertaintySpace, stage_years, rng: np.random.Generator,
              connection_rng: np.random.Generator | None = None) -> list[dict]:
    """Draw one coherent path over the horizon.

    Three draws are made *once* and held: the growth trajectory, the cost future and the
    connection trajectory. A village that grows does not stop growing between two
    milestones, a household once connected stays connected, and a world in which storage
    learns quickly is one in which converters do too; redrawing any of them at each stage
    would manufacture a mean reversion neither the reference sites nor the learning
    literature supports. The pathway and the policy target are redrawn per stage, being
    genuinely exogenous events rather than persistent states.

    The connection trajectory is drawn from ``connection_rng``, a generator of its own, so
    that adding it left every other draw of every path where it was.
    """
    from .cost_paths import draw_cost_scenario
    from .demand_paths import draw_connection, draw_trajectory

    trajectory = draw_trajectory(rng, space.demand.trajectory_probabilities)
    connection = draw_connection(space.demand, trajectory,
                                 rng if connection_rng is None else connection_rng)
    cost_scenario = draw_cost_scenario(
        rng, space.economic.scenario_probabilities,
        names=getattr(space.economic, "scenario_names", ()))

    # The line arrives once and stays. Drawn per stage and forgotten between them, a village
    # would be connected at year five, off again at ten and back at fifteen, which is not
    # what a distribution network does; the arrival is a state, so it is drawn as one.
    hazards = getattr(space.grid, "hazard_by_stage", ())
    connected_from = None
    for index, _ in enumerate(stage_years):
        hazard = float(hazards[index]) if index < len(hazards) else 0.0
        if connected_from is None and hazard > 0.0 and rng.random() < hazard:
            connected_from = index

    stages = []
    for index, year in enumerate(stage_years):
        stage = draw_axis_values(space, year, rng)
        stage["trajectory"] = trajectory
        stage["cost_scenario"] = cost_scenario
        stage["connection"] = connection
        stage["grid_connected"] = (connected_from is not None and index >= connected_from)
        stages.append(stage)
    return stages


def sample_paths(cfg: ModelConfig, space: UncertaintySpace) -> list[list[dict]]:
    """Return ``n_mc_paths`` paths, each a list of per-stage axis draws."""
    rng = np.random.default_rng(cfg.seed)
    # Created once and consumed path after path, beside the stream every other draw comes
    # from, which it never touches.
    connection_rng = np.random.default_rng(np.random.SeedSequence([int(cfg.seed), 0xC0]))
    return [draw_path(space, cfg.stage_years, rng, connection_rng)
            for _ in range(cfg.n_mc_paths)]
