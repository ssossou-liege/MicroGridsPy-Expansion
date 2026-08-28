"""The communities the model sizes, however they were described.

Two are written here, and they are templates rather than the tool's subject matter: they
carry the meter records the archetypes were calibrated on, and they let someone open the
tool and see a complete example before describing anything of their own. Every other site
comes from the user, as a file under ``sites/``, and passes through exactly the same
pipeline — a locality with no meter record of its own is simulated from its census and the
age of its connection, which is the situation of every site the tool exists to size.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import DEMAND_DIR, IRRADIANCE_DIR, USER_SITES_DIR, require

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
    #: Productive users expected in the community. Households alone understate a village
    #: whose mill and welder arrive with the connection, and those are the loads that
    #: decide whether the plant is daytime-heavy or evening-heavy.
    productive_units: int | None = None
    #: ``"template"`` for the two shipped with the tool, ``"user"`` for a described one.
    origin: str = "template"
    #: Standard time offset from UTC [h]. A property of the site, not of the acquisition:
    #: an hour's displacement between generation and consumption is precisely the error a
    #: storage sizing is most sensitive to, and it would pass unnoticed.
    utc_offset_hours: int = 1

    @property
    def n_households(self) -> int:
        """Total number of households in the community."""
        return sum(self.census.values())

    def irradiance_path(self) -> Path:
        """Path to the site's irradiance series, checked for existence."""
        if self.irradiance_file is None:
            raise FileNotFoundError(
                f"aucune série météorologique n'est enregistrée pour {self.name}. "
                "Obtenez-la depuis la carte, bouton « Obtenir la série météorologique », "
                "ou en ligne de commande avec data/irradiance/download.py. Elle se "
                "télécharge une fois par site et demande une connexion."
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

#: The two shipped as worked examples. Not the tool's subject matter -- see the module note.
TEMPLATES: dict[str, Site] = {site.name: site for site in (SAMIONTA, GBOWELE)}
SITES = TEMPLATES                                   # kept for callers that predate the store


def _slug(name: str) -> str:
    keep = [c if c.isalnum() or c in " -_" else "" for c in name]
    return ("".join(keep).strip().replace(" ", "-").lower()) or "site"


def to_record(site: Site) -> dict:
    """A site as the plain mapping the store holds and the interface edits."""
    return {"name": site.name, "census": dict(site.census),
            "latitude": site.latitude, "longitude": site.longitude,
            "irradiance_file": site.irradiance_file, "meter_file": site.meter_file,
            "productive_units": site.productive_units,
            "utc_offset_hours": site.utc_offset_hours, "origin": site.origin}


def from_record(record: dict) -> Site:
    census = {k: int(v) for k, v in (record.get("census") or {}).items() if int(v) >= 0}
    return Site(name=record["name"], census=census or {"HH1": 0},
                latitude=record.get("latitude"), longitude=record.get("longitude"),
                irradiance_file=record.get("irradiance_file"),
                meter_file=record.get("meter_file"),
                productive_units=record.get("productive_units"),
                utc_offset_hours=int(record.get("utc_offset_hours", 1)),
                origin=record.get("origin", "user"))


def save_site(site: Site) -> Path:
    """Write a described site to the store, where the next run will find it."""
    import json

    USER_SITES_DIR.mkdir(parents=True, exist_ok=True)
    path = USER_SITES_DIR / f"{_slug(site.name)}.json"
    record = to_record(site)
    record["origin"] = "user"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def delete_site(name: str) -> bool:
    path = USER_SITES_DIR / f"{_slug(name)}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def user_sites() -> dict[str, Site]:
    """Every site the user has described, keyed by name."""
    import json

    if not USER_SITES_DIR.exists():
        return {}
    out: dict[str, Site] = {}
    for path in sorted(USER_SITES_DIR.glob("*.json")):
        try:
            site = from_record(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            continue                # one malformed file must not hide the others
        out[site.name] = site
    return out


def known_sites() -> dict[str, Site]:
    """Templates and described sites together, the user's own taking precedence."""
    return {**TEMPLATES, **user_sites()}


def get_site(name: str) -> Site:
    """Return the site called ``name``, described or shipped."""
    sites = known_sites()
    try:
        return sites[name]
    except KeyError:
        raise KeyError(
            f"unknown site {name!r}; known sites are {sorted(sites)}"
        ) from None
