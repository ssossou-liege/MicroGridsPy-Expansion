r"""Fit how the reference villages' households joined the grid, and record who joined when.

Writes three tables to ``data/ramp_params/reference/``:

``connection_curves.csv``
    A logistic curve of the connected household stock at each reference village, under
    four plateau variants: the least-squares ``estimate``, the two ends of the plateau's
    95 % profile interval (``profile_lower_bound`` and ``profile_upper_bound``) and the
    ``census`` (every household connected in the end). For the three fixed-plateau
    variants the rate and the midpoint are refitted at that plateau.
``connection_observed.csv``
    Customers per site, type, connection month and, where they left the grid within the
    record, departure month: households by category, the state a village with a plant and
    a record starts its plan from, and productive users, which that plan starts from too.
``meter_status.csv``
    Written for inspection. Every customer code of the roster or of the meter archive,
    with its type and where the type comes from, its connection month, its first and last
    reading, and what became of its meter: still recording, failed, never recorded, or not
    a customer at all. It is the list the field team confirms.

*The record.* Two can be built, and ``--record`` chooses:

- ``extended``, the default: the roster and every customer of the meter archive the roster
  does not list, up to the archive's last complete month ``T`` (October 2026). Those
  customers are held in ``data/demand/archive_customers.csv``: each is connected in the
  month of its first reading, and its type comes from the operator's field census
  (received on 7 November 2026), its type column first and its category column otherwise,
  or, where the census gives none, from its consumption by ``classify_meter``.
  ``--census`` rebuilds that table from the two workbooks, reading their code and type
  columns and nothing else.
- ``roster``: the operator's customer roster alone, whose last month ``T`` is the month of
  its latest connection (May 2026). Each customer keeps its roster type and date.

Neither source types the roster's own customers the way the roster does. The profile rule
misplaces more than a quarter of them, and no rule on these descriptors does much better:
a small trader draws what a household draws, and the household categories are
socio-economic rather than electrical. The census's category column follows a taxonomy of
its own for the household tiers, which is why its type column is read first. But what the
record feeds is the connected stock, not the types, and the few codes the profile types
move it by a handful of households at most, which ``profile_bound`` reports. The roster
record, meanwhile, is contradicted by the meters: Gbowele connects in campaigns, and its
roster ends before the latest one. So the tables hold the extended record, and the roster
one is a sensitivity. A fresh roster would replace the census and profile types and the
first-reading dates, and nothing else.

*Silent meters.* A meter whose last reading, a zero included, falls three months or more
before the end of the archive has failed, and according to the operator a failed meter
lets no energy through. A replaced meter keeps its customer code, and the archive is kept
per code, so a household continuing on a new meter is one customer already. Otherwise a
meter that starts recording at the same site within two months of the failure, at a
similar level and with a similar day, is listed as a candidate replacement and not
merged: a departure and a new connection, which leaves the stock as it is and only
resets the cohort's age. A household whose failed meter was not replaced leaves the
connected stock from the month after its last reading. A roster customer whose meter
never recorded is listed apart and left out. A code that neither the roster nor the
census knows and whose readings stopped early is not a customer: a meter tried during
the test period, or for a week, and taken down.

The fit is made on the *connected stock* net of those departures, not on the households
active in a month. The mixture law already carries the connected households that consume
nothing (its ``inactive`` state), so a plateau fitted on active households and passed
through that law would take those months out twice.

The village clock starts at the site's earliest roster connection over every customer
type, which is the origin ``build_productive_profiles.connection_intensity`` takes, so the
connection curve and the productive-use intensity run on one clock.

The report checks two acceptance criteria against the meters in month ``T``: the active
households the mixture law expects of the stock connected before ``T`` began against the
households the meters find active (S2-A5), and the productive users expected against the
productive users metered (S2-A6). A household with no reading at all in ``T`` is not an
observation and leaves both sides of S2-A5, the mixture law having been estimated on months
with readings; counted inactive instead, it is reported as a sensitivity.

Deterministic given its inputs; ``tests/test_progressive_connection.py`` re-runs it and
asserts that it reproduces the committed tables.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import DEMAND_DIR, REFERENCE_DIR
from ..sites import HOUSEHOLD_TYPES, SITES
from .build_monthly_household_clusters import INTERVAL_HOURS

CURVES_FILE = "connection_curves.csv"
OBSERVED_FILE = "connection_observed.csv"
STATUS_FILE = "meter_status.csv"
ARCHIVE_CUSTOMERS = DEMAND_DIR / "archive_customers.csv"

RECORDS = ("roster", "extended")
DEFAULT_RECORD = "extended"

#: Confidence level of the plateau's profile interval.
LEVEL = 0.95

#: Bounds of the search, wide enough never to bind on these records: a rate between one
#: household in ten thousand a month and a step, a midpoint ten years either side.
RATE_BOUNDS = (1e-4, 5.0)
MIDPOINT_BOUNDS = (-120.0, 240.0)

#: Months a meter must have been silent at the end of the archive to be read as failed.
SILENT_MONTHS = 3
#: A replacement starts recording within this many months of the failure.
REPLACEMENT_MONTHS = 2
#: A candidate replacement draws within this factor of the failed meter's daily energy,
#: and its mean day correlates with the failed meter's at least this well.
LEVEL_FACTOR = 2.0
PROFILE_CORRELATION = 0.8

#: The census workbooks' customer-code column at each site, and the two type columns read
#: from them, in the order they are believed: the type column, then the category column,
#: whose household tiers follow a taxonomy of their own (it calls HH2 most of the roster's
#: HH1 households). No other column is opened: the workbooks hold personal data.
CENSUS_CODE_COLUMN = {"Samionta": "N° client Koios", "Gbowele": "Unnamed: 4"}
#: The workbooks' own column names, accents intentional: they are data, not prose.
CENSUS_TYPE_COLUMNS = ("Type (HH123,SME,CHU,SCH)", "Catégorie")
CENSUS_SHEET = "Recensement"
#: How the census's types read in the roster's terms. Anything else leaves a code untyped.
CENSUS_TYPES = {"HH1": "HH1", "HH2": "HH2", "HH3": "HH3", "SME": "PUE", "CHU": "CHU",
                "SCH": "SCH"}

#: The profile rule. Hours of the working day, and the thresholds above which a meter is
#: read as a productive user or a place of worship; chosen as the best agreement with the
#: roster's types over a small grid, so the misplacement it reports is if anything low.
DAYTIME_HOURS = (7, 18)
PRODUCTIVE_DAYTIME_SHARE = 0.35
PRODUCTIVE_DAILY_KWH = 1.5
CHURCH_SUNDAY_SHARE = 0.25

#: Above this a productive user's month counts as active, for S2-A6.
PRODUCTIVE_ACTIVE_KWH = 0.05


def load_roster() -> pd.DataFrame:
    """The operator's customer roster, with each connection's calendar month.

    A household's type is its category in the household register, the roster carrying
    only that it is a household.
    """
    roster = pd.read_parquet(DEMAND_DIR / "customer_info.parquet")
    roster["month"] = roster.connection_date.dt.to_period("M")
    register = pd.read_csv(DEMAND_DIR / "household_customers.csv")
    category = roster.customer_code.map(
        register.set_index("customer_code").customer_type)
    households = roster.customer_type == "HH"
    if category[households].isna().any():
        raise ValueError(f"{int(category[households].isna().sum())} households of the "
                         "roster have no category in the household register")
    roster["customer_type"] = roster.customer_type.where(~households, category)
    return roster


def last_roster_month(roster: pd.DataFrame) -> pd.Period:
    """The last month the roster covers.

    The roster is one extract for both villages, so its last month is that of its latest
    connection, wherever it is. A village that connected nobody in that month still has it
    observed, as a month with no connection.
    """
    return roster.connection_date.max().to_period("M")


def last_complete_month(end: pd.Timestamp) -> pd.Period:
    """The last month an archive ending at ``end`` covers to its final quarter-hour."""
    month = end.to_period("M")
    if end < (month + 1).start_time - pd.Timedelta(hours=INTERVAL_HOURS):
        month -= 1
    return month


# ------------------------------------------------------------------- the meters
@lru_cache(maxsize=None)
def _archive(site_name: str) -> pd.DataFrame:
    readings = pd.read_parquet(SITES[site_name].meter_path(),
                               columns=["timestamp", "customer_code", "power_W"])
    return readings.assign(kwh=readings.power_W * INTERVAL_HOURS / 1000.0,
                           month=readings.timestamp.dt.to_period("M"))


@lru_cache(maxsize=None)
def meter_summary(site_name: str) -> tuple[pd.DataFrame, pd.Series, pd.Timestamp]:
    """Each meter's record at a site, its energy by month, and the archive's end.

    Per code: the first and last reading, the energy over the record, the mean energy of
    a day with readings, and the shares of it drawn in the working day and on Sundays.
    """
    readings = _archive(site_name)
    hour = readings.timestamp.dt.hour
    grouped = readings.groupby("customer_code")
    meters = pd.DataFrame({"first": grouped.timestamp.min(),
                           "last": grouped.timestamp.max(),
                           "kwh": grouped.kwh.sum(),
                           "days": readings.timestamp.dt.normalize()
                                           .groupby(readings.customer_code).nunique()})
    daytime = readings[(hour >= DAYTIME_HOURS[0]) & (hour < DAYTIME_HOURS[1])]
    sunday = readings[readings.timestamp.dt.dayofweek == 6]
    meters["daily_kwh"] = meters.kwh / meters.days
    for name, part in (("daytime_share", daytime), ("sunday_share", sunday)):
        drawn = part.groupby("customer_code").kwh.sum().reindex(meters.index, fill_value=0)
        meters[name] = (drawn / meters.kwh).where(meters.kwh > 0)
    monthly = readings.groupby(["customer_code", "month"]).kwh.sum()
    return meters, monthly, readings.timestamp.max()


def classify_meter(meter: pd.Series, household_category: str) -> str:
    """A customer's type read off its consumption, for a meter the roster does not list.

    A meter that draws most of its energy in the working day, or more than a small
    workshop does, is a productive user; one that draws a quarter of its week on Sunday is
    a place of worship; any other is a household, of the site's commonest category. A
    meter that has drawn nothing has no profile to read, and is taken as a household too.
    """
    if not meter.kwh > 0:
        return household_category
    if meter.daytime_share >= PRODUCTIVE_DAYTIME_SHARE \
            or meter.daily_kwh >= PRODUCTIVE_DAILY_KWH:
        return "PUE"
    if meter.sunday_share >= CHURCH_SUNDAY_SHARE:
        return "CHU"
    return household_category


def _commonest_category(roster: pd.DataFrame, site_name: str) -> str:
    types = roster.loc[roster.site_name == site_name, "customer_type"]
    return types[types.isin(HOUSEHOLD_TYPES)].value_counts().idxmax()


def profile_bound(status: pd.DataFrame, record: str = DEFAULT_RECORD) -> pd.DataFrame:
    """How far the profile rule could move each reference village's stock at ``T``.

    What the record feeds is the connected stock, so a misplaced type matters only where
    it puts a household outside the stock or another customer inside it. Per site: the
    households on the grid at ``T``, those of them whose type the profile gave, and the
    customers on the grid the profile typed as something else. Were the rule wrong on
    every one of them, the stock would move by the larger of the last two, which is
    therefore the most it can move it.
    """
    roster = load_roster()
    customers = record_customers(status, record)
    rows = []
    for name in _reference_sites(roster):
        last = record_span(roster, record, name)[1]
        held = customers[customers.site_name == name]
        held = held[held.connection_month.map(lambda m: pd.Period(m, freq="M") <= last)
                    & ~held.departure_month.map(lambda m: bool(m)
                                                and pd.Period(m, freq="M") <= last)]
        household = held.customer_type.isin(HOUSEHOLD_TYPES)
        profiled = held.type_source == "profile"
        rows.append({"site_name": name, "month": str(last),
                     "households": int(household.sum()),
                     "profiled_households": int((household & profiled).sum()),
                     "profiled_others": int((~household & profiled).sum()),
                     "most_moved": int(max((household & profiled).sum(),
                                           (~household & profiled).sum()))})
    return pd.DataFrame(rows)


def classification_check(roster: pd.DataFrame) -> pd.DataFrame:
    """The profile rule applied to the roster's own customers: their type and the rule's."""
    rows = []
    for name in _reference_sites(roster):
        meters = meter_summary(name)[0]
        category = _commonest_category(roster, name)
        for row in roster[roster.site_name == name].itertuples():
            if row.customer_code in meters.index:
                rows.append({"site_name": name, "customer_code": row.customer_code,
                             "roster": row.customer_type,
                             "rule": classify_meter(meters.loc[row.customer_code],
                                                    category)})
    return pd.DataFrame(rows)


def _day_and_level(site_name: str, code: str, start, stop) -> tuple[np.ndarray, float]:
    readings = _archive(site_name)
    part = readings[(readings.customer_code == code) & (readings.timestamp >= start)
                    & (readings.timestamp < stop)]
    shape = part.groupby(part.timestamp.dt.hour).power_W.mean().reindex(range(24),
                                                                       fill_value=0.0)
    days = part.timestamp.dt.normalize().nunique()
    return shape.to_numpy(), float(part.kwh.sum() / days) if days else 0.0


def candidate_replacements(site_name: str, failed: pd.DataFrame) -> pd.DataFrame:
    """Meters that may have replaced a failed one, listed for the field team, not merged.

    A candidate starts recording at the same site within two months after the failed
    meter stopped, draws within a factor of two of its daily energy and has a day
    correlated with its own, each taken over the three months nearest the change. A
    failed meter that drew nothing over its last three months has no level or day to
    compare, and no candidate.
    """
    meters = meter_summary(site_name)[0]
    window = pd.DateOffset(months=SILENT_MONTHS)
    rows = []
    for code, last in failed.last.items():
        before, level = _day_and_level(site_name, code, last - window, last
                                       + pd.Timedelta(minutes=1))
        if not level > 0:
            continue
        starting = meters[(meters["first"] > last)
                          & (meters["first"] <= last + pd.DateOffset(months=REPLACEMENT_MONTHS))]
        for other, first in starting["first"].items():
            if other == code:
                continue
            after, other_level = _day_and_level(site_name, other, first, first + window)
            ratio = other_level / level
            if not 1.0 / LEVEL_FACTOR <= ratio <= LEVEL_FACTOR:
                continue
            correlation = float(np.corrcoef(before, after)[0, 1]) \
                if before.std() > 0 and after.std() > 0 else float("nan")
            if correlation >= PROFILE_CORRELATION:
                rows.append({"site_name": site_name, "failed": code, "candidate": other,
                             "level_ratio": ratio, "day_correlation": correlation})
    return pd.DataFrame(rows, columns=["site_name", "failed", "candidate", "level_ratio",
                                       "day_correlation"])


def _failed(meter: pd.Series, end: pd.Timestamp) -> bool:
    """Whether a meter's last reading falls three months or more before the archive's end."""
    return bool(meter["last"] <= end - pd.DateOffset(months=SILENT_MONTHS))


def read_census(path: Path, site_name: str) -> tuple[pd.DataFrame, list[str]]:
    """The type the operator's field census gives each customer code at one site.

    Only the code and the two type columns are opened. The type column is believed first
    and the category column where it is empty; a value outside ``CENSUS_TYPES`` leaves the
    code untyped. A code entered twice keeps its first row, and the codes entered twice
    are returned so that they can be reported.
    """
    from .build_meter_archive import VALID_CODE

    code = CENSUS_CODE_COLUMN[site_name]
    wanted = (code, *CENSUS_TYPE_COLUMNS)
    sheet = pd.read_excel(path, sheet_name=CENSUS_SHEET, usecols=lambda c: c in wanted)
    sheet["customer_code"] = sheet[code].fillna("").astype(str).str.strip().str.upper()
    sheet = sheet[sheet.customer_code.str.match(VALID_CODE)]
    typed = pd.Series(np.nan, index=sheet.index, dtype=object)
    for column in CENSUS_TYPE_COLUMNS:
        read = sheet[column].map(lambda v: CENSUS_TYPES.get(str(v).strip()))
        typed = typed.where(typed.notna(), read)
    sheet = sheet.assign(census_type=typed)
    twice = sorted(sheet.loc[sheet.customer_code.duplicated(), "customer_code"].unique())
    return sheet.drop_duplicates("customer_code")[["customer_code", "census_type"]], twice


def archive_customers(roster: pd.DataFrame,
                      census: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The customers of the meter archive the roster does not list, and their type.

    Each is connected in the month of its first reading. Its type is the census's where
    the census gives one, and the profile rule's otherwise. A code the census does not
    know and whose readings stopped early is not a customer, and is left out.
    """
    rows = []
    for name in _reference_sites(roster):
        meters, _, end = meter_summary(name)
        listed = set(roster.loc[roster.site_name == name, "customer_code"])
        typed = census[name].set_index("customer_code").census_type
        category = _commonest_category(roster, name)
        for code in sorted(set(meters.index) - listed):
            meter = meters.loc[code]
            if code not in typed.index and _failed(meter, end):
                continue
            kind = typed.get(code)
            source = "census" if isinstance(kind, str) else "profile"
            if source == "profile":
                kind = classify_meter(meter, category)
            household = kind in HOUSEHOLD_TYPES
            rows.append({"customer_code": code, "site_name": name,
                         "customer_type": "HH" if household else kind,
                         "category": kind if household else "",
                         "connection_month": str(meter["first"].to_period("M")),
                         "source": source})
    return pd.DataFrame(rows, columns=["customer_code", "site_name", "customer_type",
                                       "category", "connection_month", "source"])


