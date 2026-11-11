r"""Each customer a village's record holds, at the level its own meter measured.

Writes ``data/ramp_params/reference/own_levels.csv``: one row per household, productive
user and place of worship of the record of a reference village, with

* where its hourly shape comes from: a household's archetype, a productive user's activity
  class, the class ``place_of_worship``, and the source of each;
* its connection and departure months;
* its mean daily energy over its last twelve months of readings up to the record's last
  month, or since its connection where that is shorter, each reading over its own period;
* its own factor for each calendar month where its readings cover a year;
* its own day-to-day spread, and the highest hourly power its meter recorded over the same
  months, which bounds what a busy day draws.

A village with a plant starts from these customers rather than from the model's laws, which
describe a unit of a class or a household of a band and not the customers a village has:
the class ``milling`` averaged one mill of Samionta at 14 kWh a day and two units of
Gbowele below one, and the mixture law drew Samionta's households 58 % above their meters
and Gbowele's 33 % below over the record's last year. The model's laws then decide only what
changes after the record: the customers who connect after it, and, for a household, how its
level grows from its age at the record's end.

Offline: the generation reads the table, not this module::

    python -m microgrid_expansion.demand.build_own_levels --survey <activity survey workbook>
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR
from ..sites import HOUSEHOLD_TYPES

LEVELS_FILE = "own_levels.csv"
#: The record's customer types drawn at their own levels.
KINDS = (*HOUSEHOLD_TYPES, "PUE", "CHU")
#: The community class each community type of the record draws the shape of.
COMMUNITY_CLASS = {"CHU": "place_of_worship"}
#: The months a customer's own level is measured over, ending at its last month of readings
#: within the record.
LEVEL_MONTHS = 12
#: A month enters a customer's own seasonal pattern when its readings cover this share of
#: it; the pattern is kept only when every month of the year does.
MONTH_COVERAGE = 0.5
#: A day enters a customer's own day-to-day spread when its readings cover between these
#: shares of it, and the spread is measured on no fewer days than ``MIN_DAYS``. A day
#: covered more than once over holds a catch-up reading, which carries the energy of the
#: day before the gap as well as its own: about ten days a year per meter, and they
#: doubled the spread of a user that draws on few days (a tailor of Samionta, 3.6 with them
#: and 1.7 without).
DAY_COVERAGE = 0.9
DAY_EXCESS = 1.1
MIN_DAYS = 28

_FACTORS = tuple(f"f{m:02d}" for m in range(1, 13))


def record_users(kinds=KINDS) -> pd.DataFrame:
    """The customers of the record the tables hold, of the given types, with the month of
    their record's end: code, site, type, connection month and, where they left within the
    record, departure month."""
    from .build_connection_curves import DEFAULT_RECORD, STATUS_FILE, record_customers

    status = pd.read_csv(REFERENCE_DIR / STATUS_FILE, keep_default_na=False)
    curves = pd.read_csv(REFERENCE_DIR / "connection_curves.csv")
    last = curves.groupby("site_name").last_month.first()
    held = record_customers(status, DEFAULT_RECORD)
    held = held[held.customer_type.isin(kinds) & held.site_name.isin(last.index)].copy()
    held["record_end"] = held.site_name.map(last)
    held = held[[pd.Period(c, freq="M") <= pd.Period(t, freq="M")
                 for c, t in zip(held.connection_month, held.record_end)]]
    gone = [bool(d) and pd.Period(d, freq="M") <= pd.Period(t, freq="M")
            for d, t in zip(held.departure_month, held.record_end)]
    held["departure_month"] = held.departure_month.where(gone, "")
    return held[["site_name", "customer_code", "customer_type", "connection_month",
                 "departure_month", "record_end"]].reset_index(drop=True)


def own_levels(users: pd.DataFrame, shapes: pd.Series | None = None,
               last: str | None = None) -> pd.DataFrame:
    """Each customer's own level, from the readings up to ``last`` (default: its record's end).

    The level is the mean power over the customer's last ``LEVEL_MONTHS`` months of readings
    up to that month, or since its connection where that is shorter, each reading over its
    own period (``readings.timed_readings``), as energy per day. Where every one of those
    twelve months is covered at ``MONTH_COVERAGE``, the level is the mean of the twelve
    months, each weighted by its days, and the customer keeps a factor per calendar month,
    its month's mean over the year's; otherwise the factors are left empty. Its day-to-day
    spread is measured over the same readings (``daily_spread``), and its peak is the highest
    hourly mean of its readings over them, each clock hour's readings averaged as the
    comparison with the meters averages them. A customer with no reading up to ``last`` has
    no level, and the generator draws it from the model's laws.

    ``shapes`` gives each code its shape; a code it does not name is left empty there.
    """
    from .readings import timed_readings

    shapes = pd.Series(dtype=str) if shapes is None else shapes
    kinds = (users.customer_type if "customer_type" in users.columns
             else pd.Series("PUE", index=users.index))
    rows = []
    for site_name, group in users.assign(customer_type=kinds).groupby("site_name", sort=True):
        readings = timed_readings(site_name)
        readings = readings[readings.customer_code.isin(set(group.customer_code))]
        by_code = dict(tuple(readings.groupby("customer_code")))
        for user in group.sort_values("customer_code").itertuples():
            joined = pd.Period(user.connection_month, freq="M")
            until = pd.Period(last if last is not None else user.record_end, freq="M")
            row = {"site_name": site_name, "customer_code": user.customer_code,
                   "customer_type": user.customer_type,
                   "shape": shapes.get(user.customer_code, ""),
                   "connection_month": user.connection_month,
                   "departure_month": user.departure_month,
                   "level_from": "", "level_to": "", "months_read": 0,
                   "kwh_per_day": np.nan, "daily_cv": np.nan, "peak_kw": np.nan,
                   **{f: np.nan for f in _FACTORS}}
            own = by_code.get(user.customer_code)
            own = (own[(own.month >= joined) & (own.month <= until)]
                   if own is not None else None)
            if own is not None and not own.empty:
                end = own.month.max()
                start = max(end - (LEVEL_MONTHS - 1), joined)
                window = own[own.month >= start]
                months = window.groupby("month").agg(seconds=("seconds", "sum"),
                                                     kwh=("kwh", "sum"))
                months["watts"] = months.kwh * 3.6e6 / months.seconds
                span = pd.period_range(start, end, freq="M")
                days = pd.Series([p.days_in_month for p in span], index=span)
                covered = (months.seconds.reindex(span, fill_value=0.0)
                           / (days * 86_400.0))
                full = len(span) == LEVEL_MONTHS and bool((covered >= MONTH_COVERAGE).all())
                if full:
                    watts = months.watts.reindex(span)
                    mean = float((watts * days).sum() / days.sum())
                    for period, w in watts.items():
                        row[f"f{period.month:02d}"] = w / mean if mean > 0 else 1.0
                else:
                    mean = float(window.kwh.sum() * 3.6e6 / window.seconds.sum())
                hourly = window.groupby(window.timestamp.dt.floor("h")).power_W.mean()
                row.update(level_from=str(start), level_to=str(end),
                           months_read=int(len(months)),
                           kwh_per_day=mean * 24.0 / 1000.0,
                           daily_cv=daily_spread(window, by_month=full),
                           peak_kw=float(hourly.max()) / 1000.0)
            rows.append(row)
    return pd.DataFrame(rows)


def daily_spread(readings: pd.DataFrame, by_month: bool) -> float:
    """A customer's day-to-day spread: the standard deviation of its daily energy over its
    mean.

    Over the days its readings cover at ``DAY_COVERAGE`` to ``DAY_EXCESS``, each day's
    energy taken over the mean of its own month where the customer keeps a monthly
    pattern, so that the spread the generator draws does not count the seasons twice, and
    over the mean of all those days otherwise. Empty with fewer than ``MIN_DAYS`` such days.
    """
    day = readings.timestamp.dt.floor("D")
    daily = readings.groupby(day).agg(kwh=("kwh", "sum"), seconds=("seconds", "sum"))
    daily = daily[(daily.seconds >= DAY_COVERAGE * 86_400.0)
                  & (daily.seconds <= DAY_EXCESS * 86_400.0)]
    if len(daily) < MIN_DAYS:
        return np.nan
    month = daily.index.to_period("M")
    base = (daily.kwh.groupby(month).transform("mean") if by_month
            else pd.Series(daily.kwh.mean(), index=daily.index))
    ratio = (daily.kwh / base)[base > 0]
    return float(ratio.std()) if len(ratio) >= MIN_DAYS else np.nan


def household_archetypes(users: pd.DataFrame, levels: pd.DataFrame
                         ) -> tuple[pd.Series, pd.Series]:
    """Each household's archetype, whose measured hourly shape it draws, and its source.

    The record's households are segmented as the operative partition segments the
    register's (``partition``): each month's energy, peak and load factor, every reading
    over its own period, assigned to the nearest of the four reference profiles. The
    record holds households the register does not, so the segmentation is run on the
    record's own. A household's archetype is the one most of its months within its level's
    window are assigned to (``window``), else most of its months on the record
    (``record``); a household none of whose months is an archetype's takes the commonest
    archetype of the record's households (``commonest``). Ties go to the lowest label.
    """
    from .build_mixture_probabilities import assign_clusters_from_reference_profiles
    from .build_monthly_household_clusters import compute_monthly_features
    from .partition import ARCHETYPES, OUTLIER_MAD_THRESHOLD, WINSOR_LOWER, WINSOR_UPPER
    from .readings import timed_readings

    households = users[users.customer_type.isin(HOUSEHOLD_TYPES)]
    frames = []
    for site_name, group in households.groupby("site_name", sort=True):
        readings = timed_readings(site_name)
        end = pd.Period(group.record_end.iloc[0], freq="M")
        readings = readings[readings.customer_code.isin(set(group.customer_code))
                            & (readings.month <= end)]
        frames.append(readings.drop(columns=["month", "kwh"]).assign(site_name=site_name))
    customers = households.assign(
        connection_date=pd.to_datetime(households.connection_month))[
        ["customer_code", "customer_type", "site_name", "connection_date"]]
    monthly = compute_monthly_features(pd.concat(frames, ignore_index=True), customers)
    labelled = assign_clusters_from_reference_profiles(
        monthly, winsor_lower_quantile=WINSOR_LOWER, winsor_upper_quantile=WINSOR_UPPER,
        outlier_mad_threshold=OUTLIER_MAD_THRESHOLD)
    labelled["cluster"] = labelled["cluster"].astype(str)
    labelled = labelled[labelled.cluster.isin(ARCHETYPES)]
    commonest = str(labelled.cluster.value_counts().sort_index()
                    .sort_values(ascending=False, kind="stable").index[0])

    def mode(labels: pd.Series) -> str | None:
        if labels.empty:
            return None
        counts = labels.value_counts().sort_index()
        return str(counts.sort_values(ascending=False, kind="stable").index[0])

    window = levels.set_index("customer_code")
    archetype, source = {}, {}
    for code, own in labelled.groupby("customer_code"):
        months = pd.PeriodIndex(own.month, freq="M")
        start, end = window.at[code, "level_from"], window.at[code, "level_to"]
        inside = own[(months >= pd.Period(start, freq="M")) & (months <= pd.Period(end, freq="M"))] \
            if start else own.iloc[0:0]
        found = mode(inside.cluster)
        archetype[code], source[code] = (found, "window") if found else (mode(own.cluster),
                                                                         "record")
    for code in households.customer_code:
        if code not in archetype:
            archetype[code], source[code] = commonest, "commonest"
    return pd.Series(archetype), pd.Series(source)


def levels_table(survey: Path | None) -> pd.DataFrame:
    """``own_levels.csv``: the record's customers at their own levels.

    A productive user's class is the activity survey's, or its record's where the survey
    missed it (``build_productive_profiles.record_classes``). A household without a spread
    of its own, too few days of its readings being covered, takes the median spread of the
    record's households of its archetype at both villages (``cv_source`` says which); a
    productive user or a place of worship without one is left empty, and draws its class's.
    """
    from .build_productive_profiles import record_classes

    users = record_users()
    productive = set(users.customer_code[users.customer_type == "PUE"])
    classes, class_sources = record_classes(survey, productive)
    table = own_levels(users)
    archetypes, archetype_sources = household_archetypes(users, table)
    community = users.set_index("customer_code").customer_type.map(COMMUNITY_CLASS).dropna()
    shape = pd.concat([classes, archetypes, community])
    source = pd.concat([class_sources, archetype_sources,
                        pd.Series("type", index=community.index)])
    table["shape"] = table.customer_code.map(shape)
    table.insert(4, "shape_source", table.customer_code.map(source))
    return filled_spreads(table).sort_values(["site_name", "customer_code"],
                                             ignore_index=True)


def filled_spreads(table: pd.DataFrame) -> pd.DataFrame:
    """The table with a household's missing spread taken from its archetype, and a column
    ``cv_source`` saying where each spread comes from.

    A household with a level and no spread of its own takes the median spread of the
    table's households of its archetype that have one (``archetype``); a productive user or
    a place of worship without one is left empty and draws its class's (``class``).
    """
    table = table.copy()
    if "cv_source" in table.columns:
        table = table.drop(columns="cv_source")
    table.insert(table.columns.get_loc("daily_cv") + 1, "cv_source",
                 np.where(table.daily_cv.notna(), "own", "class"))
    household = table.customer_type.isin(HOUSEHOLD_TYPES)
    medians = table[household & table.daily_cv.notna()].groupby("shape").daily_cv.median()
    fill = household & table.daily_cv.isna() & table.kwh_per_day.notna()
    table.loc[fill, "daily_cv"] = table.loc[fill, "shape"].map(medians)
    table.loc[fill, "cv_source"] = "archetype"
    table.loc[household & table.kwh_per_day.isna(), "cv_source"] = ""
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--survey", type=Path, required=True,
                        help="activity survey workbook, for the productive users' classes")
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    args = parser.parse_args(argv)

    table = levels_table(args.survey)
    args.out.mkdir(parents=True, exist_ok=True)
    table.round(6).to_csv(args.out / LEVELS_FILE, index=False)
    summary = table.assign(year=table.f01.notna()).groupby(["site_name", "customer_type"]).agg(
        customers=("customer_code", "size"), with_a_year=("year", "sum"),
        kwh_per_day=("kwh_per_day", "sum"))
    print(f"{len(table)} customers of the record at their own levels")
    print(summary.round(2).to_string())
    print("shapes by source:", table.shape_source.value_counts().to_dict())
    print("spreads by source:", table.cv_source.value_counts().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
