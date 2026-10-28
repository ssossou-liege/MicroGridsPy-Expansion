"""The communities the model sizes, however they were described.

Two are written here, and they are templates rather than the tool's subject matter: they
carry the meter records the archetypes were calibrated on, and they let someone open the
tool and see a complete example before describing anything of their own. Every other site
comes from the user, as a file under ``sites/``, and passes through exactly the same
pipeline — a locality with no meter record of its own is simulated from its census and the
age of its connection, which is the situation of every site the tool exists to size.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from .paths import DEMAND_DIR, IRRADIANCE_DIR, USER_SITES_DIR, require

#: Socio-economic household categories used by the customer roster and the mixture model.
HOUSEHOLD_TYPES = ("HH1", "HH2", "HH3")


def standard_offset(longitude: float | None) -> int:
    """The time zone a site at this longitude most likely keeps [h from UTC].

    Solar noon follows longitude at fifteen degrees an hour, and a country's legal zone is
    usually the nearest whole hour to it. Not always: several keep a zone an hour or more
    from their sun, and where that is so the offset has to be corrected by hand. It is
    derived rather than asked because an hour's displacement between generation and
    consumption is the error a storage sizing is most sensitive to, and a developer typing
    it from memory is how that error gets in. ``None`` longitude keeps the old default.
    """
    if longitude is None:
        return 1
    return int(round(float(longitude) / 15.0))


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
    #: How many of each activity class, when the developer has surveyed them rather than
    #: only counted them. A roster is better information than a total: two mills and a
    #: welder do not make the same day as three tailors. ``None`` falls back to the total
    #: above, and that in turn to the ratio measured at the reference villages.
    productive_mix: dict[str, int] | None = None
    #: How many of each community use the village has -- a school, a health centre, a place
    #: of worship. These are not households and not trades, and no calibration of ours
    #: covers them; they are declared or they are absent.
    community_mix: dict[str, int] | None = None
    #: What the plant serves and invoices to nobody: the street lighting, counted in lamps,
    #: and the plant's own supply. Kept apart from the community buildings because a school
    #: is a customer and these are not, and the difference decides the revenue rather than
    #: the plant.
    self_mix: dict[str, int] | None = None
    #: Uses the developer described because no class of ours fits them, each carrying the
    #: devices that make it up. Their counts live in the two mixes above, under the same
    #: key, so that a declared use is counted exactly as a calibrated one is.
    declared_uses: tuple | None = None
    #: The village whose series this one is using, when it borrowed rather than downloaded.
    #: Carried so that a certificate can say whose sun it rests on: a plant sized on a
    #: neighbour's weather is a fact about the result, not a detail of how it was obtained.
    irradiance_source: str | None = None
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
                f"no meteorological series is stored for {self.name}. "
                "Fetch it from the map, with the \"Fetch the meteorological series\" button, "
                "or from the command line with data/irradiance/download.py, which "
                "downloads once per site and needs a connection."
            )
        return require(IRRADIANCE_DIR / self.irradiance_file)

    def meter_path(self) -> Path:
        """Path to the site's meter readings, checked for existence."""
        if self.meter_file is None:
            raise FileNotFoundError(f"no meter readings are registered for {self.name}")
        return require(DEMAND_DIR / self.meter_file)


#: Both villages serve two loads nobody is invoiced for, and both are in the plant's record
#: rather than in anybody's bill. The air conditioning of the room the inverters stand in is
#: metered separately at each, so it is counted as the calibrated class and carries no
#: figure here. The street lighting is not metered anywhere, so it is given as the lamps
#: that light and their rating.
SAMIONTA = Site(
    name="Samionta",
    census={"HH1": 231, "HH2": 0, "HH3": 0},
    latitude=7.095474,
    longitude=2.244630,
    irradiance_file="samionta_weather_hourly_2016_2025.csv",
    meter_file="sam_meter_readings.parquet",
    self_mix={"powerhouse": 1, "public_lighting": 1},
)

GBOWELE = Site(
    name="Gbowele",
    census={"HH1": 143, "HH2": 5, "HH3": 11},
    latitude=7.62,
    longitude=2.20,
    irradiance_file="gbowele_weather_hourly_2016_2025.csv",
    meter_file="gbo_meter_readings.parquet",
    self_mix={"powerhouse": 1, "public_lighting": 1},
)