def load_archive_customers() -> pd.DataFrame:
    """The table ``archive_customers`` wrote, with a household's category as its type."""
    table = pd.read_csv(ARCHIVE_CUSTOMERS, dtype=str, keep_default_na=False)
    table["customer_type"] = table.category.where(table.customer_type == "HH",
                                                  table.customer_type)
    return table


def meter_status(roster: pd.DataFrame, unlisted: pd.DataFrame) -> pd.DataFrame:
    """Every customer code of the roster or the archive, and what became of its meter."""
    rows = []
    for name in _reference_sites(roster):
        meters, _, end = meter_summary(name)
        on_roster = roster[roster.site_name == name].set_index("customer_code")
        known = unlisted[unlisted.site_name == name].set_index("customer_code")
        for code in sorted(set(on_roster.index) | set(meters.index)):
            listed = code in on_roster.index
            recorded = code in meters.index
            customer = listed or code in known.index
            meter = meters.loc[code] if recorded else None
            if not customer:
                status = "not_a_customer"
            elif not recorded:
                status = "never_recorded"
            elif _failed(meter, end):
                status = "failed"
            else:
                status = "recording"
            first = meter["first"].to_period("M") if recorded else None
            last = meter["last"].to_period("M") if recorded else None
            source = on_roster if listed else known
            rows.append({
                "site_name": name, "customer_code": code,
                "customer_type": source.at[code, "customer_type"] if customer else "",
                "type_source": ("roster" if listed
                                else known.at[code, "source"] if customer else ""),
                "connection_month": (str(on_roster.at[code, "month"]) if listed
                                     else str(first)),
                "first_reading_month": str(first) if recorded else "",
                "last_reading_month": str(last) if recorded else "",
                "status": status,
                "departure_month": str(last + 1) if status == "failed" else "",
            })
    return pd.DataFrame(rows)


