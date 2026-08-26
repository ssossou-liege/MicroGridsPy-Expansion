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
SCENARIOS = ("ssp126", "ssp245", "ssp370")

#: Global climate models forming the multi-model ensemble. Three independent modelling
#: centres rather than one: the spread between models over West Africa is comparable to the
#: spread between pathways at this horizon, and a single model would present one structural
#: assumption as if it were the climate.
GCM_MODELS = ("GFDL-ESM4", "EC-Earth3", "IPSL-CM6A-LR")

#: The ensemble member published for every model in this archive.
VARIANT = "r1i1p1f1"

#: Grid label each model's files carry. It is a property of the model's native grid, not of
#: the archive, and it differs between centres — a detail worth declaring rather than
#: guessing, since guessing it wrong returns a 404 that looks exactly like a model which
#: does not publish the pathway.
GRID_LABEL = {"GFDL-ESM4": "gr1", "EC-Earth3": "gr", "IPSL-CM6A-LR": "gr",
              "MPI-ESM1-2-HR": "gn", "MRI-ESM2-0": "gn", "ACCESS-CM2": "gn"}

#: Daily variables requested, by their archive short name.
CMIP6_VARIABLES = {
    "rsds": "surface downwelling shortwave radiation [W/m2]",
    "tas": "near-surface air temperature [K]",
    "sfcWind": "near-surface wind speed [m/s]",
}

#: Source of the projections. NASA's downscaled archive is used in place of the raw model
#: output for two reasons: it is already bias-corrected and downscaled to a quarter degree,
#: which is the step this study would otherwise have to perform itself and could not
#: validate; and it is served openly, a point at a time, so that a site needs kilobytes
#: where the raw archive would need hundreds of megabytes a year and a licence agreement.
ARCHIVE = "https://ds.nccs.nasa.gov/thredds/ncss/grid/AMES/NEX/GDDP-CMIP6"


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


def _archive_url(model: str, scenario: str, variable: str, year: int) -> str:
    """Address of one model-scenario-variable-year in the downscaled archive."""
    grid = GRID_LABEL.get(model, "gn")
    stem = f"{variable}_day_{model}_{scenario}_{VARIANT}_{grid}_{year}"
    return (f"{ARCHIVE}/{model}/{scenario}/{VARIANT}/{variable}/"
            f"{stem}_v2.0.nc")


def download_projection(site: Site, scenario: str, model: str, variable: str,
                        year: int, raw_dir: Path | None = None,
                        timeout_s: int = 300) -> Path | None:
    """Fetch one daily series at the site's grid point, and cache it.

    The archive's subset service returns the single grid cell containing the site, so what
    crosses the network is a few kilobytes of comma-separated values rather than the
    global field. A model that does not publish a pathway simply yields nothing, which is
    reported and skipped rather than raised: the ensemble is what is available, and
    pretending otherwise would silently drop a site.
    """
    import requests

    raw_dir = (IRRADIANCE_DIR / "raw") if raw_dir is None else raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"nexgddp_{site.name.lower()}_{model}_{scenario}_{variable}_{year}.csv"
    if target.exists() and target.stat().st_size > 0:
        return target

    query = {
        "var": variable,
        "latitude": f"{site.latitude:.4f}",
        "longitude": f"{site.longitude:.4f}",
        "time_start": f"{year}-01-01T12:00:00Z",
        "time_end": f"{year}-12-31T12:00:00Z",
        "accept": "csv",
    }
    try:
        response = requests.get(_archive_url(model, scenario, variable, year),
                                params=query, timeout=timeout_s)
        response.raise_for_status()
        text = response.text
        if "time" not in text.split("\n", 1)[0]:
            raise ValueError("the archive returned no series")
        target.write_text(text)
        return target
    except Exception as error:
        print(f"    indisponible: {model} {scenario} {variable} {year} -> "
              f"{type(error).__name__}: {str(error)[:120]}")
        target.unlink(missing_ok=True)
        return None


def read_projection(path: Path, variable: str) -> pd.Series:
    """Daily series of one variable, indexed by date, in the model's own units."""
    frame = pd.read_csv(path)
    time_column = next(c for c in frame.columns if c.startswith("time"))
    value_column = next(c for c in frame.columns if c.startswith(variable))
    series = pd.Series(frame[value_column].to_numpy(dtype=float),
                       index=pd.to_datetime(frame[time_column]).dt.tz_localize(None).dt.normalize(),
                       name=variable)
    return series[~series.index.duplicated(keep="first")].sort_index()


