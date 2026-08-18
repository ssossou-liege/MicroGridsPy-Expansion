"""Declarative description of the sites the model is built for.

Every layer resolves a site through this registry rather than hard-coding census
counts, file names or coordinates, so that adding a locality is a matter of adding one
entry and running the same pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import DEMAND_DIR, IRRADIANCE_DIR, require

#: Socio-economic household categories used by the customer roster and the mixture model.
HOUSEHOLD_TYPES = ("HH1", "HH2", "HH3")


@dataclass(frozen=True)
class Site:
    """One community served by a micro-grid.

    Attributes
    ----------
    name
        Identifier used in the calibration tables (``site_name`` column).
    census
        Number of households of each socio-economic category in the *whole* community,
        not only the instrumented sample. The demand generator scales to these counts.
    latitude, longitude
        Decimal degrees. ``None`` when not yet recorded; the resource layer needs them
        only for plane-of-array transposition, not for the specific yield from measured
        global horizontal irradiance.
    irradiance_file
        Name of the hourly irradiance series in ``data/irradiance/``, or ``None`` when
        the series has still to be produced for this site.
    """

    name: str
    census: dict[str, int]
    latitude: float | None = None
    longitude: float | None = None
    irradiance_file: str | None = None
    meter_file: str | None = None

    @property
    def n_households(self) -> int:
        """Total number of households in the community."""
        return sum(self.census.values())

    def irradiance_path(self) -> Path:
        """Path to the site's irradiance series, checked for existence."""
        if self.irradiance_file is None:
            raise FileNotFoundError(
                f"no irradiance series is registered for {self.name}. Produce one with "
                "data/irradiance/download.py and record its file name in sites.py."
            )
        return require(IRRADIANCE_DIR / self.irradiance_file)

    def meter_path(self) -> Path:
        """Path to the site's meter readings, checked for existence."""
        if self.meter_file is None:
            raise FileNotFoundError(f"no meter readings are registered for {self.name}")
        return require(DEMAND_DIR / self.meter_file)


SAMIONTA = Site(
    name="Samionta",
    census={"HH1": 231, "HH2": 0, "HH3": 0},
    latitude=7.095474,
    longitude=2.244630,
    irradiance_file="samionta_weather_hourly_2016_2025.csv",
    meter_file="sam_meter_readings.parquet",
)

GBOWELE = Site(
    name="Gbowele",
    census={"HH1": 143, "HH2": 5, "HH3": 11},
    latitude=7.62,
    longitude=2.20,
    irradiance_file="gbowele_weather_hourly_2016_2025.csv",
    meter_file="gbo_meter_readings.parquet",
)

SITES: dict[str, Site] = {site.name: site for site in (SAMIONTA, GBOWELE)}


def get_site(name: str) -> Site:
    """Return the registered site called ``name``."""
    try:
        return SITES[name]
    except KeyError:
        raise KeyError(
            f"unknown site {name!r}; registered sites are {sorted(SITES)}"
        ) from None
