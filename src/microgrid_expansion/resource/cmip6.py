"""Downscaling of CMIP6 climate projections into hourly meteorological series.

Bridges the resolution gap between global climate models, which publish daily means on a
coarse grid, and the hourly site-level series a dispatch model consumes. The chain has
three stages, each calibrated on the site's own history rather than on regional constants:

1. **Clear-sky envelope.** The local atmospheric transmission ceiling is estimated from the
   historical series by taking a high percentile of the ratio of measured to theoretical
   clear-sky irradiance at high sun elevations. It absorbs the humidity, aerosol load and
   seasonal dust -- the harmattan in this region -- without any of them being prescribed.
2. **Deterministic disaggregation.** Each projected daily mean is distributed over the
   hours of its day in proportion to the cosine of the solar zenith angle, which imposes a
   physically coherent diurnal shape on a quantity the climate model only resolves daily.
3. **Stochastic perturbation.** High-frequency cloud variability is restored by perturbing
   the clearness index with noise whose variance is the one measured historically, then
   clipping to the clear-sky envelope so that no hour exceeds what the sky can deliver.

This is the resource side of the scenario tree (layer L4). It is not needed for the
single-scenario layers, which use the measured history directly.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import IRRADIANCE_DIR
from ..sites import Site

SOLAR_CONSTANT_W_M2 = 1361.0

#: Shared socio-economic pathways retained; SSP5-8.5 is deliberately excluded, its emission
#: trajectory no longer being regarded as a plausible baseline.
SCENARIOS = ("ssp1_2_6", "ssp2_4_5", "ssp3_7_0")

#: Global climate models forming the multi-model ensemble.
GCM_MODELS = ("ipsl_cm6a_lr", "ec_earth3", "gfdl_esm4")

#: CMIP6 variables requested, by short name.
CMIP6_VARIABLES = {
    "rsds": "surface_downwelling_shortwave_radiation",
    "tas": "near_surface_air_temperature",
    "sfcWind": "near_surface_wind_speed",
}


def cos_zenith(latitude: float, longitude: float, day_of_year: np.ndarray,
               hour: np.ndarray) -> np.ndarray:
    """Cosine of the solar zenith angle, clipped at the horizon."""
    declination = 23.45 * np.sin(np.radians(360.0 / 365.0 * (np.asarray(day_of_year) - 80.0)))
    hour_angle = 15.0 * (np.asarray(hour) - 12.0)
    cosine = (np.sin(np.radians(latitude)) * np.sin(np.radians(declination))
              + np.cos(np.radians(latitude)) * np.cos(np.radians(declination))
              * np.cos(np.radians(hour_angle)))
    return np.clip(cosine, 0.0, None)


def clear_sky_ghi(latitude: float, longitude: float, times: pd.DatetimeIndex,
                  transmission: float = 1.0) -> np.ndarray:
    """Theoretical clear-sky global horizontal irradiance [W/m2]."""
    times = pd.DatetimeIndex(times)
    cosine = cos_zenith(latitude, longitude,
                        times.dayofyear.to_numpy(), times.hour.to_numpy())
    return SOLAR_CONSTANT_W_M2 * transmission * cosine


@dataclass
class SkyCalibration:
    """Local sky properties estimated from the site's measured history."""

    transmission: float          # atmospheric transmission ceiling [-]
    kt_mean: float               # mean daytime clearness index [-]
    kt_std: float                # its standard deviation, i.e. cloud volatility [-]


def calibrate_sky(history: pd.DataFrame, site: Site,
                  percentile: float = 98.0) -> SkyCalibration:
    """Estimate the clear-sky ceiling and the cloud volatility from measured irradiance.

    ``history`` is a site series as produced by
    :mod:`microgrid_expansion.resource.era5`.
    """
    times = pd.DatetimeIndex(history["timestamp"])
    measured = history["irradiance_w_m2"].to_numpy(dtype=float)

    theoretical = clear_sky_ghi(site.latitude, site.longitude, times, transmission=1.0)
    daylight = theoretical > 200.0
    if not daylight.any():
        raise ValueError("no daylight hours in the historical series")
    transmission = float(np.percentile(measured[daylight] / theoretical[daylight], percentile))

    envelope = clear_sky_ghi(site.latitude, site.longitude, times, transmission)
    significant = envelope > 50.0
    kt = np.clip(measured[significant] / envelope[significant], 0.0, 1.1)
    return SkyCalibration(transmission, float(kt.mean()), float(kt.std()))