def _reference_sites(roster: pd.DataFrame) -> list[str]:
    return [name for name, site in SITES.items()
            if site.meter_file is not None and (roster.site_name == name).any()]


# ------------------------------------------------------------------- the record
def record_customers(status: pd.DataFrame, record: str) -> pd.DataFrame:
    """The customers a record holds: none whose meter never recorded, no non-customer."""
    if record not in RECORDS:
        raise ValueError(f"unknown record {record!r}; choose from {RECORDS}")
    held = status[~status.status.isin(("not_a_customer", "never_recorded"))]
    if record == "roster":
        held = held[held.type_source == "roster"]
    return held


def record_span(roster: pd.DataFrame, record: str, site_name: str) -> tuple[pd.Period,
                                                                           pd.Period]:
    """The origin of a site's village clock and the last month ``T`` of the record."""
    origin = roster.loc[roster.site_name == site_name, "month"].min()
    if record == "roster":
        return origin, last_roster_month(roster)
    return origin, last_complete_month(meter_summary(site_name)[2])


def _age(months: pd.Series, origin: pd.Period) -> np.ndarray:
    """Village age of each month, with an empty month as never."""
    out = np.full(len(months), np.iinfo(np.int64).max, dtype=np.int64)
    for i, month in enumerate(months):
        if month:
            out[i] = (pd.Period(month, freq="M") - origin).n
    return out


