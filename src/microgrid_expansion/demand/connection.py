"""How many households a village has on its grid, month by month, and since when.

A village is not connected in a day. At the two reference villages the households joined
over two and a half years and stopped well short of the census: a fifth of it at Samionta,
three fifths so far at Gbowele and still rising. Connecting the whole census at year 0, as
the model did, sized every plan for a village that does not exist yet and left nothing to
defer.

Two objects carry the connection here. A ``ConnectionCurve`` is the logistic diffusion of
the connected share of the census, fitted on the reference villages
(``build_connection_curves``). A ``ConnectionSchedule`` is the connected stock of each
category, village month by village month, either drawn from a curve or read off the
roster up to its last month and continued by the curve beyond it. Households join in
monthly cohorts, and each cohort ages on its own clock: the schedule hands the generator
its connected households grouped by the maturity band of their cohort, so the
maturity-conditioned mixture law applies per cohort and not to the community as a whole.

A household whose meter failed and was not replaced leaves the grid, since a failed meter
lets no energy through. The roster's record carries those departures, each from the cohort
it joined in, so the observed stock may fall; beyond the record no trajectory disconnects
anyone. The record also carries the productive users connected by its last month, which a
village with a plant starts from as it does from its households.

The village clock starts at the site's first customer connection, the origin the
productive-use intensity is estimated on. The whole census at village month 0 is the
degenerate case, and it reproduces the model as it stood bit for bit.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from ..paths import REFERENCE_DIR
from ..settings import CONNECTION_TRAJECTORIES as TRAJECTORIES
from ..settings import HIGH_PLATEAUS
from ..sites import HOUSEHOLD_TYPES

CURVES_PATH = REFERENCE_DIR / "connection_curves.csv"
OBSERVED_PATH = REFERENCE_DIR / "connection_observed.csv"

#: Under ``pairing = "paired"``, each reference village's connection goes with its growth.
PAIRED_WITH_GROWTH = {"slow": "low", "central": "central", "fast": "high"}
#: The reference villages that bracket a new site: Samionta connects few, Gbowele many.
LOW_SITE, HIGH_SITE = "Samionta", "Gbowele"
#: Village months a drawn schedule covers. Beyond it the stock is held, which a logistic
#: has long since reached: forty years past the first connection.
HORIZON_MONTHS = 480
#: A roster that ends longer than this before the plan's first January is not continued.
MAX_GAP_MONTHS = 12


def _month_index(month: str) -> int:
    """``YYYY-MM`` as a count of months, so that two months subtract."""
    period = pd.Period(month, freq="M")
    return period.year * 12 + period.month - 1


@dataclass(frozen=True)
class ConnectionCurve:
    """A logistic diffusion of the connected share of the census.

    ``l(a) = 1 / (1 + exp(-r (a - m)))`` on the village clock, scaled by a plateau share
    ``s`` of the census. ``rate_per_month = math.inf`` is the instant limit, every
    household of the plateau connected at the midpoint and none before.
    """

    share: float
    rate_per_month: float
    midpoint_months: float
    label: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not 0.0 < float(self.share) <= 1.0:
            raise ValueError(f"a plateau share lies in (0, 1], not {self.share}")
        if not float(self.rate_per_month) > 0.0:
            raise ValueError(f"a connection rate must be positive, not "
                             f"{self.rate_per_month}")

    def unit(self, age: float) -> float:
        """The unit logistic ``l(a)`` at village age ``a``."""
        if math.isinf(self.rate_per_month):
            return 1.0 if age >= self.midpoint_months else 0.0
        x = self.rate_per_month * (age - self.midpoint_months)
        if x >= 0.0:
            return 1.0 / (1.0 + math.exp(-x))
        e = math.exp(x)
        return e / (1.0 + e)


@dataclass(frozen=True)
class ObservedState:
    """A reference village's connections as its record holds them, up to its last month."""

    site: str
    origin_month: str
    last_month: str
    categories: tuple[str, ...]
    #: Cumulative households per category connected at village months ``0..T``, before
    #: the departures are taken off.
    stock: tuple[tuple[int, ...], ...]
    #: Households that left the grid within the record, on the village clock:
    #: ``(cohort month, departure month, category index, households)``.
    departures: tuple[tuple[int, int, int, int], ...] = ()
    #: Productive users connected at village months ``0..T``, net of any that left.
    productive: tuple[int, ...] = ()

    def connected(self, age: int) -> tuple[int, ...]:
        """Households of each category on the grid at village month ``age``."""
        row = list(self.stock[min(int(age), self.last_age)])
        for _, gone, k, n in self.departures:
            if gone <= age:
                row[k] -= n
        return tuple(row)

    @property
    def last_age(self) -> int:
        """``T``: the village age of the roster's last month."""
        return len(self.stock) - 1

    def age_in(self, month: str) -> int:
        """Village age, in whole months, of a calendar month."""
        return _month_index(month) - _month_index(self.origin_month)

    def year0_age(self, base_year: int) -> int:
        """Village age at the plan's year 0, which starts in January of ``base_year``.

        Derived, not declared. A roster that ends more than a year before that January is
        refused rather than continued in silence: the curve would then be inventing the
        village's recent past rather than its future.
        """
        age = self.age_in(f"{int(base_year)}-01")
        if age < 0:
            raise ValueError(f"the plan starts in {base_year}, before {self.site}'s first "
                             f"connection in {self.origin_month}")
        if age - self.last_age > MAX_GAP_MONTHS:
            raise ValueError(
                f"{self.site}'s roster ends in {self.last_month}, more than "
                f"{MAX_GAP_MONTHS} months before the plan's first January of {base_year}; "
                "extend the roster rather than extrapolate the village's recent past")
        return age


