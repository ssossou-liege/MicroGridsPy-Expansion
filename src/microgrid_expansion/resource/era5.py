"""Acquisition of the historical meteorological series from ERA5-Land.

Produces, for one site, the hourly series the resource layer consumes: global horizontal
irradiance, two-metre air temperature and ten-metre wind speed. It is written as a library
function with a command-line wrapper rather than a top-to-bottom script, so that a user
interface can drive it the same way the command line does.

Two conversions deserve attention, because getting either wrong corrupts the diurnal shape
without producing an obvious error.

**Accumulations.** ``ssrd`` is published in J/m2 as an accumulation, and what it
accumulates over depends on the product. The gridded ``reanalysis-era5-land`` product
accumulates from the start of the forecast day, so the hourly flux is the difference
between consecutive values; the ``reanalysis-era5-land-timeseries`` product used here
already delivers the accumulation *over each hour*, so the flux is the value divided by
3600. Applying the wrong one silently distorts the diurnal shape rather than failing, so
the series is checked against physical bounds after conversion.

**Time labelling.** Two conventions compose here and are easy to confuse. ERA5 labels an
accumulated value by the *end* of the hour it covers, whereas the model indexes an hour by
its *beginning*; and ERA5 is published in UTC whereas the demand profiles are built in
local clock time. The net shift is therefore the UTC offset minus one hour, which for West
Africa Time happens to be zero -- a coincidence worth stating explicitly, since applying
either correction alone silently displaces generation relative to consumption by an hour,
and storage sizing is precisely what that error corrupts. The convention is verified
against the computed solar noon by :func:`check_solar_alignment`.
"""
from __future__ import annotations

import argparse
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import IRRADIANCE_DIR
from ..sites import Site, get_site

#: ERA5-Land variables requested for one site.
ERA5_VARIABLES = (
    "surface_solar_radiation_downwards",   # ssrd, accumulated J/m2
    "2m_temperature",                      # t2m, K
    "10m_u_component_of_wind",             # u10, m/s
    "10m_v_component_of_wind",             # v10, m/s
)

#: Standard time offset of the study area (West Africa Time, no daylight saving).
LOCAL_UTC_OFFSET_HOURS = 1
#: ERA5 labels an accumulated value by the end of the hour it covers; the model indexes an
#: hour by its beginning, so one hour is subtracted when relabelling.
ERA5_LABELS_INTERVAL_END = True

#: Columns of the produced series, in order.
OUTPUT_COLUMNS = ("timestamp", "irradiance_w_m2", "temperature_c", "wind_speed_m_s", "year")


@dataclass(frozen=True)
class Era5Request:
    """One ERA5-Land time-series request for a single point."""

    latitude: float
    longitude: float
    first_year: int
    last_year: int

    @property
    def date_range(self) -> str:
        return f"{self.first_year}-01-01/{self.last_year}-12-31"

    def payload(self) -> dict:
        return {
            "variable": list(ERA5_VARIABLES),
            "location": {"latitude": self.latitude, "longitude": self.longitude},
            "date": [self.date_range],
            "data_format": "netcdf",
        }


#: Physical bounds a converted irradiance series must satisfy. They are wide enough to
#: accept any tropical site and narrow enough to catch a mis-converted accumulation, which
#: is the failure mode that produces a plausible-looking but wrong series.
MAX_PLAUSIBLE_FLUX_W_M2 = (700.0, 1400.0)
MEAN_DAILY_IRRADIATION_KWH_M2 = (2.5, 8.0)


