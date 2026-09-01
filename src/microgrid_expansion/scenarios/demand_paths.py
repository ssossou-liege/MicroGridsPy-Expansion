"""Demand realisations from the calibrated generator, stage by stage.

A path's demand is not three independent draws but one community ageing. The growth
trajectory — slow, central or fast — is drawn once and held, because a village that grows
does not stop growing between two milestones, and letting the trajectory change at each
stage would manufacture a mean reversion the two reference sites give no reason to expect.
What varies within a path is the *age* of the connection, which advances with the horizon
and moves the behavioural composition and the number of enterprises with it.

The generator is the one calibrated in layer L1 and corrected in L3: households by
behavioural archetype, productive users by a connection trajectory of their own.
"""
from __future__ import annotations

import numpy as np

from pathlib import Path

from ..demand.generator import simulate_demand_year
from ..paths import RESULTS_DIR
from ..sites import Site, get_site
from .uncertainty_space import DemandAxis

#: Growth trajectories, in the order the envelope brackets them.
TRAJECTORIES = ("slow", "central", "fast")

#: Where the realisation pools live.
DEMAND_POOL_DIR = RESULTS_DIR / "cache" / "demand_pool"


def draw_trajectory(rng: np.random.Generator,
                    probabilities: tuple[float, ...] | None = None) -> str:
    """Pick the growth trajectory a path will follow throughout."""
    weights = probabilities or (1.0 / 3, 1.0 / 3, 1.0 / 3)
    return str(rng.choice(TRAJECTORIES, p=weights))


#: Realisations held per (trajectory, maturity). Given those two, the generator's draws are
#: exchangeable: what distinguishes them is the composition drawn from the mixture law and
#: the appliance noise, neither of which carries information a scenario path could use. A
#: small pool sampled with replacement therefore represents the conditional distribution as
#: faithfully as a fresh run per path, at a hundredth of the cost — and a fresh run per path
#: is not merely expensive but impossible, a thousand paths over five stages being five
#: thousand simulated years.
POOL_SIZE = 4


def _pool_path(site_name: str, trajectory: str, maturity: int) -> Path:
    return DEMAND_POOL_DIR / f"demand_{site_name.lower()}_{trajectory}_m{maturity}.npy"


def demand_pool(site: Site | str = "Samionta", trajectory: str = "central",
                maturity_months: int = 12, size: int = POOL_SIZE,
                year: int = 2025, seed: int = 0) -> np.ndarray:
    """Realisations of one community-year, cached on disk.

    The cache is keyed on the demand fingerprint as well as on the site and the trajectory:
    the calibration tables, the code that reads them and the appliance library alike, so a
    change to any of them invalidates the pool rather than being silently served the demand
    of a model that no longer exists.
    """
    site = get_site(site) if isinstance(site, str) else site
    from ..instances import _demand_fingerprint

    DEMAND_POOL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _demand_fingerprint()
    path = _pool_path(f"{site.name}_{stamp}", trajectory, maturity_months)
    if path.exists():
        cached = np.load(path)
        if cached.shape[0] >= size:
            return cached[:size]

    drawn = [np.asarray(simulate_demand_year(
        site, year, seed=seed + k, maturity_months=maturity_months,
        trajectory=trajectory, include_productive=True).hourly_kw, dtype=float)
        for k in range(size)]
    pool = np.array(drawn)
    np.save(path, pool)
    return pool


def simulate_stage_demand(demand_axis: DemandAxis, stage_year: int,
                          rng: np.random.Generator,
                          site: Site | str = "Samionta",
                          trajectory: str = "central",
                          base_maturity_months: int = 12,
                          year: int = 2025) -> np.ndarray:
    """Hourly demand [kW] at a stage, for a community that has aged into it."""
    maturity = base_maturity_months + 12 * int(stage_year)
    pool = demand_pool(site, trajectory, maturity, year=year)
    return pool[int(rng.integers(0, pool.shape[0]))]
