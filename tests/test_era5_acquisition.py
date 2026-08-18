"""Conventions of the ERA5-Land acquisition.

Both quantities converted here -- the radiation accumulation and the time label -- have two
plausible conventions, and choosing the wrong one produces a series that looks entirely
reasonable while displacing or distorting the daily energy. These tests pin the convention
that was verified against the site's computed solar noon, so that a future change of
product or endpoint fails loudly instead of silently corrupting the resource.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion.resource.era5 import (
    ERA5_LABELS_INTERVAL_END,
    LOCAL_UTC_OFFSET_HOURS,
    Era5Request,
    check_irradiance,
    check_solar_alignment,
    deaccumulate,
    process_era5,
    series_filename,
)
from microgrid_expansion.sites import SAMIONTA


def _synthetic_day(peak_w_m2: float = 900.0, days: int = 3) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """A clean sinusoidal daylight profile, centred on 12:00 of the index."""
    times = pd.date_range("2024-03-01", periods=24 * days, freq="h")
    hour = times.hour.to_numpy(dtype=float)
    flux = np.clip(peak_w_m2 * np.sin(np.pi * (hour - 6.0) / 12.0), 0.0, None)
    return flux, times


# ------------------------------------------------------------------ accumulation
def test_deaccumulate_recovers_a_constant_flux_and_resets_each_day():
    """For the gridded product, the hourly flux is the within-day first difference."""
    times = pd.date_range("2020-01-01", periods=48, freq="h")
    accumulation = np.concatenate([np.arange(24) * 3600.0 * 100.0] * 2)
    flux = deaccumulate(accumulation, times)
    assert flux[0] == 0.0 and flux[24] == 0.0          # reset at each day boundary
    assert np.allclose(flux[1:24], 100.0)
    assert (flux >= 0).all()


def test_deaccumulate_rejects_a_length_mismatch():
    with pytest.raises(ValueError, match="timestamps"):
        deaccumulate(np.zeros(5), pd.date_range("2020-01-01", periods=4, freq="h"))


# ----------------------------------------------------------------- physical guard
def test_physical_guard_accepts_a_plausible_series():
    flux, times = _synthetic_day()
    check_irradiance(flux, times)                       # must not raise


def test_physical_guard_catches_an_implausible_peak():
    flux, times = _synthetic_day()
    with pytest.raises(ValueError, match="peak irradiance"):
        check_irradiance(flux * 4.0, times)


def test_physical_guard_catches_an_implausible_daily_total():
    """A credible peak with too few sunlit hours must still be rejected."""
    times = pd.date_range("2024-03-01", periods=72, freq="h")
    flux = np.zeros(72)
    flux[times.hour == 12] = 900.0                      # one sunlit hour per day
    with pytest.raises(ValueError, match="daily irradiation"):
        check_irradiance(flux, times)


# -------------------------------------------------------------------- time labels
def test_solar_alignment_accepts_the_verified_convention():
    """Radiation centred on local solar noon is what the convention must produce."""
    flux, times = _synthetic_day()
    discrepancy = check_solar_alignment(flux, times, longitude=SAMIONTA.longitude,
                                        utc_offset_hours=LOCAL_UTC_OFFSET_HOURS)
    assert abs(discrepancy) < 0.5


def test_solar_alignment_catches_an_off_by_one_hour():
    """Applying only one of the two time corrections shifts the day by an hour."""
    flux, times = _synthetic_day()
    with pytest.raises(ValueError, match="time convention"):
        check_solar_alignment(flux, times + pd.Timedelta(hours=2),
                              longitude=SAMIONTA.longitude,
                              utc_offset_hours=LOCAL_UTC_OFFSET_HOURS)


def test_net_shift_composes_both_time_conventions():
    """ERA5 labels the interval end, so the net shift is the offset minus one hour."""
    assert ERA5_LABELS_INTERVAL_END is True
    net = LOCAL_UTC_OFFSET_HOURS - (1 if ERA5_LABELS_INTERVAL_END else 0)
    assert net == 0                                     # West Africa Time: they cancel


# ------------------------------------------------------------------------ request
def test_request_payload_targets_the_site_and_period():
    request = Era5Request(latitude=7.1, longitude=2.2, first_year=2020, last_year=2021)
    payload = request.payload()
    assert payload["location"] == {"latitude": 7.1, "longitude": 2.2}
    assert payload["date"] == ["2020-01-01/2021-12-31"]
    assert "surface_solar_radiation_downwards" in payload["variable"]
    assert "2m_temperature" in payload["variable"]


def test_series_filename_is_site_specific():
    name = series_filename(SAMIONTA, 2016, 2025)
    assert name == "samionta_weather_hourly_2016_2025.csv"


# ------------------------------------------------------------------ end to end
def test_process_era5_produces_the_expected_columns():
    """A minimal in-memory dataset must round-trip through the processing step."""
    xr = pytest.importorskip("xarray")

    times = pd.date_range("2024-03-01", periods=48, freq="h")
    hour = times.hour.to_numpy(dtype=float)
    flux = np.clip(900.0 * np.sin(np.pi * (hour - 6.0) / 12.0), 0.0, None)
    dataset = xr.Dataset(
        {
            "ssrd": ("valid_time", flux * 3600.0),
            "t2m": ("valid_time", np.full(48, 300.0)),
            "u10": ("valid_time", np.full(48, 3.0)),
            "v10": ("valid_time", np.full(48, 4.0)),
        },
        coords={"valid_time": times},
    )
    frame = process_era5(dataset)
    assert list(frame.columns) == ["timestamp", "irradiance_w_m2", "temperature_c",
                                   "wind_speed_m_s", "year"]
    assert frame["temperature_c"].iloc[0] == pytest.approx(26.85)     # 300 K
    assert frame["wind_speed_m_s"].iloc[0] == pytest.approx(5.0)      # hypot(3, 4)
    assert frame["irradiance_w_m2"].max() == pytest.approx(900.0, rel=1e-6)