def household_stock(customers: pd.DataFrame, origin: pd.Period,
                    last: pd.Period) -> np.ndarray:
    """Households connected in or before each village month ``0..T``, net of departures."""
    households = customers[customers.customer_type.isin(HOUSEHOLD_TYPES)]
    joined = _age(households.connection_month, origin)
    left = _age(households.departure_month, origin)
    span = np.arange((last - origin).n + 1)
    return np.array([(joined <= a).sum() - (left <= a).sum() for a in span], dtype=float)


def _unit(ages: np.ndarray, rate: float, midpoint: float) -> np.ndarray:
    from scipy.special import expit

    return expit(rate * (ages - midpoint))


def _fit(ages: np.ndarray, stock: np.ndarray, plateau: float | None,
         lower: float, upper: float):
    """Least squares of ``K l(a)``, free in ``(K, r, m)`` or at a fixed ``K``.

    Started from a small grid of points and the best kept: with a two-year record the
    surface has flat valleys, and a single start can stop in one.
    """
    from scipy.optimize import least_squares

    span = float(ages[-1])
    best = None
    for rate in (0.05, 0.1, 0.3):
        for midpoint in (span / 3, span / 2, span, 1.5 * span):
            if plateau is None:
                for start in (lower, 0.5 * (lower + upper), upper):
                    result = least_squares(
                        lambda p: p[0] * _unit(ages, p[1], p[2]) - stock,
                        x0=[min(max(start, lower), upper), rate, midpoint],
                        bounds=([lower, RATE_BOUNDS[0], MIDPOINT_BOUNDS[0]],
                                [upper, RATE_BOUNDS[1], MIDPOINT_BOUNDS[1]]),
                        x_scale="jac")
                    if best is None or result.cost < best.cost:
                        best = result
            else:
                result = least_squares(
                    lambda p: plateau * _unit(ages, p[0], p[1]) - stock,
                    x0=[rate, midpoint],
                    bounds=([RATE_BOUNDS[0], MIDPOINT_BOUNDS[0]],
                            [RATE_BOUNDS[1], MIDPOINT_BOUNDS[1]]),
                    x_scale="jac")
                if best is None or result.cost < best.cost:
                    best = result
    return best


