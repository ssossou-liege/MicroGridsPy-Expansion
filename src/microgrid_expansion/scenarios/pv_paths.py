"""Photovoltaic yield and ambient temperature per climate pathway and stage.

Two distinct uncertainties are carried, and they are of different sizes. The first is
**inter-annual variability**: a site's yield differs by several per cent from one year to
the next, and ten years of reanalysis are available to sample it. The second is **climate
drift**: the slow change in irradiance and temperature a pathway implies, which is small
over two decades beside the first but moves systematically rather than about a mean.

Variability is therefore sampled by drawing one of the historical years, which preserves
the joint structure of irradiance and temperature — a hot cloudy week is hot *and* cloudy —
in a way no perturbation of a mean year would. Drift is applied on top as a pathway- and
horizon-dependent shift, taken from the downscaled projections when they are present and
from the pathway's published sign and magnitude when they are not.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from ..paths import IRRADIANCE_DIR
from ..resource.yield_model import (
    load_irradiance, simulate_resource_year)
from ..sites import Site, get_site

#: Annual drift used only when no downscaled projection is on disk for a pathway and year.
#: Irradiance over West Africa changes little and not monotonically under any pathway;
#: warming is the robust signal and is what actually moves a photovoltaic plant, through the
#: cell-temperature derating and the battery's ceiling.
PATHWAY_DRIFT = {
    "ssp126": {"yield_per_year": -0.0002, "warming_per_year": 0.018},
    "ssp245": {"yield_per_year": -0.0004, "warming_per_year": 0.028},
    "ssp370": {"yield_per_year": -0.0006, "warming_per_year": 0.040},
}

#: Base calendar year the milestone offsets are counted from.
BASE_YEAR = 2025


@lru_cache(maxsize=8)
def _historical(site_name: str) -> tuple[np.ndarray, np.ndarray, tuple[int, ...]]:
    """Hourly yield and temperature of every complete historical year at a site.

    Resolved through the resource layer rather than by reading the file again: the
    conversion from irradiance to yield carries the cell-temperature model and the
    conventions of the acquisition, and a second reader would eventually disagree with the
    first about one of them.
    """
    site = get_site(site_name)
    available = sorted(load_irradiance(site).index.year.unique())
    rows_yield, rows_temp, years = [], [], []
    for year in available:
        try:
            resolved = simulate_resource_year(site, int(year))
        except ValueError:
            continue
        if resolved.specific_yield.size < 8760:
            continue
        rows_yield.append(resolved.specific_yield[:8760])
        rows_temp.append(resolved.t_amb_c[:8760])
        years.append(int(year))
    if not rows_yield:
        raise ValueError(f"no complete historical year for {site_name}")
    return np.array(rows_yield), np.array(rows_temp), tuple(years)


@lru_cache(maxsize=64)
def _projected(site_name: str, pathway: str, calendar_year: int):
    """Downscaled projection for a pathway and milestone, or ``None`` if not produced."""
    from ..resource.cmip6 import read_projection_series

    site = get_site(site_name)
    frame = read_projection_series(site, pathway, calendar_year)
    if frame is None:
        return None
    resolved = simulate_resource_year(site, calendar_year, frame=frame.iloc[:8760])
    return resolved.specific_yield[:8760], resolved.t_amb_c[:8760]


def historical_years(site: Site | str = "Samionta") -> tuple[int, ...]:
    """The years available to sample."""
    name = site if isinstance(site, str) else site.name
    return _historical(name)[2]


def simulate_stage_pv(pathway: str, stage_year: int,
                      site: Site | str = "Samionta",
                      rng: np.random.Generator | None = None
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Specific yield [kW/kW] and ambient temperature [degC] for a pathway and stage.

    Two uncertainties of different natures are carried. The **climate signal** — the slow,
    pathway-dependent change in irradiance and temperature — comes from the downscaled
    projection for that pathway and milestone, when one has been produced. The
    **inter-annual variability** — the several per cent by which a site's yield differs
    from one year to the next, which is larger than the signal over two decades — is
    restored by scaling with a ratio drawn from the historical years, the projection
    supplying a single year and therefore no variability of its own.

    Without a projection on disk the signal falls back to the pathway's published warming
    rate applied to a sampled historical year, which is a weaker representation and is
    reported as such rather than passed off as the projection.
    """
    name = site if isinstance(site, str) else site.name
    yields, temperatures, years = _historical(name)
    rng = np.random.default_rng() if rng is None else rng

    annual = yields.sum(axis=1)
    variability = float(annual[int(rng.integers(0, len(years)))] / annual.mean())

    projected = _projected(name, pathway, BASE_YEAR + int(stage_year))
    if projected is not None:
        yield_, temperature = projected
        return yield_ * variability, temperature

    drift = PATHWAY_DRIFT.get(pathway, PATHWAY_DRIFT["ssp245"])
    horizon = int(stage_year)
    pick = int(rng.integers(0, len(years)))
    return (yields[pick] * (1.0 + drift["yield_per_year"]) ** horizon,
            temperatures[pick] + drift["warming_per_year"] * horizon)
