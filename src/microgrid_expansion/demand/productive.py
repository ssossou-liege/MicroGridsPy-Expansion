"""Productive uses: how many enterprises connect, and what each of them draws.

Households and productive users are not the same modelling problem. A community's
households are counted once, before the grid is built, and the question is how many of
them connect and how their consumption matures. Enterprises cannot be counted that way:
nobody knows in advance who will start a business, and the census taken before
construction says nothing about it. Their number is therefore carried as a *trajectory*
conditioned on the age of the connection, drawn stochastically, and bracketed by the same
envelope as household growth --- which is an honest statement of what two reference sites
support, and no more.

What each enterprise draws is taken from measurement rather than from an appliance model.
The survey conducted on these sites records activity, working hours and use windows
reliably, but forty-two per cent of its nameplate powers are entered as zero: mills,
incubators and refrigerators whose rating plate the surveyor could not read, the technical
label having been photographed sixteen times out of fifty. Building a bottom-up appliance
model on that would be building on the one field the survey does not support. The meter
records, by contrast, cover every connected enterprise. Activity class comes from the
survey; magnitude and shape come from the meters.

Classes matter because these users are extremely unequal: the five largest account for
sixty-one per cent of the energy the sampled enterprises consume, and their shapes differ
in kind rather than in degree. Milling, sewing and sawing are frankly diurnal, peaking in
the afternoon; refrigeration and egg incubation run around the clock; the many small
trading activities keep the evening profile of a household. A single average enterprise
would reproduce none of them, and would in particular erase the daytime load that decides
whether an array should be coupled on the direct or the alternating side.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR

#: Activity classes, in the order they are reported.
CLASSES = ("refrigeration", "milling", "incubation", "tailoring", "sawmill", "small_trade")

#: Enterprises the survey did not reach. They are not unclassified in the sense of being
#: unknown: they are the small trading activities the survey deliberately passed over in
#: favour of the large consumers, and their measured profile is reported as its own class
#: rather than folded into an average that would misdescribe both ends.
UNSURVEYED = "small_trade"

HOURS = tuple(range(24))

#: The customers of the reference villages' records at their own levels, whose recorded
#: peaks bound what a busy day of a unit of their class draws (``peak_ratios``).
OWN_LEVELS_FILE = "own_levels.csv"
#: The record's types whose units a class's ceiling is read from: productive users and
#: places of worship. Households have no class.
UNIT_TYPES = ("PUE", "CHU")


def peak_ratios(path=None) -> pd.DataFrame:
    """Each class's ceiling on a busy day, as a ratio to a unit's mean hourly power.

    For every metered unit of the class on the reference villages' records, a productive
    user or a place of worship with a level of its own, the ratio of the highest hourly
    power its meter recorded over its level's months to its mean hourly power; the class's
    ratio is the median over its units. One row per class: ``units``, ``codes`` and
    ``peak_ratio``. Empty where the table is absent.

    A unit of a class has no meter of its own to bound its busy days, and the plain
    scaling of its mean day gave the test bench's mills four times their mean hour on a busy
    day, 15 kW for the class where 7 before the class tables read Samionta's second mill as
    one. The median is what the class's own units recorded, the ones that run hardest and
    the ones that barely run alike.
    """
    path = REFERENCE_DIR / OWN_LEVELS_FILE if path is None else path
    if not path.exists():
        return pd.DataFrame(columns=["units", "codes", "peak_ratio"])
    levels = pd.read_csv(path, dtype={"shape": str})
    units = levels[levels.customer_type.isin(UNIT_TYPES)
                   & (levels.kwh_per_day > 0) & (levels.peak_kw > 0)]
    ratio = units.peak_kw * 24.0 / units.kwh_per_day
    table = units.assign(ratio=ratio).groupby("shape").agg(
        units=("customer_code", "size"), codes=("customer_code", " ".join),
        peak_ratio=("ratio", "median"))
    table.index.name = "class"
    return table


def with_ceilings(profiles: pd.DataFrame, path=None) -> pd.DataFrame:
    """A class table with each class's ``peak_ratio`` (``peak_ratios``), empty where its
    units recorded none."""
    profiles = profiles.copy()
    profiles["peak_ratio"] = peak_ratios(path).peak_ratio.reindex(profiles.index)
    return profiles


def classify(activity: str) -> str:
    """Map a declared economic activity to one of the modelled classes."""
    text = unicodedata.normalize("NFKD", str(activity).upper())
    text = "".join(c for c in text if not unicodedata.combining(c))
    if any(k in text for k in ("GLACE", "BOISSON", "JUS", "POISSONNERIE",
                               "CONGEL", "FRAICH")):
        return "refrigeration"
    if any(k in text for k in ("MOULIN", "MOUTURE")):
        return "milling"
    if any(k in text for k in ("COUVEUSE", "COUVAISON", "ECLOSION", "OEUF")):
        return "incubation"
    if any(k in text for k in ("COUTURE", "TAILLEUR")):
        return "tailoring"
    if "SCIERIE" in text:
        return "sawmill"
    return UNSURVEYED


@dataclass(frozen=True)
class ProductiveCalibration:
    """Everything the generator needs about productive users, read from the CSVs."""

    profiles: pd.DataFrame        # class x hour -> mean kW per connected unit
    mix: pd.DataFrame             # class x trajectory -> share of connections
    intensity: pd.DataFrame       # maturity band x trajectory -> units per census household

    @classmethod
    def load(cls) -> "ProductiveCalibration":
        d = REFERENCE_DIR
        profiles = pd.read_csv(d / "pue_class_profiles.csv", index_col="activity_class")
        # Hour columns arrive as strings; anything else — the day-to-day spread — keeps
        # its name.
        profiles.columns = [int(c) if str(c).isdigit() else c for c in profiles.columns]
        # The ceiling on a busy day of a unit of each class, from its metered units.
        profiles = with_ceilings(profiles)
        mix = pd.read_csv(d / "pue_class_mix.csv", index_col="activity_class")
        # The table is stored rounded; a multinomial draw needs probabilities that sum to
        # one exactly, and one part in a million the wrong way makes it refuse.
        mix = mix / mix.sum(axis=0)
        intensity = pd.read_csv(d / "pue_connection_intensity.csv",
                                index_col="maturity")
        return cls(profiles=profiles, mix=mix, intensity=intensity)


def sample_units(calibration: ProductiveCalibration, n_connected: int,
                 maturity_band: str, trajectory: str,
                 rng: np.random.Generator,
                 expected_units: int | None = None,
                 declared_mix: dict[str, int] | None = None) -> dict[str, int]:
    """Draw how many enterprises of each class are connected.

    ``n_connected`` counts the households already on the grid, not the community's census:
    enterprises appear alongside existing connections, and a ratio taken over dwellings
    that are not yet connected would not transfer to a site whose connection has advanced
    at another pace.

    The expected number follows the connection intensity measured at the reference sites
    for this maturity and trajectory; the realised number is a Poisson draw around it,
    business creation being a counting process rather than a fixed roster. Classes are
    then allocated multinomially from the observed mix.

    ``expected_units`` overrides that expectation with what the developer expects on this
    site, which is usually better information than a ratio transferred from two other
    villages: the mill and the welder decide whether the plant is daytime-heavy or
    evening-heavy, and someone who has surveyed the community knows how many are coming.
    It replaces the mean, not the draw -- the count stays uncertain because business
    creation is.

    ``declared_mix`` goes one step further: a developer who has surveyed the community
    knows not only how many enterprises to expect but which. Given it, neither the count
    nor the split is drawn -- a village that says it has two mills and one welder is
    answered with two mills and one welder, since a measured roster is not a distribution
    to sample from. The measured mix is still what fills the classes the survey left
    unstated, and it alone decides the shape of each one's day.
    """
    if declared_mix is not None:
        return {klass: int(max(declared_mix.get(klass, 0), 0))
                for klass in calibration.mix.index}

    band = maturity_band if maturity_band in calibration.intensity.index \
        else calibration.intensity.index[-1]
    column = trajectory if trajectory in calibration.intensity.columns else "central"
    expected = (float(expected_units) if expected_units is not None
                else float(calibration.intensity.loc[band, column]) * n_connected)
    total = int(rng.poisson(max(expected, 0.0)))
    if total == 0:
        return {c: 0 for c in calibration.mix.index}
    shares = calibration.mix[column if column in calibration.mix.columns else "central"]
    draw = rng.multinomial(total, shares.to_numpy())
    return dict(zip(calibration.mix.index, (int(n) for n in draw)))


def _class_day(calibration, klass: str) -> tuple[np.ndarray, float]:
    """A class's measured mean day [kW per hour] and the log-normal sigma of its days."""
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    shape = calibration.profiles.loc[klass, hours].to_numpy(dtype=float)
    spread = float(calibration.profiles.loc[klass].get("daily_cv", 0.0) or 0.0)
    return shape, float(np.sqrt(np.log1p(spread ** 2)))