def _standard_errors(result, n: int) -> np.ndarray:
    """Standard errors from the Jacobian at the optimum.

    A cumulative series is serially correlated, each month carrying every earlier one, so
    these are optimistic: they treat thirty-odd months as thirty-odd independent draws.
    """
    jac = np.asarray(result.jac, dtype=float)
    p = jac.shape[1]
    sigma2 = 2.0 * float(result.cost) / max(n - p, 1)
    covariance = sigma2 * np.linalg.pinv(jac.T @ jac)
    return np.sqrt(np.clip(np.diag(covariance), 0.0, None))


def fit_site(name: str, stock: np.ndarray, origin: pd.Period, last: pd.Period,
             census: int | None = None) -> tuple[list[dict], dict]:
    """The four plateau variants of one reference village, and what the profile found.

    census replaces the site's census as the plateau's upper bound, for a sensitivity.
    """
    from scipy.stats import f as fisher

    ages = np.arange(stock.size, dtype=float)
    census = int(SITES[name].n_households if census is None else census)
    n = stock.size
    observed = float(stock[-1])

    free = _fit(ages, stock, None, observed, float(census))
    ssr_free = 2.0 * float(free.cost)
    se = _standard_errors(free, n)

    # Profile of the plateau over every whole number of households it could be: no fewer
    # than are connected at the end of the record, no more than the census.
    profile = {}
    for plateau in range(int(observed), census + 1):
        profile[plateau] = 2.0 * float(_fit(ages, stock, float(plateau), 0, 0).cost)
    ssr_min = min(ssr_free, min(profile.values()))
    threshold = ssr_min * (1.0 + fisher.ppf(LEVEL, 1, n - 3) / (n - 3))
    inside = [k for k, ssr in profile.items() if ssr <= threshold] \
        or [min(profile, key=profile.get)]
    interval = (min(inside), max(inside))
    identified = interval[1] < census

    common = {"site_name": name, "census_households": census, "identified": identified,
              "n_months": n, "origin_month": str(origin), "last_month": str(last)}
    out = [{**common, "variant": "estimate",
            "plateau_households": float(free.x[0]),
            "plateau_share": float(free.x[0]) / census,
            "rate_per_month": float(free.x[1]), "midpoint_months": float(free.x[2]),
            "se_plateau": float(se[0]), "se_rate": float(se[1]),
            "se_midpoint": float(se[2])}]
    for variant, plateau in (("profile_lower_bound", interval[0]),
                             ("profile_upper_bound", interval[1]), ("census", census)):
        fixed = _fit(ages, stock, float(plateau), 0, 0)
        se_fixed = _standard_errors(fixed, n)
        out.append({**common, "variant": variant,
                    "plateau_households": float(plateau),
                    "plateau_share": float(plateau) / census,
                    "rate_per_month": float(fixed.x[0]),
                    "midpoint_months": float(fixed.x[1]),
                    "se_plateau": np.nan, "se_rate": float(se_fixed[0]),
                    "se_midpoint": float(se_fixed[1])})
    report = {"site": name, "origin": origin, "last": last, "stock": stock,
              "interval": interval, "ssr_min": ssr_min, "threshold": threshold}
    return out, report