#: The street lighting of the villages that have a figure for it, as lamps alight and their
#: rating. Built on access rather than here: making a use needs the demand package, and that
#: package reads this module at import time for the census and the meter files, so calling
#: into it while this one is still being defined is a cycle. One village, for now.
#:
#: Gbowele carries six luminaires on photocells: one of 50 W, one of 65 W and four of 100 W.
#: The four went up on 25 August 2026, replacing 50 W fittings that had failed. Five hundred
#: and fifteen watts if every one of them lit; about four hundred do, and that is the state
#: carried here because it is the state the plant now serves.
#:
#: Two distribution meters stand in series at the head of the network and record everything
#: sent into it, so the difference between what they read and what the customers' meters read
#: is the lighting, the losses and the meters' own supply. The two agree with each other to a
#: few watts throughout, which is what makes the reading trustworthy.
#:
#: The installation shows as a step on the date the operator gives, and the two meters put it
#: at the same size. Over the twenty-four nights of August before it, what switches at dusk
#: reads 103 W; over the six after, 296 W. A step of 193 W, and the night level alone rises
#: from 404 to 554 W. Before the step the lighting had been flat for twenty-two months:
#: November 2024 to August 2026 reads 188, 196, 204, 196, 176, 184, 204, 200, 204, 200, 196,
#: 164, 144, 196, 118, 200, 152, 132, 150, 144, 140, 124 W. The decline across that list is
#: not lamps dying but this estimator losing its footing: what does not switch grows from
#: 40 W to about 290 W over the same months, as the customers' night load trebles, and the
#: night and midday baselines it differences drift apart with it. Read where the baseline was
#: small, the lighting was 195 W.
#:
#: So 195 W before the step and about 390 after, which is the four new fittings alight and
#: the two old ones dark, or near enough; and 390 W is an upper bound besides, the lighting
#: current incurring a loss of its own on the way. The first three months of the record stand
#: higher still -- 788, 512, 134 W -- and that is the village being connected and the
#: metering catching up, not lamps.
#:
#: What does *not* switch grows steadily, from 40 W in November 2024 to about 290 W in August
#: 2026, while the customers' night load roughly trebles. That is the network loss and the
#: meters' own supply together, and it is the only sight this project has of a loss that
#: grows with the load.
#:
#: Reading a photocell village the way a clock village is read invites a bias, and the check
#: is that Samionta answers it. Its clock cannot vary, and yet the same night-by-night
#: estimator finds a standard deviation of 0.55 h on its switch-on and 0.86 h on its
#: switch-off, against 0.60 and 1.05 here. Almost all of what looks like a photocell
#: wandering is the estimator's own noise, and what a photocell really adds over a clock is
#: of the same order. The power is immune to it either way: the deep-night and midday windows
#: the 195 W is read from sit hours away from any switching time under either mechanism.
#: Samionta: eight floodlights of 65 W, which is the luminaire's nameplate and not an
#: inference. Two measurements agree with it and were made before it was known. This plant
#: has no distribution meter, so its own telemetry answers instead: over seventeen months,
#: the load it served less what the customers' meters recorded less what the plant room's
#: meter recorded leaves a residual flat at about 770 W from one in the morning to six, and
#: near zero at midday. Comparing hours of equal customer throughput with the lamps on and
#: off puts what switches at dusk at 585 W, give or take 189 at ninety-five per cent; an
#: earlier estimate from the loss study, made before the plant room had a meter of its own,
#: gave 521 W give or take 91, against the 520 W eight of these draw.
#:
#: Read as medians by quarter of an hour the same residual sits at 915 W all night and 270 W
#: through the middle of the day, so 645 W switch. What the plant produces above the 520 W
#: of nameplate is left where it belongs rather than folded into the rating: these
#: luminaires carry no photocell, run off a clock, sit at the end of the network and have a
#: power factor above nine tenths but not one, so a loss on the lighting circuit is part of
#: it -- and the rest is the instrument, this village being the one where a telemetry
#: sampled every five minutes is differenced against meters that integrate every fifteen,
#: which already showed its hand by returning a negative apparent network loss. Gbowele,
#: measured meter against meter, shows no such excess at all. Ten lamps would fit the 645 W
#: as well as eight plus a loss; the operator confirms eight.
#:
#: The clock is set, the operator says, to somewhere between half past six and seven in the
#: evening and between half past six and seven in the morning. The residual picks the late
#: end of both: full plateau by half past seven in the evening, half of it by a quarter past
#: seven in the morning.
#: Lamps alight, their rating, when they switch, and where those come from.
_TEMPLATE_LIGHTING: dict[str, tuple[int, float, int, int, str]] = {
    "Samionta": (8, 65.0, 19 * 60, 7 * 60,
                 "eight 65 W floodlights on a clock, from the data sheet and the "
                 "plant's own load balance"),
    "Gbowele": (4, 100.0, 19 * 60 + 15, 7 * 60,
                "the four 100 W fittings put up on 25 August 2026, from the step the "
                "two series distribution meters both record on that date"),
}


