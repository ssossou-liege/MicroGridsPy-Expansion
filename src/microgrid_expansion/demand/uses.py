"""Uses a community has that no calibration of ours has measured.

The demand this project builds rests on two measured populations: households, whose
behaviour is calibrated into four archetypes and simulated appliance by appliance, and
productive customers, whose six activity classes carry an hourly shape taken from meters.
Between them they cover what the two reference villages happen to contain.

They do not cover what a village elsewhere contains. A school, a health centre, a church
and the street lighting are loads a developer knows about before any meter is installed,
and none of them is a household or a trade. Nor do the six activity classes exhaust the
trades: a village with a cold store, a welding shop or an internet kiosk has a load none of
the six describes, and forcing it into the nearest class describes a different village.

This module lets such a use be declared rather than inferred. A use is a name and a list of
devices, each given in the terms RAMP is driven by -- what it draws, how many there are, how
long it runs, the shortest stretch it runs for, the window it runs in, and how often it is
used at all. Those are the same seven quantities the household calibration carries, so a
declared use goes through exactly the machinery a calibrated one does and inherits its
treatment of windows that cross midnight, of duties that fill their window, and of counts
that must be realised rather than rounded.

Nothing here carries a default drawn from thin air. A use the developer declares is one the
developer parameterises; the catalogue below names the four that come up everywhere and says
what is known about each, which for three of them is nothing numerical at all. A plant sized
on invented occupancy would be no better for being sized confidently.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

MINUTES_PER_DAY = 1440

#: The categories a use can belong to. Productive uses are trades, and scale with how far
#: the connection has advanced; community uses are the buildings a village already has, and
#: are connected from the start because they are what a line is usually run for.
CATEGORIES = ("productive", "community")


@dataclass(frozen=True)
class Device:
    """One device inside a use, in the terms RAMP is driven by.

    ``power_w`` is what it draws when running, ``number`` how many of it there are, and
    ``func_time_min`` how many minutes a day it actually runs -- not how long it is
    switched on at the wall. ``func_cycle_min`` is the shortest stretch it runs for once
    started, which is what stops a fridge being simulated as a thousand one-minute bursts.
    The window is the part of the day it may run in, counted in minutes from midnight, and
    may cross midnight by giving an end below its start. ``occasional_use`` is the chance it
    is used on a given day at all, which is how a welding set that works three days a week
    differs from a lamp that burns every night.
    """

    name: str
    power_w: float
    number: float = 1.0
    func_time_min: float = 0.0
    func_cycle_min: float = 1.0
    window_start_min: int = 0
    window_end_min: int = MINUTES_PER_DAY
    occasional_use: float = 1.0

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("a device needs a name")
        if not (self.power_w > 0):
            raise ValueError(f"{self.name}: power must be above zero")
        if not (self.func_time_min > 0):
            raise ValueError(f"{self.name}: running time must be above zero")
        if self.number < 0:
            raise ValueError(f"{self.name}: a count cannot be negative")
        if not (0.0 <= self.occasional_use <= 1.0):
            raise ValueError(f"{self.name}: occasional use is a probability")
        for bound in (self.window_start_min, self.window_end_min):
            if not (0 <= bound <= MINUTES_PER_DAY):
                raise ValueError(f"{self.name}: a window lies within the day")
        if self.func_time_min > self.window_width_min:
            raise ValueError(
                f"{self.name}: it cannot run {self.func_time_min:.0f} minutes a day inside "
                f"a window {self.window_width_min:.0f} minutes wide")

    @property
    def window_width_min(self) -> float:
        """Minutes the window spans, counting one that crosses midnight."""
        if self.window_end_min > self.window_start_min:
            return float(self.window_end_min - self.window_start_min)
        return float(MINUTES_PER_DAY - self.window_start_min + self.window_end_min)

    @property
    def is_constant(self) -> bool:
        """Whether the device simply runs its window, every day, without variation.

        Street lighting is the case that matters: it switches on at dusk and off at dawn
        and has no behaviour to speak of. Such a device is placed exactly rather than drawn,
        because a draw of something certain only loses energy.
        """
        return (self.occasional_use >= 1.0
                and self.func_time_min >= self.window_width_min - 1e-9)

    @property
    def daily_kwh(self) -> float:
        """What one use of this kind draws in a day, if every device runs its full time."""
        return (self.power_w * self.number * self.func_time_min) / (1000.0 * 60.0)

    def as_row(self) -> dict:
        """The seven quantities under the names the calibration tables use.

        Returned in the calibration's own vocabulary so that a declared device and a
        measured one reach the simulator by the same path, rather than through a second
        translation that could drift from the first.
        """
        end = self.window_end_min
        if end <= self.window_start_min:
            end = end + MINUTES_PER_DAY        # the caller unwraps it as it does for meters
        return {"power": float(self.power_w), "number": float(self.number),
                "func_time": float(self.func_time_min),
                "func_cycle": float(self.func_cycle_min),
                "w1_start": int(self.window_start_min), "w1_end": int(end),
                "occasional_use": float(self.occasional_use)}


@dataclass(frozen=True)
class UseSpec:
    """A use a community has, and the devices that make it up."""

    key: str
    label: str
    category: str = "community"
    devices: tuple[Device, ...] = ()
    #: Where the numbers come from. A use carrying none is one nobody has measured, and the
    #: interface says so rather than letting its figures pass for sourced.
    source: str = ""

    def validate(self) -> None:
        if not self.key.strip():
            raise ValueError("a use needs a key")
        if self.category not in CATEGORIES:
            raise ValueError(f"{self.key}: unknown category {self.category!r}")
        if not self.devices:
            raise ValueError(f"{self.key}: a use with no device draws nothing")
        for device in self.devices:
            device.validate()

    @property
    def daily_kwh(self) -> float:
        return sum(device.daily_kwh for device in self.devices)

    @property
    def peak_w(self) -> float:
        """Everything running at once, which is the worst a connection must admit."""
        return sum(device.power_w * device.number for device in self.devices)

    def to_record(self) -> dict:
        record = asdict(self)
        record["devices"] = [asdict(device) for device in self.devices]
        return record

    @classmethod
    def from_record(cls, record: dict) -> "UseSpec":
        devices = tuple(Device(**device) for device in record.get("devices", ()))
        return cls(key=record["key"], label=record.get("label", record["key"]),
                   category=record.get("category", "community"),
                   devices=devices, source=record.get("source", ""))


@dataclass(frozen=True)
class CommunityCalibration:
    """The community classes the meters could speak to, in the shape the generator wants.

    Presented with the same ``profiles`` attribute the productive calibration carries, so
    that a measured community class reaches the month through the function that already
    draws the productive ones and inherits its day-to-day spread rather than repeating a
    mean day, which would flatten the evenings this class is almost entirely made of.
    """

    profiles: "object"

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(self.profiles.index)

    @classmethod
    def load(cls) -> "CommunityCalibration | None":
        """The calibrated classes, or ``None`` when the table has not been built."""
        import pandas as pd

        from ..paths import REFERENCE_DIR

        path = REFERENCE_DIR / "community_class_profiles.csv"
        if not path.exists():
            return None
        profiles = pd.read_csv(path, index_col="community_class")
        profiles.columns = [int(c) if str(c).isdigit() else c for c in profiles.columns]
        return cls(profiles=profiles)


def dusk_to_dawn(lamps: int, watts: float, *, source: str,
                 start_min: int = 18 * 60 + 30,
                 end_min: int = 6 * 60) -> UseSpec:
    """Street lighting, which is the one community use that needs no occupancy to model.

    It runs from dusk to dawn every night of the year, so its energy follows from a lamp
    count and a rating and nothing else. That makes it the only one of the four this
    catalogue can carry a number for.
    """
    width = MINUTES_PER_DAY - start_min + end_min
    return UseSpec(
        key="public_lighting", label="Public lighting", category="community",
        source=source,
        devices=(Device(name="street lamp", power_w=watts, number=float(lamps),
                        func_time_min=float(width), func_cycle_min=float(width),
                        window_start_min=start_min, window_end_min=end_min),))


#: The four community uses that come up in every village, and what is known about each.
#:
#: Only street lighting carries numbers, and they are the ones reported for the Samionta
#: plant rather than a figure chosen to look plausible. The school, the health centre and
#: the place of worship are named and left empty on purpose: their load depends on what
#: equipment they hold and how many hours they keep, which varies more between two villages
#: than between a village and a town, and a default would be invention dressed as
#: calibration. The interface asks for them; it does not pretend to know them.
COMMUNITY_CATALOGUE: dict[str, dict] = {
    "school": {
        "label": "School",
        "known": False,
        "note": "Lighting, fans and whatever office equipment the school holds, during "
                "term and school hours only. Depends on the establishment; no calibration "
                "of ours covers it.",
    },
    "health_centre": {
        "label": "Health centre",
        "known": False,
        "note": "Lighting, refrigeration for the cold chain, and occasionally a steriliser. "
                "The cold chain runs around the clock and is usually the whole of the "
                "load; a centre without one is a different building electrically.",
    },
    "place_of_worship": {
        "label": "Place of worship",
        "known": False,
        "note": "Lighting and amplification, concentrated on service days and on evenings. "
                "Five are metered across the two reference villages, which is enough to "
                "calibrate a shape and not enough to have done so yet.",
    },
    "public_lighting": {
        "label": "Public lighting",
        "known": True,
        "note": "Street lamps burning dusk to dawn. Not a customer and usually unmetered: "
                "at Gbowele it falls inside what the distribution meters record, together "
                "with the network losses.",
    },
}


def community_catalogue(lamps: int | None = None, watts: float | None = None,
                        source: str = "") -> dict[str, UseSpec | None]:
    """The four community uses, those with numbers carrying them and the rest empty.

    ``None`` against a key means the use is known to exist and not known to any figure, and
    the caller must obtain it. Returning ``None`` rather than a plausible default is the
    whole point: a plant sized on invented occupancy is not improved by the confidence with
    which it was sized.
    """
    out: dict[str, UseSpec | None] = {key: None for key in COMMUNITY_CATALOGUE}
    if lamps and watts:
        out["public_lighting"] = dusk_to_dawn(lamps, watts, source=source)
    return out