def observed_table(customers: pd.DataFrame, last: pd.Period) -> pd.DataFrame:
    """Customers per site, type, connection month and departure month.

    Households by category and productive users, the two the brownfield state starts
    from. A departure after the record's last month is not part of it and is left out.
    """
    rows = customers[customers.customer_type.isin((*HOUSEHOLD_TYPES, "PUE"))].copy()
    gone = rows.departure_month.map(lambda m: bool(m) and pd.Period(m, freq="M") <= last)
    rows["departure_month"] = rows.departure_month.where(gone, "")
    table = (rows.groupby(["site_name", "customer_type", "connection_month",
                           "departure_month"]).size()
             .rename("customers").reset_index())
    return table.sort_values(["site_name", "connection_month", "customer_type",
                              "departure_month"], ignore_index=True)


def build(record: str = DEFAULT_RECORD) -> tuple[pd.DataFrame, pd.DataFrame,
                                                pd.DataFrame, list[dict]]:
    """The three tables under one record, and the profile of each reference village."""
    roster = load_roster()
    status = meter_status(roster, load_archive_customers())
    customers = record_customers(status, record)
    rows, reports, observed = [], [], []
    for name in _reference_sites(roster):
        origin, last = record_span(roster, record, name)
        held = customers[(customers.site_name == name)
                         & customers.connection_month.map(
                             lambda m: pd.Period(m, freq="M") <= last)]
        fitted, report = fit_site(name, household_stock(held, origin, last), origin, last)
        rows += fitted
        reports.append(report)
        observed.append(observed_table(held, last))
    columns = ["site_name", "variant", "plateau_households", "census_households",
               "plateau_share", "rate_per_month", "midpoint_months", "se_plateau",
               "se_rate", "se_midpoint", "identified", "n_months", "origin_month",
               "last_month"]
    curves = pd.DataFrame(rows)[columns]
    observed = pd.concat(observed, ignore_index=True).sort_values(
        ["site_name", "connection_month", "customer_type", "departure_month"],
        ignore_index=True)
    return curves, observed, status, reports


# ------------------------------------------------------------------- the checks
def _own_trajectory(site_name: str) -> str:
    from .growth import TRAJECTORIES

    return next(t for t, site in TRAJECTORIES.items() if site == site_name)