@lru_cache(maxsize=1)
def _template_uses() -> dict[str, tuple]:
    """The templates' declared uses, built once, after the demand package can be imported."""
    from .demand.uses import dusk_to_dawn

    return {name: (dusk_to_dawn(lamps, watts, source=source,
                                start_min=start, end_min=end),)
            for name, (lamps, watts, start, end, source) in _TEMPLATE_LIGHTING.items()}

#: The two shipped as worked examples. Not the tool's subject matter -- see the module note.
TEMPLATES: dict[str, Site] = {site.name: site for site in (SAMIONTA, GBOWELE)}
SITES = TEMPLATES                                   # kept for callers that predate the store


def _slug(name: str) -> str:
    keep = [c if c.isalnum() or c in " -_" else "" for c in name]
    return ("".join(keep).strip().replace(" ", "-").lower()) or "site"


def _uses_from(records) -> tuple | None:
    """Rebuild declared uses from a stored record, dropping any that no longer parse."""
    if not records:
        return None
    from .demand.uses import UseSpec
    out = []
    for record in records:
        try:
            out.append(UseSpec.from_record(record))
        except (KeyError, TypeError, ValueError):
            continue          # a use written by an older version is skipped, not fatal
    return tuple(out) or None


def to_record(site: Site) -> dict:
    """A site as the plain mapping the store holds and the interface edits."""
    return {"name": site.name, "census": dict(site.census),
            "latitude": site.latitude, "longitude": site.longitude,
            "irradiance_file": site.irradiance_file, "meter_file": site.meter_file,
            "irradiance_source": site.irradiance_source,
            "productive_units": site.productive_units,
            "productive_mix": site.productive_mix,
            "community_mix": site.community_mix,
            "self_mix": site.self_mix,
            "declared_uses": ([u.to_record() for u in site.declared_uses]
                              if site.declared_uses else None),
            "utc_offset_hours": site.utc_offset_hours, "origin": site.origin}


#: Uses that were written under another category before self consumption existed, with the
#: category they belong to. Street lighting is the whole of it: it was listed among the
#: community buildings because that is where a developer looks for it, and it is not one --
#: nobody is billed for it. A site saved then is read as what it describes rather than
#: rewritten on disk, so an old store stays readable by an old checkout.
_MOVED_TO_SELF = {"public_lighting": {"category": "self_consumption",
                                      "billable": False, "on_network": True}}


def _migrate_self_consumption(community: dict | None, own: dict | None,
                              records) -> tuple[dict | None, dict | None, list]:
    """Move a use that has changed category, and its count, out of the community list."""
    community = dict(community or {})
    own = dict(own or {})
    moved = []
    for raw in list(records or ()):
        key = raw.get("key")
        if key not in _MOVED_TO_SELF or raw.get("category") == "self_consumption":
            moved.append(raw)
            continue
        moved.append({**raw, **_MOVED_TO_SELF[key]})
        if key in community:
            own.setdefault(key, community.pop(key))
    return community or None, own or None, moved


def from_record(record: dict) -> Site:
    census = {k: int(v) for k, v in (record.get("census") or {}).items() if int(v) >= 0}
    community, own, uses = _migrate_self_consumption(
        record.get("community_mix"), record.get("self_mix"),
        record.get("declared_uses"))
    return Site(name=record["name"], census=census or {"HH1": 0},
                latitude=record.get("latitude"), longitude=record.get("longitude"),
                irradiance_file=record.get("irradiance_file"),
                irradiance_source=record.get("irradiance_source"),
                meter_file=record.get("meter_file"),
                productive_units=record.get("productive_units"),
                productive_mix=record.get("productive_mix"),
                community_mix=community,
                self_mix=own,
                declared_uses=_uses_from(uses),
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
    shipped = {name: (replace(site, declared_uses=_template_uses()[name])
                      if name in _template_uses() else site)
               for name, site in TEMPLATES.items()}
    return {**shipped, **user_sites()}


def get_site(name: str) -> Site:
    """Return the site called ``name``, described or shipped."""
    sites = known_sites()
    try:
        return sites[name]
    except KeyError:
        raise KeyError(
            f"unknown site {name!r}; known sites are {sorted(sites)}"
        ) from None