def ensemble_daily(site: Site, scenario: str, year: int,
                   models: tuple[str, ...] = GCM_MODELS,
                   raw_dir: Path | None = None) -> pd.DataFrame | None:
    """Multi-model mean of the daily fields at the site, for one pathway and year.

    Averaging across models before downscaling rather than downscaling each and averaging
    after is deliberate: the disaggregation is non-linear in the daily mean only through
    the clear-sky ceiling, and averaging first keeps a single coherent series whose
    inter-model spread is reported rather than propagated into a false hourly precision.
    """
    collected: dict[str, list[pd.Series]] = {v: [] for v in CMIP6_VARIABLES}
    for model in models:
        for variable in CMIP6_VARIABLES:
            path = download_projection(site, scenario, model, variable, year,
                                       raw_dir=raw_dir)
            if path is not None:
                collected[variable].append(read_projection(path, variable))
    if not all(collected.values()):
        return None

    frame = pd.DataFrame({
        variable: pd.concat(series, axis=1).mean(axis=1)
        for variable, series in collected.items()
    }).dropna()
    frame["tas"] = frame["tas"] - 273.15                     # kelvin to celsius
    return frame.rename(columns={"rsds": "ghi_daily_w_m2", "tas": "t_amb_c",
                                 "sfcWind": "wind_speed_m_s"})


def build_hourly_series(site: Site, scenario: str, year: int,
                        history: pd.DataFrame | None = None,
                        models: tuple[str, ...] = GCM_MODELS,
                        seed: int = 0,
                        raw_dir: Path | None = None) -> pd.DataFrame | None:
    """Hourly meteorological series for one pathway and milestone year.

    Runs the three stages of the downscaling on the ensemble daily means: the clear-sky
    ceiling calibrated on the site's own history, the deterministic disaggregation of each
    daily mean over its hours, and the stochastic restoration of cloud variability.
    """
    from .yield_model import load_irradiance

    daily = ensemble_daily(site, scenario, year, models=models, raw_dir=raw_dir)
    if daily is None:
        return None
    # ``load_irradiance`` indexes by timestamp; the calibration reads it as a column.
    history = load_irradiance(site).reset_index() if history is None else history
    calibration = calibrate_sky(history, site)

    index = pd.date_range(f"{year}-01-01", periods=24 * len(daily), freq="h")
    envelope = clear_sky_ghi(site.latitude, site.longitude, index) * calibration.transmission
    deterministic = disaggregate_daily_irradiance(
        daily["ghi_daily_w_m2"].to_numpy(dtype=float), site, index)
    irradiance = perturb_clearness(deterministic, envelope, calibration,
                                   np.random.default_rng(seed))

    hourly = pd.DataFrame({
        "timestamp": index,
        "irradiance_w_m2": irradiance,
        "temperature_c": np.repeat(daily["t_amb_c"].to_numpy(dtype=float), 24),
        "wind_speed_m_s": np.repeat(daily["wind_speed_m_s"].to_numpy(dtype=float), 24),
    })
    hourly["year"] = year
    return hourly


#: All projected series for a site live in one document, indexed by pathway and year. A file
#: per pathway and milestone meant fifteen of them per site, each a copy of the same columns,
#: with the pathway and the year encoded in the file name — where nothing can read them
#: without parsing a string, and where adding a milestone means remembering the convention.
PROJECTION_FILE = "{site}_cmip6_hourly.csv"


def projection_path(site: Site) -> Path:
    return IRRADIANCE_DIR / PROJECTION_FILE.format(site=site.name.lower())


def write_hourly_series(site: Site, scenario: str, year: int, **kwargs) -> Path | None:
    """Build one pathway-year and merge it into the site's projection document."""
    hourly = build_hourly_series(site, scenario, year, **kwargs)
    if hourly is None:
        return None
    hourly.insert(1, "pathway", scenario)

    destination = projection_path(site)
    if destination.exists():
        existing = pd.read_csv(destination)
        keep = ~((existing["pathway"] == scenario) & (existing["year"] == year))
        hourly = pd.concat([existing[keep], hourly], ignore_index=True)
    hourly = hourly.sort_values(["pathway", "year", "timestamp"], kind="stable")
    hourly.to_csv(destination, index=False)
    return destination


def read_projection_series(site: Site, pathway: str, year: int) -> pd.DataFrame | None:
    """One pathway-year out of the site's projection document."""
    path = projection_path(site)
    if not path.exists():
        return None
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    block = frame[(frame["pathway"] == pathway) & (frame["year"] == year)]
    return None if block.empty else block.drop(columns=["pathway"]).reset_index(drop=True)
