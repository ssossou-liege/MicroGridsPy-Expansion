"""Demand realisations from the calibrated RAMP generator.

Draws a stochastic 8760-hour demand profile for each stage of a scenario path from
the calibrated appliance parameters in ``data/ramp_params/`` (behavioural clusters,
appliance stock, usage patterns) together with the connection growth between stages.

Produces, per stage, the array ``D`` [kW] entering the formulation (parameter
``D_{n,t,h}`` after time-domain reduction).
"""
from __future__ import annotations

import numpy as np

from .uncertainty_space import DemandAxis


def simulate_stage_demand(
    demand_axis: DemandAxis,
    stage_year: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Return an 8760-hour demand profile [kW] for one stage.

    Draws a community composition from the calibrated cluster mixture, simulates each
    cluster's appliance usage with RAMP, and applies the connection growth for
    ``stage_year``. Stub for the skeleton.
    """
    raise NotImplementedError(
        "Wire to the calibrated RAMP cluster generator (data/ramp_params/)."
    )
