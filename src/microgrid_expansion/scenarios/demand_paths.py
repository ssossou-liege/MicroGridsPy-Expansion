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

import hashlib

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


def draw_connection(demand_axis: DemandAxis, trajectory: str,
                    rng: np.random.Generator) -> str:
    """Pick the connection trajectory a path will follow throughout.

    Nothing is drawn under the whole census, which holds one trajectory, nor when the
    connection is paired with the growth trajectory already drawn: ``rng`` is then left
    exactly where it was.
    """
    from ..demand.connection import PAIRED_WITH_GROWTH, TRAJECTORIES as CONNECTIONS

    if demand_axis.connection_mode == "census":
        return "census"
    if demand_axis.connection_pairing == "paired":
        return PAIRED_WITH_GROWTH[trajectory]
    weights = demand_axis.connection_probabilities or (1.0 / 3, 1.0 / 3, 1.0 / 3)
    return str(rng.choice(CONNECTIONS, p=weights))


#: Realisations held per (trajectory, maturity). Given those two, the generator's draws are
#: exchangeable: what distinguishes them is the composition drawn from the mixture law and
#: the appliance noise, neither of which carries information a scenario path could use. A
#: small pool sampled with replacement therefore represents the conditional distribution as
#: faithfully as a fresh run per path, at a hundredth of the cost — and a fresh run per path
#: is not merely expensive but impossible, a thousand paths over five stages being five
#: thousand simulated years.
POOL_SIZE = 4


def _pool_key(site: Site, trajectory: str, maturity: int, year: int, seed: int,
              schedule) -> str:
    """Digest of everything that decides what a pool holds.

    The site's own description, the demand fingerprint, the calendar year, the seed, the
    growth trajectory, the village age and the connection schedule over the year. Keyed on
    the name and the fingerprint alone, an edited community of the same name was served the
    old pool, and a pool drawn for 2025 would have been served for a leap year. The
    schedule enters by the digest of its stock rather than by its trajectory's name, so two
    trajectories that agree up to the end of the year share a pool and a refit of the
    curves invalidates exactly the pools it changes.
    """
    from ..instances import _demand_fingerprint, _site_fingerprint

    raw = "|".join((_site_fingerprint(site), _demand_fingerprint(), str(int(year)),
                    str(int(seed)), trajectory, str(int(maturity)),
                    schedule.digest(until=int(maturity) + 11)))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _pool_path(site_name: str, trajectory: str, maturity: int, key: str,
               kind: str = "demand") -> Path:
    return DEMAND_POOL_DIR / (f"{kind}_{site_name.lower()}_{trajectory}_m{maturity}"
                              f"_{key}.npy")


def demand_pool(site: Site | str = "Samionta", trajectory: str = "central",
                maturity_months: int = 12, size: int = POOL_SIZE,
                year: int = 2025, seed: int = 0,
                connection=None) -> tuple[np.ndarray, np.ndarray]:
    """Realisations of one community-year, cached on disk.

    Returns the load and, beside it, the part of that load which sits at the plant rather
    than out on the network -- the air conditioning of the inverter room and the rest of
    what the plant draws to run itself. The second is needed to apply a distribution loss
    to the first, and it is held apart so that changing the loss costs nothing.

    The cache is keyed on the demand fingerprint as well as on the site and the trajectory:
    the calibration tables, the code that reads them and the appliance library alike, so a
    change to any of them invalidates the pool rather than being silently served the demand
    of a model that no longer exists. See ``_pool_key`` for the rest of the key.

    ``connection`` is the ``ConnectionSchedule`` the households follow, ``None`` the whole
    census at village month 0.
    """
    from ..demand.connection import ConnectionSchedule

    site = get_site(site) if isinstance(site, str) else site
    schedule = ConnectionSchedule.whole_census(site) if connection is None else connection

    DEMAND_POOL_DIR.mkdir(parents=True, exist_ok=True)
    key = _pool_key(site, trajectory, maturity_months, year, seed, schedule)
    path = _pool_path(site.name, trajectory, maturity_months, key)
    own = _pool_path(site.name, trajectory, maturity_months, key, kind="atplant")
    if path.exists():
        cached = np.load(path)
        if cached.shape[0] >= size:
            plant = np.load(own) if own.exists() else np.zeros_like(cached)
            return cached[:size], plant[:size]

    years = [simulate_demand_year(
        site, year, seed=seed + k, maturity_months=maturity_months,
        trajectory=trajectory, include_productive=True, connection=connection)
        for k in range(size)]
    pool = np.array([np.asarray(y.hourly_kw, dtype=float) for y in years])
    # The plant's own supply is held in its own pool rather than folded into the first,
    # because the network loss does not apply to it and because the loss is a figure a
    # developer changes. Kept apart, trying another loss costs nothing; folded in, every
    # attempt would rebuild an hour of simulated years.
    plant = np.array([np.zeros(pool.shape[1]) if y.at_plant_kw is None
                      else np.asarray(y.at_plant_kw, dtype=float) for y in years])
    np.save(path, pool)
    if plant.any():
        np.save(own, plant)
    return pool, plant


def simulate_stage_demand(demand_axis: DemandAxis, stage_year: int,
                          rng: np.random.Generator,
                          site: Site | str = "Samionta",
                          trajectory: str = "central",
                          base_maturity_months: int = 12,
                          year: int = 2025,
                          network_loss_fraction: float = 0.0,
                          connection=None) -> np.ndarray:
    """Hourly load the plant must produce at a stage, for a community aged into it.

    The distribution loss is applied here, through the same function the single certified
    year uses, so that a plan and a sizing of one village are asked for the same energy.

    ``connection`` is the path's ``ConnectionSchedule``, held over the path as the growth
    trajectory is; ``None`` is the whole census. The village age at the stage is the base
    age plus twelve months a year.
    """
    from ..instances import check_network_loss, with_network_loss

    maturity = base_maturity_months + 12 * int(stage_year)
    pool, plant = demand_pool(site, trajectory, maturity, year=year, connection=connection)
    k = int(rng.integers(0, pool.shape[0]))
    served, _ = with_network_loss(pool[k], plant[k],
                                  check_network_loss(network_loss_fraction))
    return served