@lru_cache(maxsize=1)
def _curves_table() -> pd.DataFrame:
    return pd.read_csv(CURVES_PATH)


def curve_row(site_name: str, variant: str) -> pd.Series:
    """One row of the calibration table."""
    table = _curves_table()
    rows = table[(table.site_name == site_name) & (table.variant == variant)]
    if rows.empty:
        raise ValueError(f"no connection curve {variant!r} for {site_name!r}")
    return rows.iloc[0]


def _curve(row: pd.Series, label: str) -> ConnectionCurve:
    return ConnectionCurve(float(row.plateau_share), float(row.rate_per_month),
                           float(row.midpoint_months), label=label)


def _between(low: ConnectionCurve, high: ConnectionCurve) -> ConnectionCurve:
    return ConnectionCurve(0.5 * (low.share + high.share),
                           0.5 * (low.rate_per_month + high.rate_per_month),
                           0.5 * (low.midpoint_months + high.midpoint_months),
                           label="central")


def load_curves(settings=None) -> dict[str, ConnectionCurve]:
    """The three trajectories of a new site, bracketed by the two reference villages.

    ``low`` is Samionta's estimate and ``high`` Gbowele's, or, while Gbowele's plateau is not
    identified, the variant ``settings.connection.high_plateau`` names, refitted at that
    plateau. ``central`` takes the means of the two. The within-site errors are reported in
    the table, not drawn: the two villages differ by far more than either is uncertain.
    """
    high_variant = (getattr(getattr(settings, "connection", None), "high_plateau", None)
                    or HIGH_PLATEAUS[0])
    low = _curve(curve_row(LOW_SITE, "estimate"), "low")
    estimate = curve_row(HIGH_SITE, "estimate")
    high = _curve(estimate if bool(estimate.identified)
                  else curve_row(HIGH_SITE, high_variant), "high")
    return {"low": low, "central": _between(low, high), "high": high}


def own_curves(site_name: str) -> dict[str, ConnectionCurve]:
    """A reference village's future bracketed by its own fit.

    Where its plateau is identified, the two ends of the plateau's profile interval, the
    rate and the midpoint refitted at each, with the estimate as ``central``. Two standard
    errors either side of the estimate would be optimistic where the estimate sits at its
    bound, the stock already connected, as Samionta's does. Where the plateau is not
    identified, from the profile's lower bound to the census, each refitted at its
    plateau, with ``central`` between them.
    """
    estimate = curve_row(site_name, "estimate")
    if bool(estimate.identified):
        return {"low": _curve(curve_row(site_name, "profile_lower_bound"), "low"),
                "central": _curve(estimate, "central"),
                "high": _curve(curve_row(site_name, "profile_upper_bound"), "high")}
    low = _curve(curve_row(site_name, "profile_lower_bound"), "low")
    high = _curve(curve_row(site_name, "census"), "high")
    return {"low": low, "central": _between(low, high), "high": high}