def active_check(status: pd.DataFrame, roster: pd.DataFrame, record: str,
                 site_name: str, keep_failed: bool = False,
                 last_cohort: bool = False) -> dict:
    """S2-A5: the households the mixture law expects active in month ``T``, and the meters'.

    The stock is the record's households connected before ``T`` began and not gone by
    then, each cohort at its own age in ``T``, under the site's own growth law. Given the
    stock, the number outside the ``inactive`` state is a sum of independent draws, which
    sets the deviation. A household is active on the meters, as in the law, when its
    month's energy is above zero.

    The criterion is read over the households with at least one reading in ``T``
    (``expected_observed``, ``sd_observed``, ``within``): the law was estimated on months
    with readings, so a month without any is not an observation of the inactive state, and
    such a household leaves both sides. That reading was chosen after the result was seen.
    The other, every household of the stock with those without a reading counted inactive
    (``expected``, ``sd``, ``within_counted_inactive``), is kept as a sensitivity.
    ``keep_failed`` keeps the households whose failed meter was not replaced, as
    households that cannot be active; ``last_cohort`` adds the households connected
    during ``T`` itself.
    """
    from .generator import INACTIVE, _redistribute_outliers
    from .growth import maturity_band, trajectory_law

    origin, last = record_span(roster, record, site_name)
    monthly = meter_summary(site_name)[1]
    households = record_customers(status, record)
    households = households[(households.site_name == site_name)
                            & households.customer_type.isin(HOUSEHOLD_TYPES)]
    joined = households.connection_month.map(lambda m: pd.Period(m, freq="M"))
    left = households.departure_month.map(
        lambda m: pd.Period(m, freq="M") if m else last + 1)
    before = households[(joined <= last) if last_cohort else (joined < last)]
    gone = (left[before.index] <= last)
    stock = before if keep_failed else before[~gone]
    law = trajectory_law(_own_trajectory(site_name))
    mean = variance = observed_mean = observed_variance = 0.0
    metered = unobserved = 0
    for row in stock.itertuples():
        age = (last - pd.Period(row.connection_month, freq="M")).n
        weights = law.xs(maturity_band(age), level="maturity")
        weights = _redistribute_outliers(weights.loc[row.customer_type]
                                         if row.customer_type in weights.index
                                         else weights.mean(axis=0))
        p = 1.0 - float(weights.get(INACTIVE, 0.0))
        mean += p
        variance += p * (1.0 - p)
        if gone.get(row.Index, False):
            continue
        # The law was estimated on months with readings, and a month without any is not
        # an observation of the inactive state. Counted apart, so that the comparison can
        # be read either way.
        if (row.customer_code, last) not in monthly.index:
            unobserved += 1
            continue
        observed_mean += p
        observed_variance += p * (1.0 - p)
        metered += int(monthly[(row.customer_code, last)] > 0.0)
    return {"site": site_name, "month": str(last), "households": len(stock),
            "expected": mean, "sd": variance ** 0.5, "metered": metered,
            "kept_failed": int(gone.sum()) if keep_failed else 0,
            "unobserved": unobserved, "expected_observed": observed_mean,
            "sd_observed": observed_variance ** 0.5,
            "within": abs(metered - observed_mean) <= 2.0 * observed_variance ** 0.5,
            "within_counted_inactive": abs(metered - mean) <= 2.0 * variance ** 0.5}


