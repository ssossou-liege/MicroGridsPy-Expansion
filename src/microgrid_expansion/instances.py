"""Assembly of one site-year into the arrays the oracles consume.

Both oracles need the same three hourly series — community demand, photovoltaic specific
yield and ambient temperature — for one site and one year. Producing the demand takes a
little over a minute, so a resolved instance is cached on disk: a certified sizing evaluates
the oracles thousands of times over the same instance, and regenerating it each time would
dominate the cost of the search.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .paths import REFERENCE_DIR, RESULTS_DIR
from .sites import Site, get_site

CACHE_DIR = RESULTS_DIR / "cache"


@dataclass(frozen=True)
class SiteYear:
    """One site, one year: everything the operating models need."""

    site: str
    year: int
    demand_kw: np.ndarray
    specific_yield: np.ndarray
    t_amb_c: np.ndarray
    usable_fraction: np.ndarray
    self_discharge: np.ndarray
    trajectory: str
    maturity_months: int
    seed: int
    chemistry: str = "lfp"

    @property
    def hours(self) -> int:
        return self.demand_kw.size

    @property
    def demand_kwh(self) -> float:
        return float(self.demand_kw.sum())

    @property
    def peak_kw(self) -> float:
        return float(self.demand_kw.max())


def _calibration_fingerprint() -> str:
    """Digest of the calibration tables the demand generator reads.

    Without it a cached instance survives a recalibration and the run silently sizes
    against the demand of a model that no longer exists — which is not hypothetical: the
    appliance windows were corrected under a cache that would have gone on serving the
    uncorrected year.
    """
    digest = hashlib.sha1()
    for path in sorted(REFERENCE_DIR.glob("*.csv")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _site_fingerprint(site: Site) -> str:
    """Everything about a site's description that decides the year it produces.

    The name alone is not the site. When sites were written into the source a name could
    only mean one description, and keying on it was safe; now that a site is something the
    user edits, the same name means whatever they last saved. Keyed on the name alone, the
    cache answered a community of three hundred households with the year computed for one
    hundred and fifty -- no error, no warning, a plausible number for the wrong village.
    """
    census = ";".join(f"{k}={v}" for k, v in sorted(site.census.items()))
    return "|".join(str(x) for x in (
        census, site.latitude, site.longitude, site.irradiance_file,
        site.productive_units, site.utc_offset_hours))


def _cache_key(site: str, year: int, trajectory: str, maturity_months: int,
               seed: int, chemistry: str, archetypes: str = "std",
               description: str = "") -> str:
    # The chemistry belongs in the key: it changes the storage ceiling and the
    # self-discharge the instance carries, so a cached instance from another chemistry
    # would silently describe a different battery. So does the calibration, for the same
    # reason: it decides the demand the instance carries. So does the site's own
    # description, for the plainest reason of all: it *is* the community.
    raw = (f"{site}|{year}|{trajectory}|{maturity_months}|{seed}|{chemistry}"
           f"|{_calibration_fingerprint()}|{archetypes}|{description}")
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def build_site_year(
    site: Site | str,
    year: int = 2025,
    trajectory: str = "central",
    maturity_months: int = 12,
    seed: int = 0,
    chemistry: str | None = None,
    use_cache: bool = True,
) -> SiteYear:
    """Resolve a site and year into aligned hourly series.

    The demand and the resource are produced independently and must agree in length; a
    leap year has 8 784 hours and both sides are built for the same calendar year, so a
    mismatch signals that one of them was built for another year.
    """
    from .demand import archetypes as _archetypes
    from .demand.generator import simulate_demand_year
    from .resource import simulate_resource_year

    from . import config as _config

    site = get_site(site) if isinstance(site, str) else site
    chemistry = _config.BATTERY_CHEMISTRY if chemistry is None else chemistry
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # The archetypes a site runs on are part of what a cached year is: adjusted locally and
    # not counted here, a stale file would answer with the behaviour of another community.
    key = _cache_key(site.name, year, trajectory, maturity_months, seed, chemistry,
                     _archetypes.fingerprint(site.name), _site_fingerprint(site))
    path = CACHE_DIR / f"siteyear_{site.name.lower()}_{key}.npz"

    if use_cache and path.exists():
        stored = np.load(path)
        return SiteYear(site=site.name, year=year,
                        demand_kw=stored["demand_kw"],
                        specific_yield=stored["specific_yield"],
                        t_amb_c=stored["t_amb_c"],
                        usable_fraction=stored["usable_fraction"],
                        self_discharge=stored["self_discharge"],
                        trajectory=trajectory, maturity_months=maturity_months,
                        seed=seed, chemistry=chemistry)

    demand = simulate_demand_year(site, year=year, seed=seed,
                                  maturity_months=maturity_months,
                                  trajectory=trajectory,
                                  scaling=_archetypes.scaling_for(site.name))
    resource = simulate_resource_year(site, year, chemistry=chemistry)
    if demand.hourly_kw.size != resource.specific_yield.size:
        raise ValueError(
            f"demand has {demand.hourly_kw.size} hours and the resource "
            f"{resource.specific_yield.size}; both must cover {year}"
        )

    instance = SiteYear(
        site=site.name, year=year,
        demand_kw=demand.hourly_kw,
        specific_yield=resource.specific_yield,
        t_amb_c=resource.t_amb_c,
        usable_fraction=resource.usable_fraction,
        self_discharge=resource.self_discharge,
        trajectory=trajectory, maturity_months=maturity_months, seed=seed,
        chemistry=chemistry,
    )
    if use_cache:
        np.savez_compressed(
            path, demand_kw=instance.demand_kw, specific_yield=instance.specific_yield,
            t_amb_c=instance.t_amb_c, usable_fraction=instance.usable_fraction,
            self_discharge=instance.self_discharge,
        )
    return instance