def check_irradiance(flux_w_m2: np.ndarray, times: pd.DatetimeIndex) -> None:
    """Raise if a converted irradiance series is not physically plausible."""
    flux = np.asarray(flux_w_m2, dtype=float)
    peak = float(flux.max())
    daily = pd.Series(flux, index=times).groupby(times.date).sum() / 1000.0
    mean_daily = float(daily.mean())

    lo, hi = MAX_PLAUSIBLE_FLUX_W_M2
    if not lo <= peak <= hi:
        raise ValueError(
            f"peak irradiance {peak:.0f} W/m2 outside [{lo:.0f}, {hi:.0f}]: the "
            "accumulation was probably converted with the wrong convention"
        )
    lo, hi = MEAN_DAILY_IRRADIATION_KWH_M2
    if not lo <= mean_daily <= hi:
        raise ValueError(
            f"mean daily irradiation {mean_daily:.2f} kWh/m2 outside [{lo}, {hi}]: the "
            "accumulation was probably converted with the wrong convention"
        )


def deaccumulate(values: np.ndarray, times: pd.DatetimeIndex) -> np.ndarray:
    """Hourly mean flux [W/m2] from an accumulation that resets each UTC day.

    Applies to the gridded ERA5-Land product. The time-series product used by
    :func:`download_era5` does *not* need it: see :func:`process_era5`.
    """
    values = np.asarray(values, dtype=float)
    if values.shape[0] != len(times):
        raise ValueError(f"{values.shape[0]} values for {len(times)} timestamps")

    increments = np.diff(values, prepend=0.0)
    new_day = np.empty(len(times), dtype=bool)
    new_day[0] = True
    new_day[1:] = times.date[1:] != times.date[:-1]
    increments[new_day] = values[new_day]
    return np.clip(increments, 0.0, None) / 3600.0


def check_solar_alignment(
    flux_w_m2: np.ndarray,
    times_local: pd.DatetimeIndex,
    longitude: float,
    utc_offset_hours: int,
    tolerance_h: float = 0.5,
) -> float:
    """Verify that the relabelled series peaks where the sun actually is.

    The irradiance-weighted centre of the day must fall at local solar noon, which follows
    from the site's longitude and the zone's offset. Returns the discrepancy in hours and
    raises when it exceeds ``tolerance_h``: an off-by-one in either time convention shows
    up here as a one-hour error, and nowhere else.
    """
    weights = pd.Series(np.asarray(flux_w_m2, dtype=float), index=times_local)
    hourly = weights.groupby(times_local.hour).mean()
    centre = float((hourly.index.to_numpy() * hourly.to_numpy()).sum() / hourly.to_numpy().sum())
    centre += 0.5                                   # bin label -> bin centre
    solar_noon = 12.0 - longitude / 15.0 + utc_offset_hours
    discrepancy = centre - solar_noon
    if abs(discrepancy) > tolerance_h:
        raise ValueError(
            f"irradiance centred at {centre:.2f} h local but solar noon is at "
            f"{solar_noon:.2f} h ({discrepancy:+.2f} h): the time convention is wrong"
        )
    return discrepancy


def process_era5(
    dataset,
    utc_offset_hours: int = LOCAL_UTC_OFFSET_HOURS,
    longitude: float | None = None,
) -> pd.DataFrame:
    """Turn a downloaded ERA5-Land time series into the hourly series, in local time.

    ``ssrd`` is divided by 3600 without differencing: this product accumulates over each
    hour, not since the start of the day. The conversion is verified against physical
    bounds by :func:`check_irradiance` before the frame is returned.
    """
    times_utc = pd.DatetimeIndex(pd.to_datetime(np.asarray(dataset["valid_time"].values)))

    ghi = np.clip(np.asarray(dataset["ssrd"].values).ravel(), 0.0, None) / 3600.0
    check_irradiance(ghi, times_utc)
    temperature_c = np.asarray(dataset["t2m"].values).ravel() - 273.15
    wind = np.hypot(np.asarray(dataset["u10"].values).ravel(),
                    np.asarray(dataset["v10"].values).ravel())

    # UTC -> local, and end-of-interval label -> beginning-of-interval label.
    net_shift = utc_offset_hours - (1 if ERA5_LABELS_INTERVAL_END else 0)
    times_local = times_utc + pd.Timedelta(hours=net_shift)
    if longitude is not None:
        check_solar_alignment(ghi, times_local, longitude, utc_offset_hours)
    frame = pd.DataFrame({
        "timestamp": times_local,
        "irradiance_w_m2": ghi,
        "temperature_c": temperature_c,
        "wind_speed_m_s": wind,
    })
    frame["year"] = frame["timestamp"].dt.year
    return frame[list(OUTPUT_COLUMNS)].reset_index(drop=True)