def class_cap(calibration, klass: str, mean_day: np.ndarray) -> float | None:
    """The highest hourly power a unit of ``klass`` with mean day ``mean_day`` draws [kW].

    Its mean hourly power times the class's ``peak_ratio`` (``peak_ratios``); ``None`` for a
    class whose units recorded no peak, which keeps the plain scaling.
    """
    if "peak_ratio" not in calibration.profiles.columns:
        return None
    ratio = calibration.profiles.loc[klass, "peak_ratio"]
    if ratio is None or not np.isfinite(float(ratio)) or float(ratio) <= 0.0:
        return None
    cap = float(ratio) * float(np.sum(mean_day)) / 24.0
    return cap if cap > 0.0 else None


def monthly_profile_parts(counts: dict[str, int], calibration,
                          days: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Hourly load of the connected enterprises over one month [kW], class by class.

    Each class contributes its measured mean day, scaled each day by a draw whose spread
    reproduces the day-to-day variability measured for that class. Repeating a mean day
    unchanged would flatten exactly the peaks a storage sizing is most sensitive to; a mill
    that runs hard two days in three is not a mill running steadily at two thirds.

    A busy day of a unit runs longer, not harder, as a customer of a record's does
    (``longer_days``), under its class's ceiling (``class_cap``): a day on which some unit
    would pass it is drawn unit by unit, and every other day is the units' factors summed
    times the mean day. Where no unit passes its ceiling, the parts give the whole load to
    the last bit as the single sum this replaced did, the draws being the same.
    """
    parts: dict[str, np.ndarray] = {}
    for klass, n in counts.items():
        if not n or klass not in calibration.profiles.index:
            continue
        shape, sigma = _class_day(calibration, klass)
        # Log-normal about a unit mean, so the drawn days average to the measured day.
        factors = rng.lognormal(-0.5 * sigma ** 2, sigma, size=(n, days))
        load = factors.sum(axis=0)[:, None] * shape[None, :]
        cap = class_cap(calibration, klass, shape)
        if cap is not None:
            busy = (factors * float(shape.max()) > cap).any(axis=0)
            if busy.any():
                held = np.zeros((int(busy.sum()), shape.size))
                for unit in factors[:, busy]:
                    held += longer_days(shape, unit, cap)
                load[busy] = held
        parts[klass] = load.ravel()
    return parts


def longer_days(mean_day: np.ndarray, factors: np.ndarray, cap: float | None) -> np.ndarray:
    """A customer's days [kW, one row a day], each a draw of its mean day that runs longer
    rather than harder.

    Day ``d`` holds ``factors[d]`` times the mean day's energy. Scaling every hour by the
    factor, as a class unit's day is drawn, gives a busy day of a mill four times its mean
    power at every hour, far beyond what its motor draws. Here the hour ``h`` of day ``d`` is
    ``min(cap, lambda_d m(h))``, with ``lambda_d`` set so that the day holds its energy: the
    mean day is the customer's power when it runs times the share of each hour it runs, and
    a busy day runs a larger share of each hour, an hour already full passing the rest to
    the hours that are not. A quiet day runs a smaller share, which is the plain scaling. No
    hour exceeds ``cap``, the highest hourly power the customer's meter recorded; a day that
    would hold more than ``cap`` in every hour its mean day uses is held at that, and the
    rest of its draw is lost, which a lognormal draw reaches only far in its tail.
    ``cap`` ``None`` is the plain scaling.
    """
    m = np.asarray(mean_day, dtype=float)
    factors = np.asarray(factors, dtype=float)
    plain = factors[:, None] * m[None, :]
    if cap is None or not np.any(plain > cap):
        return plain
    cap = float(cap)
    busy = np.flatnonzero((plain > cap).any(axis=1))
    target = factors[busy] * m.sum()
    used = m > 0
    full = target >= cap * used.sum()
    days = np.empty((busy.size, m.size))
    days[full] = np.where(used, cap, 0.0)
    if (~full).any():
        goal = target[~full]
        low = np.zeros(goal.size)
        high = np.full(goal.size, cap / m[used].min())
        for _ in range(60):                      # bisection on lambda, to machine precision
            middle = 0.5 * (low + high)
            held = np.minimum(cap, middle[:, None] * m[None, :]).sum(axis=1)
            low, high = np.where(held < goal, middle, low), np.where(held < goal, high, middle)
        rows = np.minimum(cap, high[:, None] * m[None, :])
        # The hours below the cap take what the bisection leaves, so the day is exact.
        free = rows < cap
        rest = goal - np.where(free, 0.0, rows).sum(axis=1)
        below = np.where(free, rows, 0.0).sum(axis=1)
        scale = np.where(below > 0, rest / np.where(below > 0, below, 1.0), 1.0)
        days[~full] = np.where(free, rows * scale[:, None], rows)
    plain[busy] = days
    return plain


def own_level_parts(users, calibration, month: int, days: int,
                    rng: np.random.Generator,
                    scales=None) -> dict[str, np.ndarray]:
    """Hourly load over one month [kW] of a record's customers at their own measured levels.

    Each customer draws its own mean daily energy, times its own factor for the calendar
    month where its readings cover a full year and times its entry of ``scales`` where one
    is given (a household's growth beyond the record), on its shape's hourly profile in
    ``calibration``, with its own day-to-day spread where it was measured and its shape's
    otherwise. A busy day runs longer and not harder, within the highest hourly power its
    meter recorded (``longer_days``). A customer without a measured level draws its shape's
    mean day under its class's ceiling, which is what a unit of its class draws in
    ``monthly_profile_parts``. Customers come in the order given, one draw of ``days``
    factors each; the parts are keyed by shape.
    """
    parts: dict[str, np.ndarray] = {}
    for i, user in enumerate(users):
        if user.klass not in calibration.profiles.index:
            raise ValueError(f"no profile for the shape {user.klass!r}")
        shape, sigma = _class_day(calibration, user.klass)
        cap = class_cap(calibration, user.klass, shape) if user.kwh_per_day is None \
            else None
        if user.kwh_per_day is not None:
            total = float(shape.sum())
            unit = shape / total if total > 0 else np.full(shape.size, 1.0 / shape.size)
            shape = unit * float(user.kwh_per_day)
            if user.monthly:
                shape = shape * float(user.monthly[month - 1])
            if scales is not None:
                shape = shape * float(scales[i])
            cap = getattr(user, "peak_kw", None)
        if user.daily_cv is not None:
            sigma = float(np.sqrt(np.log1p(float(user.daily_cv) ** 2)))
        factors = rng.lognormal(-0.5 * sigma ** 2, sigma, size=days)
        load = longer_days(shape, factors, cap).ravel()
        parts[user.klass] = parts[user.klass] + load if user.klass in parts else load
    return parts