def disaggregate_daily_irradiance(daily_mean_w_m2: np.ndarray, site: Site,
                                  times: pd.DatetimeIndex) -> np.ndarray:
    """Spread daily-mean irradiance over the hours by solar geometry [W/m2]."""
    times = pd.DatetimeIndex(times)
    hourly = np.zeros(len(times), dtype=float)
    day_of_year = times.dayofyear.to_numpy()
    for day in np.unique(day_of_year):
        mask = day_of_year == day
        if day - 1 >= len(daily_mean_w_m2):
            continue
        weights = cos_zenith(site.latitude, site.longitude,
                             np.full(mask.sum(), day), times.hour.to_numpy()[mask])
        total = weights.sum()
        if total > 0:
            # The day's energy is daily_mean x 24 h, redistributed by solar elevation.
            hourly[mask] = weights / total * daily_mean_w_m2[day - 1] * mask.sum()
    return hourly


def perturb_clearness(deterministic_w_m2: np.ndarray, envelope_w_m2: np.ndarray,
                      calibration: SkyCalibration,
                      rng: np.random.Generator) -> np.ndarray:
    """Restore cloud variability by perturbing the clearness index."""
    deterministic = np.asarray(deterministic_w_m2, dtype=float)
    envelope = np.asarray(envelope_w_m2, dtype=float)
    out = np.zeros_like(deterministic)
    lit = envelope > 50.0
    noise = rng.normal(0.0, calibration.kt_std, size=deterministic.shape)
    kt = np.zeros_like(deterministic)
    kt[lit] = deterministic[lit] / envelope[lit]
    out[lit] = np.clip(kt[lit] + noise[lit], 0.0, 1.0) * envelope[lit]
    return out


def extract_netcdf(archive: Path, destination: Path) -> Path:
    """Extract the single NetCDF member of a Climate Data Store ZIP.

    Replaces the shell ``unzip``/``mv`` pair the original script used, whose wildcard could
    move an unrelated file left over from an earlier download into place.
    """
    with zipfile.ZipFile(archive) as zf:
        members = [n for n in zf.namelist() if n.endswith(".nc")]
        if len(members) != 1:
            raise ValueError(f"{archive.name} holds {len(members)} NetCDF members, expected 1")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(members[0]) as src, open(destination, "wb") as dst:
            dst.write(src.read())
    return destination


def download_projection(site: Site, scenario: str, model: str, variable: str,
                        year: int, raw_dir: Path | None = None) -> Path | None:
    """Download one CMIP6 daily field for one model, scenario, variable and year."""
    import cdsapi

    raw_dir = (IRRADIANCE_DIR / "raw") if raw_dir is None else raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"cmip6_{site.name.lower()}_{model}_{scenario}_{variable}_{year}.nc"
    if target.exists():
        return target

    box = [site.latitude + 0.13, site.longitude - 0.13,
           site.latitude - 0.13, site.longitude + 0.13]
    archive = target.with_suffix(".zip")
    try:
        cdsapi.Client().retrieve(
            "projections-cmip6",
            {
                "format": "zip",
                "temporal_resolution": "daily",
                "experiment": scenario,
                "level": "single_levels",
                "variable": CMIP6_VARIABLES[variable],
                "model": model,
                "date": f"{year}-01-01/{year}-12-31",
                "area": box,
            },
            str(archive),
        )
        extract_netcdf(archive, target)
        return target
    except Exception as error:                      # a model may not publish a scenario
        print(f"    indisponible: {model} {scenario} {variable} {year} -> {error}")
        return None
    finally:
        archive.unlink(missing_ok=True)
