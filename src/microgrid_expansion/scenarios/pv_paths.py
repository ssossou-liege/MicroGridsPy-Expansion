"""Photovoltaic specific-yield profiles per climate scenario.

Maps an SSP pathway (ssp126/245/370) and stage year to an 8760-hour specific-
yield profile ``rho`` [kW per installed kW] and the corresponding ambient-temperature
series (used downstream for battery self-discharge and capacity derating).

Baseline data are the historical hourly irradiance series in
``data/irradiance/``; SSP-downscaled irradiance is substituted when available
(see ``data/irradiance/README.md``).
"""
from __future__ import annotations

import numpy as np


def simulate_stage_pv(
    pathway: str,
    stage_year: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(rho, t_amb)`` 8760-hour arrays for a pathway and stage.

    ``rho``   -- specific yield [kW/kW].
    ``t_amb`` -- ambient temperature [degC].
    Stub for the skeleton.
    """
    raise NotImplementedError("Load TMY / SSP irradiance and convert to specific yield.")