def open_era5(raw_path: Path):
    """Open a Climate Data Store download as a single dataset.

    The time-series endpoint returns a ZIP holding one NetCDF per variable group --
    radiation, temperature, wind -- despite the ``.nc`` request format, so the members are
    extracted and merged on their shared time coordinate. A plain NetCDF is opened as it
    is, which keeps the function usable with other products.
    """
    import xarray as xr

    if not zipfile.is_zipfile(raw_path):
        return xr.open_dataset(raw_path).load()

    with zipfile.ZipFile(raw_path) as archive:
        members = [n for n in archive.namelist() if n.endswith(".nc")]
        if not members:
            raise ValueError(f"{raw_path.name} holds no NetCDF member")
        with tempfile.TemporaryDirectory() as tmp:
            archive.extractall(tmp, members=members)
            parts = [xr.open_dataset(Path(tmp) / name).load() for name in members]
            merged = xr.merge(parts, compat="override", join="exact")
            for part in parts:
                part.close()
    return merged


def series_filename(site: Site, first_year: int, last_year: int) -> str:
    """Canonical name of a site's meteorological series."""
    return f"{site.name.lower()}_weather_hourly_{first_year}_{last_year}.csv"


def download_era5(
    site: Site,
    first_year: int,
    last_year: int,
    raw_dir: Path | None = None,
    out_dir: Path = IRRADIANCE_DIR,
    overwrite: bool = False,
) -> Path:
    """Download, process and write the site's hourly meteorological series.

    The raw NetCDF is cached, so re-running after an interrupted processing step does not
    queue a second request against the Climate Data Store.
    """
    if site.latitude is None or site.longitude is None:
        raise ValueError(
            f"{site.name} has no coordinates in the site registry; record them before "
            "requesting its meteorological series."
        )

    raw_dir = (IRRADIANCE_DIR / "raw") if raw_dir is None else raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"era5_land_{site.name.lower()}_{first_year}_{last_year}.nc"

    if overwrite or not raw_path.exists():
        import cdsapi

        request = Era5Request(site.latitude, site.longitude, first_year, last_year)
        print(f"--> ERA5-Land {site.name} ({site.latitude}, {site.longitude}) "
              f"{request.date_range}")
        client = cdsapi.Client()
        client.retrieve("reanalysis-era5-land-timeseries",
                        request.payload()).download(str(raw_path))
    else:
        print(f"--> cache: {raw_path.name}")

    frame = process_era5(open_era5(raw_path), longitude=site.longitude)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / series_filename(site, first_year, last_year)
    frame.to_csv(out_path, index=False)
    print(f"--> {out_path} ({len(frame):,} heures)")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Gbowele")
    parser.add_argument("--first-year", type=int, default=2016)
    parser.add_argument("--last-year", type=int, default=2025)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    path = download_era5(get_site(args.site), args.first_year, args.last_year,
                         overwrite=args.overwrite)
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    print("\nRésumé :")
    print(f"  période        : {frame['timestamp'].min()} -> {frame['timestamp'].max()}")
    print(f"  irradiance     : max {frame['irradiance_w_m2'].max():.0f} W/m2, "
          f"cumul {frame['irradiance_w_m2'].sum() / 1000 / (args.last_year - args.first_year + 1):.0f} kWh/m2/an")
    print(f"  température    : {frame['temperature_c'].min():.1f} - "
          f"{frame['temperature_c'].max():.1f} °C")
    print(f"  vent           : moyenne {frame['wind_speed_m_s'].mean():.2f} m/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