def productive_check(status: pd.DataFrame, roster: pd.DataFrame, record: str,
                     site_name: str) -> dict:
    """S2-A6: productive users expected in month ``T`` against those the meters find active.

    Expected three ways: anchored on the observed state, the productive users connected
    by ``T``, which a village with a plant starts from; and by the rule alone, the
    intensity at the village's band times the connected stock (the base it was estimated
    on) or times the households the law expects active (the generator's reading before).
    """
    from .growth import maturity_band
    from .productive import ProductiveCalibration

    origin, last = record_span(roster, record, site_name)
    monthly = meter_summary(site_name)[1]
    customers = record_customers(status, record)
    customers = customers[(customers.site_name == site_name)
                          & customers.connection_month.map(
                              lambda m: pd.Period(m, freq="M") <= last)]
    gone = customers.departure_month.map(lambda m: bool(m)
                                         and pd.Period(m, freq="M") <= last)
    customers = customers[~gone]
    productive = customers[customers.customer_type == "PUE"]
    metered = sum(monthly.get((code, last), 0.0) > PRODUCTIVE_ACTIVE_KWH
                  for code in productive.customer_code)
    trajectory = _own_trajectory(site_name)
    intensity = float(ProductiveCalibration.load().intensity.loc[
        maturity_band((last - origin).n), trajectory])
    stock = int(customers.customer_type.isin(HOUSEHOLD_TYPES).sum())
    active = active_check(status, roster, record, site_name, last_cohort=True)
    return {"site": site_name, "month": str(last), "trajectory": trajectory,
            "metered": int(metered), "anchored": len(productive),
            "per_connected": intensity * stock, "per_active": intensity * active["expected"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--record", choices=RECORDS, default=DEFAULT_RECORD)
    parser.add_argument("--census", action="append", default=[], metavar="SITE=WORKBOOK",
                        help="the operator's field census of a site, to rebuild "
                             f"{ARCHIVE_CUSTOMERS.name} from; once per reference site")
    parser.add_argument("--as-of", default=None,
                        help="month (YYYY-MM) at which to state each village's age; "
                             "defaults to the current month")
    args = parser.parse_args(argv)

    roster = load_roster()
    kind = lambda t: "HH" if t in HOUSEHOLD_TYPES else t
    if args.census:
        census = {}
        for entry in args.census:
            name, _, path = entry.partition("=")
            census[name], twice = read_census(Path(path), name)
            print(f"{name}: census codes entered twice, first row kept: {twice}")
        unlisted = archive_customers(roster, census)
        unlisted.to_csv(ARCHIVE_CUSTOMERS, index=False)
        print(f"written {ARCHIVE_CUSTOMERS}")
        typed = pd.concat(census.values()).set_index("customer_code").census_type
        listed = roster.assign(census=roster.customer_code.map(typed).fillna("none"))
        agree = float((listed.customer_type == listed.census).mean())
        print(f"Census type against the roster's, {len(listed)} roster customers: "
              f"{1 - agree:.1%} differ")
        print(pd.crosstab(listed.customer_type, listed.census, margins=True).to_string())

    curves, observed, status, reports = build(args.record)
    args.out.mkdir(parents=True, exist_ok=True)
    curves.round(6).to_csv(args.out / CURVES_FILE, index=False)
    observed.to_csv(args.out / OBSERVED_FILE, index=False)
    status.to_csv(args.out / STATUS_FILE, index=False)

    check = classification_check(roster)
    misplaced = float((check.roster != check.rule).mean())
    coarse = float((check.roster.map(kind) != check.rule.map(kind)).mean())
    print(f"\nProfile rule on the roster's {len(check)} metered customers: "
          f"{misplaced:.1%} misplaced, {coarse:.1%} counting the household categories as "
          "one")
    print(pd.crosstab(check.roster, check.rule, margins=True).to_string())
    print(f"\nRecord: {args.record}")
    print("What the profile types could move the stock at T by, at most:")
    print(profile_bound(status, args.record).to_string(index=False))
    as_of = (pd.Period(args.as_of, freq="M") if args.as_of
             else pd.Timestamp.today().to_period("M"))
    for report in reports:
        print(f"{report['site']}: origin {report['origin']}, last month {report['last']} "
              f"(village age {(report['last'] - report['origin']).n}), "
              f"{int(report['stock'][-1])} households connected net of departures; "
              f"village age in {as_of}: {(as_of - report['origin']).n} months")
        print(f"  plateau interval at {LEVEL:.0%}: {report['interval'][0]} to "
              f"{report['interval'][1]} households")
    print(curves.round(4).to_string(index=False))
    print("\nCustomers added from the archive:")
    print(status[status.type_source.isin(("census", "profile"))].to_string(index=False))
    print("\nMeters that failed, never recorded, or are not a customer's:")
    print(status[status.status != "recording"].to_string(index=False))
    for name in _reference_sites(roster):
        failed = status[(status.site_name == name) & (status.status == "failed")]
        last = meter_summary(name)[0].loc[failed.customer_code, "last"]
        print(f"\n{name}: candidate replacements")
        print(candidate_replacements(name, last.to_frame()).to_string(index=False))
    print("\nS2-A5, active households in the record's last month")
    for name in _reference_sites(roster):
        row = active_check(status, roster, args.record, name)
        print(f"  {row['site']} {row['month']}: {row['households']} households, "
              f"{row['unobserved']} without a reading in the month; over the "
              f"{row['households'] - row['unobserved']} observed, expected "
              f"{row['expected_observed']:.1f} +- {row['sd_observed']:.1f}, metered "
              f"{row['metered']}, within two deviations: {row['within']}")
        for keep in (False, True):
            row = active_check(status, roster, args.record, name, keep_failed=keep)
            print(f"    sensitivity, without a reading counted inactive"
                  + (f" and the {row['kept_failed']} failed meters kept" if keep else "")
                  + f": {row['households']} households, expected {row['expected']:.1f} "
                  f"+- {row['sd']:.1f}, within two deviations: "
                  f"{row['within_counted_inactive']}")
    print("\nS2-A6, productive users in the record's last month")
    for name in _reference_sites(roster):
        row = productive_check(status, roster, args.record, name)
        print(f"  {row['site']} {row['month']} ({row['trajectory']}): metered "
              f"{row['metered']}, anchored {row['anchored']}, per connected household "
              f"{row['per_connected']:.1f}, per active household {row['per_active']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