@lru_cache(maxsize=None)
def observed_state(site_name: str) -> ObservedState | None:
    """The record of a site, or ``None`` for a site that has none."""
    table = pd.read_csv(OBSERVED_PATH, dtype={"departure_month": str},
                        keep_default_na=False)
    rows = table[table.site_name == site_name]
    if rows.empty:
        return None
    estimate = curve_row(site_name, "estimate")
    origin, last = str(estimate.origin_month), str(estimate.last_month)
    households = rows[rows.customer_type.isin(HOUSEHOLD_TYPES)]
    categories = tuple(dict.fromkeys(sorted(households.customer_type)))
    span = _month_index(last) - _month_index(origin) + 1

    def age(month: str) -> int:
        out = _month_index(month) - _month_index(origin)
        if not 0 <= out < span:
            raise ValueError(f"{site_name}: {month} lies outside the record's span "
                             f"{origin} to {last}")
        return out

    counts = [[0] * len(categories) for _ in range(span)]
    departures = []
    for row in households.itertuples():
        joined, k = age(row.connection_month), categories.index(row.customer_type)
        counts[joined][k] += int(row.customers)
        if row.departure_month:
            departures.append((joined, age(row.departure_month), k, int(row.customers)))
    stock, running = [], [0] * len(categories)
    for month in counts:
        running = [a + b for a, b in zip(running, month)]
        stock.append(tuple(running))
    productive = [0] * span
    for row in rows[rows.customer_type == "PUE"].itertuples():
        joined = age(row.connection_month)
        gone = age(row.departure_month) if row.departure_month else span
        for a in range(joined, gone):
            productive[a] += int(row.customers)
    return ObservedState(site_name, origin, last, categories, tuple(stock),
                         tuple(sorted(departures)), tuple(productive))


@dataclass(frozen=True)
class ConnectionSchedule:
    """The connected stock of each household category over village months ``0..A_max``.

    ``stock`` counts the households that have joined, cumulatively; ``departures`` takes
    off those that left, each from the cohort it joined in, which only a village's own
    record holds. Beyond its last month the stock is held. Trailing months equal to the one
    before are dropped on construction, so two schedules that connect the same households
    at the same ages are equal whatever horizon they were drawn over.

    ``productive`` is the productive users a village's record holds at village months
    ``0..T``, empty for a schedule drawn from a curve alone.
    """

    categories: tuple[str, ...]
    census: tuple[int, ...]
    stock: tuple[tuple[int, ...], ...]
    label: str = field(default="", compare=False)
    #: ``(cohort month, departure month, category index, households)``.
    departures: tuple[tuple[int, int, int, int], ...] = ()
    productive: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        width = len(self.categories)
        if len(self.census) != width or not self.stock:
            raise ValueError("a schedule holds one census figure per category and at "
                             "least one month")
        previous = (0,) * width
        for age, row in enumerate(self.stock):
            if len(row) != width:
                raise ValueError(f"village month {age} holds {len(row)} categories, "
                                 f"not {width}")
            for k, (n, before) in enumerate(zip(row, previous)):
                if int(n) != n or n < before:
                    raise ValueError(
                        f"the households of {self.categories[k]} joined by village month "
                        f"{age} are {n}: a whole number, and no fewer than the {before} "
                        "before")
            previous = row
        rows = [tuple(int(n) for n in row) for row in self.stock]
        while len(rows) > 1 and rows[-1] == rows[-2]:
            rows.pop()
        object.__setattr__(self, "stock", tuple(rows))
        departures = tuple(sorted(tuple(int(x) for x in d) for d in self.departures))
        object.__setattr__(self, "departures", departures)
        object.__setattr__(self, "productive", tuple(int(n) for n in self.productive))
        for joined, gone, k, n in departures:
            if not (0 <= joined < gone and 0 <= k < width and n > 0):
                raise ValueError(f"a departure must leave after it joined, from a known "
                                 f"category, and count someone: {(joined, gone, k, n)}")
        last = max([len(rows) - 1, *(gone for _, gone, _, _ in departures)])
        for age in range(last + 1):
            for k, (n, cap) in enumerate(zip(self.connected(age).values(), self.census)):
                if not 0 <= n <= cap:
                    raise ValueError(
                        f"the stock of {self.categories[k]} at village month {age} is {n}: "
                        f"it must lie between none and the census {cap}")
        for joined, k in {(j, k) for j, _, k, _ in departures}:
            left = sum(n for j, _, kk, n in departures if j == joined and kk == k)
            if left > self._row(joined)[k] - self._row(joined - 1)[k]:
                raise ValueError(f"more households leave the cohort of village month "
                                 f"{joined} than joined it")
        if any(n < 0 for n in self.productive):
            raise ValueError("a count of productive users cannot be negative")

    # ---------------------------------------------------------------- reading
    def _row(self, age: int) -> tuple[int, ...]:
        if age < 0:
            return (0,) * len(self.categories)
        return self.stock[min(int(age), len(self.stock) - 1)]

    def connected(self, age: int) -> dict[str, int]:
        """Households of each category on the grid at village month ``age``."""
        row = self._row(age)
        if self.departures:
            row = list(row)
            for _, gone, k, n in self.departures:
                if gone <= age:
                    row[k] -= n
        return dict(zip(self.categories, row))

    def cohort(self, month: int) -> dict[str, int]:
        """Households of each category connected in village month ``month``."""
        return {k: a - b for k, a, b in
                zip(self.categories, self._row(month), self._row(month - 1))}

    def census_by_band(self, age: int) -> dict[str, dict[str, int]]:
        """Connected households grouped by the maturity band of their cohort.

        A household of the cohort of month ``u`` is ``age - u`` months old at village age
        ``age``; one that has left by then is in no band. Bands come in ``MATURITY_LABELS``
        order and empty ones are left out; each band's mapping keeps the census's category
        order, so the draws fall in the order they always did.
        """
        from .growth import maturity_band
        from .maturity import MATURITY_LABELS

        totals = {band: [0] * len(self.categories) for band in MATURITY_LABELS}
        for month in range(min(int(age), len(self.stock) - 1) + 1):
            joined = [a - b for a, b in zip(self._row(month), self._row(month - 1))]
            for cohort, gone, k, n in self.departures:
                if cohort == month and gone <= age:
                    joined[k] -= n
            if any(joined):
                into = totals[maturity_band(int(age) - month)]
                for k, n in enumerate(joined):
                    into[k] += n
        return {band: dict(zip(self.categories, counts))
                for band, counts in totals.items() if any(counts)}

    def digest(self, until: int) -> str:
        """A hash of the stock over village months ``0..until``, and of nothing else.

        The trajectory's name is left out on purpose: two trajectories that connect the same
        households up to the end of a year draw the same year. The departures and the
        observed productive users enter only where a schedule has them, so that a schedule
        drawn from a curve keeps the digest it had before either existed.
        """
        digest = hashlib.sha1(",".join(self.categories).encode())
        for age in range(int(until) + 1):
            digest.update(",".join(str(n) for n in self._row(age)).encode() + b";")
        gone = [d for d in self.departures if d[1] <= until]
        if gone:
            digest.update(b"departures:" + repr(gone).encode())
        if self.productive:
            digest.update(b"productive:" + repr(self.productive[:int(until) + 1]).encode())
        return digest.hexdigest()[:12]

    @property
    def is_whole_census(self) -> bool:
        """Every household connected at village month 0: the model before this module."""
        return (len(self.stock) == 1 and self.stock[0] == self.census
                and not self.departures and not self.productive)

    def observed_productive(self, age: int) -> tuple[int, int] | None:
        """The productive users a village's record holds, and the record's last month.

        At or before the record's last month ``T``, the users connected at ``age``; beyond
        it, those of ``T``, which the rule then adds to. ``None`` for a schedule that has no
        record behind it.
        """
        if not self.productive:
            return None
        last = len(self.productive) - 1
        return self.productive[min(int(age), last)], last

    # ---------------------------------------------------------- construction
    @classmethod
    def whole_census(cls, site) -> "ConnectionSchedule":
        """Every household of the census connected at village month 0."""
        census = tuple(int(n) for n in site.census.values())
        return cls(tuple(site.census), census, (census,), label="census")

    @classmethod
    def greenfield(cls, site, curve: ConnectionCurve,
                   horizon_months: int = HORIZON_MONTHS) -> "ConnectionSchedule":
        """A new site's stock, ``floor(s l(a) H_k + 1/2)`` for each category apart.

        Rounding each category on its own keeps each monotone; the total may then differ
        from the rounded total by a household per category, which is accepted.
        """
        census = tuple(int(n) for n in site.census.values())
        stock = tuple(tuple(math.floor(curve.share * curve.unit(a) * h + 0.5)
                            for h in census)
                      for a in range(int(horizon_months) + 1))
        return cls(tuple(site.census), census, stock, label=curve.label)

    @classmethod
    def brownfield(cls, site, observed: ObservedState, curve: ConnectionCurve,
                   horizon_months: int = HORIZON_MONTHS) -> "ConnectionSchedule":
        """The record up to its last month ``T``, and the curve conditioned on it beyond.

        ``N_k(a) = N_k(T) + floor((Nbar_k - N_k(T)) (l(a) - l(T)) / (1 - l(T)) + 1/2)``,
        with ``N_k(T)`` the stock on the grid at ``T``, net of the record's departures, and
        ``Nbar_k`` the plateau or that stock, whichever is larger. It starts on the
        observation, never decreases, tends to the plateau, and stays flat where the
        plateau is already passed: no trajectory disconnects anyone. The record's
        productive users come along, for the generator to start from.
        """
        categories = tuple(site.census)
        census = tuple(int(n) for n in site.census.values())
        unknown = set(observed.categories) - set(categories)
        if unknown:
            raise ValueError(f"{site.name}'s roster connects {sorted(unknown)}, which its "
                             "census does not hold")
        place = [observed.categories.index(k) if k in observed.categories else None
                 for k in categories]
        rows = [tuple(0 if i is None else row[i] for i in place) for row in observed.stock]
        departures = tuple((joined, gone, place.index(k), n)
                           for joined, gone, k, n in observed.departures)
        t = observed.last_age
        joined_by_t = rows[-1]
        net = observed.connected(t)
        on_grid = tuple(0 if i is None else net[i] for i in place)
        for k, n, h in zip(categories, on_grid, census):
            if n > h:
                raise ValueError(f"{site.name} has {n} households of {k} connected and a "
                                 f"census of {h}; the census is out of date")
        ceiling = tuple(max(math.floor(curve.share * h + 0.5), n)
                        for h, n in zip(census, on_grid))
        base = curve.unit(t)
        for age in range(t + 1, int(horizon_months) + 1):
            if 1.0 - base < 1e-9:
                break
            progress = (curve.unit(age) - base) / (1.0 - base)
            rows.append(tuple(joined + math.floor((c - n) * progress + 0.5)
                              for joined, n, c in zip(joined_by_t, on_grid, ceiling)))
        return cls(categories, census, tuple(rows), label=curve.label,
                   departures=departures, productive=observed.productive)


@dataclass
class ConnectionPlan:
    """The connection schedules one run may use, and the village age its year 0 stands at."""

    mode: str
    #: By trajectory name; under ``mode = "census"`` a single entry, ``"census"``.
    schedules: dict[str, ConnectionSchedule]
    #: Derived for a site with its own record in a brownfield run; ``None`` where the
    #: declared ``maturity_months`` stands.
    year0_age: int | None = None

    def schedule(self, trajectory: str) -> ConnectionSchedule:
        if self.mode == "census":
            return self.schedules["census"]
        if trajectory not in self.schedules:
            raise ValueError(f"unknown connection trajectory {trajectory!r}; choose from "
                             f"{sorted(self.schedules)}")
        return self.schedules[trajectory]


def plan(site, settings=None, brownfield: bool | None = None,
         horizon_months: int = HORIZON_MONTHS) -> ConnectionPlan:
    """The schedules ``settings.connection`` asks for at ``site``.

    ``brownfield`` defaults to whether the settings declare a plant already standing. A
    brownfield site with rows in the observed table starts from them; any other site
    follows the curves from village month 0.
    """
    from ..settings import default_settings

    settings = default_settings() if settings is None else settings
    choice = settings.connection
    if choice.mode == "census":
        return ConnectionPlan("census", {"census": ConnectionSchedule.whole_census(site)})
    if brownfield is None:
        brownfield = not settings.installed.is_empty
    observed = observed_state(site.name) if brownfield else None
    if observed is None:
        return ConnectionPlan(choice.mode, {
            name: ConnectionSchedule.greenfield(site, curve, horizon_months)
            for name, curve in load_curves(settings).items()})
    curves = (own_curves(site.name) if choice.brownfield_bracket == "own"
              else load_curves(settings))
    return ConnectionPlan(
        choice.mode,
        {name: ConnectionSchedule.brownfield(site, observed, curve, horizon_months)
         for name, curve in curves.items()},
        year0_age=observed.year0_age(settings.installed.base_year))
