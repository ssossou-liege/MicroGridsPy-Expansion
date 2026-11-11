r"""Calibrate productive-use archetypes from the meter records and the activity survey.

Writes four tables to ``data/ramp_params/reference/``:

``pue_class_profiles.csv``
    Mean hourly load of one connected enterprise of each class [kW]. Taken from the meters,
    not from an appliance model: the survey's nameplate powers are missing for forty-two
    per cent of the equipment it records, which is precisely the field a bottom-up model
    would rest on.
``pue_class_mix.csv``
    Share of connections belonging to each class, from the observed roster of both sites.
``pue_connection_intensity.csv``
    Enterprises connected per census household, by maturity band and growth trajectory.
    Enterprises cannot be counted in advance --- nobody knows who will start a business ---
    so their number is carried as a trajectory and bracketed by the two reference sites,
    exactly as household growth is.
``pue_own_levels.csv``
    Each productive user the record of a reference village holds, at the level its own
    meter measured: its mean daily energy over its last twelve months of readings, or since
    its connection where that is shorter, and its own factor for each calendar month where
    its readings cover a full year. A village with a plant starts from these users rather
    than from the class profiles, which describe a unit of a class and not the units a
    village has: the class ``milling`` averages one mill of Samionta at 14 kWh a day and two
    of Gbowele below one.

The script is deterministic given its inputs.
"""
from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import DEMAND_DIR, REFERENCE_DIR
from ..sites import SITES
from .maturity import MATURITY_EDGES, MATURITY_LABELS
from .productive import CLASSES, UNSURVEYED, classify

#: Trajectory names and the reference site whose connection behaviour each reproduces,
#: kept consistent with the household growth envelope.
TRAJECTORY_SITE = {"slow": "Samionta", "central": None, "fast": "Gbowele"}

METER_FILES = {"Samionta": "sam_meter_readings.parquet",
               "Gbowele": "gbo_meter_readings.parquet"}

LEVELS_FILE = "pue_own_levels.csv"
#: The months a productive user's own level is measured over, ending at its last month of
#: readings within the record.
LEVEL_MONTHS = 12
#: A month enters a user's own seasonal pattern when its readings cover this share of it;
#: the pattern is kept only when every month of the year does.
MONTH_COVERAGE = 0.5
#: A day enters a user's own day-to-day spread when its readings cover this share of it,
#: and the spread is measured on no fewer days than this; otherwise the class's applies.
DAY_COVERAGE = 0.9
MIN_DAYS = 28
#: Productive users the activity survey did not reach and whose class their record shows,
#: for the hourly shape of their own level only; the class profiles and the mix, which the
#: survey alone types, do not read this. 0097SAM is not in the survey, which lists a maize
#: mill at Samionta under the code "0017" with no site, a code the roster gives to a
#: household. Its mean day is a mill's: almost nothing from 22:00 to 06:00, 62 % of its energy
#: between 07:00 and 18:00, against 71 % for the class ``milling`` and 50 % for
#: ``small_trade``, whose night floor would put 3 of its 15 kWh a day after dark.
RECORD_CLASS = {"0097SAM": "milling"}


def load_survey(path: Path, known_codes: set[str]) -> pd.DataFrame:
    """Activity class of each surveyed enterprise, keyed by customer code.

    Codes are entered by hand and reach the sheet in several shapes --- with the site
    suffix, without it, with an interior space --- so they are normalised against the
    roster rather than trusted as typed.
    """
    sheet = pd.read_excel(path, sheet_name=0)
    column = lambda fragment: next(c for c in sheet.columns if fragment in str(c))
    codes, classes = [], []
    for raw, village, activity in zip(sheet[column("Code client")],
                                      sheet[column("Village")],
                                      sheet[column("Type d")]):
        text = str(raw).strip().replace(" ", "").upper()
        digits = re.sub(r"[^0-9]", "", text)
        suffix = "SAM" if str(village).upper().startswith("SAM") else "GBO"
        for candidate in (text, f"{digits.zfill(4)}{suffix}"):
            if candidate in known_codes:
                codes.append(candidate)
                classes.append(classify(activity))
                break
    frame = pd.DataFrame({"customer_code": codes, "activity_class": classes})
    # A code entered without its site suffix can match the roster twice; keep the first
    # response for each customer rather than letting the ambiguity duplicate a profile.
    return frame.drop_duplicates(subset="customer_code", keep="first")


def enterprise_profiles(months: int = 12) -> pd.DataFrame:
    """Mean hourly load of every connected enterprise [kW], over its recent record."""
    roster = pd.read_parquet(DEMAND_DIR / "customer_info.parquet")
    productive = roster[roster.customer_type == "PUE"]
    rows = []
    for site, meter_file in METER_FILES.items():
        codes = set(productive.loc[productive.site_name == site, "customer_code"])
        if not codes:
            continue
        meters = pd.read_parquet(DEMAND_DIR / meter_file)
        meters = meters[meters.customer_code.isin(codes)].copy()
        meters["ts"] = pd.to_datetime(meters.timestamp)
        recent = meters[meters.ts >= meters.ts.max() - pd.Timedelta(days=30 * months)]
        recent = recent.assign(hour=recent.ts.dt.hour)
        recent = recent.assign(day=recent.ts.dt.floor("D"))
        for code, group in recent.groupby("customer_code"):
            profile = (group.groupby("hour").power_W.mean()
                       .reindex(range(24), fill_value=0.0) / 1000.0)
            # Day-to-day variability, kept so that repeating a mean day does not flatten
            # the peaks a storage sizing is most sensitive to.
            daily = group.groupby("day").power_W.sum() * 0.25 / 1000.0
            spread = float(daily.std() / daily.mean()) if daily.mean() > 0 else 0.0
            rows.append({"customer_code": code, "site": site, "daily_cv": spread,
                         **{h: float(profile[h]) for h in range(24)}})
    return pd.DataFrame(rows).set_index("customer_code")


def connection_intensity() -> pd.DataFrame:
    """Enterprises connected per *connected* household, by maturity band and trajectory.

    Referred to connected households rather than to the census: the census counts the
    community's dwellings, most of which are not yet on the grid, while an enterprise
    appears alongside the connections that already exist. Referred to the census the ratio
    would depend on how far connection has progressed, which is precisely the thing the
    maturity conditioning is meant to carry, and it would not transfer to a site whose
    connection rate differs.
    """
    roster = pd.read_parquet(DEMAND_DIR / "customer_info.parquet")
    roster["month"] = roster.connection_date.dt.to_period("M")
    observed = {}
    for site_name, site in SITES.items():
        rows = roster[roster.site_name == site_name]
        if rows.empty:
            continue
        start = rows.month.min()
        ages = (rows.month - start).apply(lambda p: p.n)
        span = range(int(ages.max()) + 1)
        productive = np.array([(ages[rows.customer_type == "PUE"] <= a).sum()
                               for a in span], dtype=float)
        households = np.array([(ages[rows.customer_type == "HH"] <= a).sum()
                               for a in span], dtype=float)
        # Aggregate over each band rather than averaging monthly ratios: a village's first
        # month may hold one household and one enterprise, and a ratio of one taken from
        # that would dominate any average it entered.
        by_band = []
        for lower, upper, label in zip(MATURITY_EDGES[:-1], MATURITY_EDGES[1:],
                                       MATURITY_LABELS):
            # Bands are half-open on the left: the edges start at -1 so that band "0-3"
            # covers months zero to three. Slicing from the raw edge would index from -1
            # and leave the first band empty.
            start = max(int(lower) + 1, 0)
            stop = min(int(upper) + 1, productive.size)
            enterprises = productive[start:stop].sum()
            dwellings = households[start:stop].sum()
            by_band.append(float(enterprises / dwellings) if dwellings > 0 else np.nan)
        series = pd.Series(by_band, index=list(MATURITY_LABELS)).ffill().bfill()
        observed[site_name] = series

    frame = pd.DataFrame(observed)
    table = pd.DataFrame(index=frame.index)
    for trajectory, site_name in TRAJECTORY_SITE.items():
        table[trajectory] = (frame.mean(axis=1) if site_name is None
                             else frame[site_name])
    table.index.name = "maturity"
    return table


def record_users() -> pd.DataFrame:
    """The productive users of the record the tables hold, with the month of their record's
    end: code, site, connection month and, where they left within the record, departure
    month."""
    from .build_connection_curves import DEFAULT_RECORD, STATUS_FILE, record_customers

    status = pd.read_csv(REFERENCE_DIR / STATUS_FILE, keep_default_na=False)
    curves = pd.read_csv(REFERENCE_DIR / "connection_curves.csv")
    last = curves.groupby("site_name").last_month.first()
    held = record_customers(status, DEFAULT_RECORD)
    held = held[(held.customer_type == "PUE") & held.site_name.isin(last.index)].copy()
    held["record_end"] = held.site_name.map(last)
    held = held[[pd.Period(c, freq="M") <= pd.Period(t, freq="M")
                 for c, t in zip(held.connection_month, held.record_end)]]
    gone = [bool(d) and pd.Period(d, freq="M") <= pd.Period(t, freq="M")
            for d, t in zip(held.departure_month, held.record_end)]
    held["departure_month"] = held.departure_month.where(gone, "")
    return held[["site_name", "customer_code", "connection_month", "departure_month",
                 "record_end"]].reset_index(drop=True)


def own_levels(users: pd.DataFrame, classes: pd.Series,
               last: str | None = None) -> pd.DataFrame:
    """Each user's own level, from the readings up to ``last`` (default: its record's end).

    The level is the mean power over the user's last ``LEVEL_MONTHS`` months of readings up
    to that month, or since its connection where that is shorter, each reading over its own
    period (``build_meter_archive.timed_readings``), as energy per day. Where every one of
    those twelve months is covered at ``MONTH_COVERAGE``, the level is the mean of the
    twelve months, each weighted by its days, and the user keeps a factor per calendar
    month, its month's mean over the year's; otherwise the factors are left empty. Its
    day-to-day spread is measured over the same readings (``_daily_spread``). A user with
    no reading up to ``last`` has no level, and the generator gives it its class's profile.
    """
    from .build_meter_archive import timed_readings

    factors = [f"f{m:02d}" for m in range(1, 13)]
    rows = []
    for site_name, group in users.groupby("site_name", sort=True):
        readings = timed_readings(site_name)
        readings = readings[readings.customer_code.isin(set(group.customer_code))]
        by_code = dict(tuple(readings.groupby("customer_code")))
        for user in group.sort_values("customer_code").itertuples():
            joined = pd.Period(user.connection_month, freq="M")
            until = pd.Period(last if last is not None else user.record_end, freq="M")
            row = {"site_name": site_name, "customer_code": user.customer_code,
                   "activity_class": classes.get(user.customer_code, UNSURVEYED),
                   "connection_month": user.connection_month,
                   "departure_month": user.departure_month,
                   "level_from": "", "level_to": "", "months_read": 0,
                   "kwh_per_day": np.nan, "daily_cv": np.nan,
                   **{f: np.nan for f in factors}}
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
                row.update(level_from=str(start), level_to=str(end),
                           months_read=int(len(months)),
                           kwh_per_day=mean * 24.0 / 1000.0,
                           daily_cv=_daily_spread(window, by_month=full))
            rows.append(row)
    return pd.DataFrame(rows)


def _daily_spread(readings: pd.DataFrame, by_month: bool) -> float:
    """A user's day-to-day spread: the standard deviation of its daily energy over its mean.

    Over the days its readings cover at ``DAY_COVERAGE``, each day's energy taken over the
    mean of its own month where the user keeps a monthly pattern, so that the spread the
    generator draws does not count the seasons twice, and over the mean of the whole window
    otherwise. Empty with fewer than ``MIN_DAYS`` such days, and the class's spread applies.
    """
    day = readings.timestamp.dt.floor("D")
    daily = readings.groupby(day).agg(kwh=("kwh", "sum"), seconds=("seconds", "sum"))
    daily = daily[daily.seconds >= DAY_COVERAGE * 86_400.0]
    if len(daily) < MIN_DAYS:
        return np.nan
    month = daily.index.to_period("M")
    base = (daily.kwh.groupby(month).transform("mean") if by_month
            else pd.Series(daily.kwh.mean(), index=daily.index))
    ratio = (daily.kwh / base)[base > 0]
    return float(ratio.std()) if len(ratio) >= MIN_DAYS else np.nan


def record_classes(survey: Path | None, codes: set[str]) -> tuple[pd.Series, pd.Series]:
    """The class of each code for its own level's shape, and where the class comes from.

    The survey's class where it reaches the code, ``RECORD_CLASS`` where the record shows
    one the survey missed, and ``UNSURVEYED`` otherwise.
    """
    found = (load_survey(survey, codes).set_index("customer_code")["activity_class"]
             if survey is not None else pd.Series(dtype=str))
    classes, sources = {}, {}
    for code in sorted(codes):
        if code in found.index:
            classes[code], sources[code] = found[code], "survey"
        elif code in RECORD_CLASS:
            classes[code], sources[code] = RECORD_CLASS[code], "record"
        else:
            classes[code], sources[code] = UNSURVEYED, "unsurveyed"
    return pd.Series(classes), pd.Series(sources)


def levels_table(survey: Path) -> pd.DataFrame:
    """``pue_own_levels.csv``: the record's productive users at their own levels."""
    users = record_users()
    classes, sources = record_classes(survey, set(users.customer_code))
    table = own_levels(users, classes)
    table.insert(3, "class_source", table.customer_code.map(sources))
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", type=Path, required=True,
                        help="activity survey workbook")
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--months", type=int, default=12,
                        help="length of the meter window used for the profiles")
    args = parser.parse_args(argv)

    profiles = enterprise_profiles(args.months)
    survey = load_survey(args.survey, set(profiles.index))
    labelled = profiles.join(survey.set_index("customer_code")["activity_class"])
    labelled["activity_class"] = labelled["activity_class"].fillna(UNSURVEYED)

    hours = [h for h in range(24)]
    by_class = labelled.groupby("activity_class")[hours].mean()
    by_class = by_class.reindex([c for c in CLASSES if c in by_class.index])
    by_class.index.name = "activity_class"

    # The mix belongs to the trajectory, not to the model. The two reference villages hold
    # populations of enterprises that differ in kind as well as in number: one has few and
    # large — mills, a sawmill, ice makers — the other many and small. Drawing both from a
    # pooled mix reproduces neither, overstating the second by more than twice. Each
    # trajectory therefore carries the mix of the site whose behaviour it reproduces.
    mixes = {}
    for trajectory, site_name in TRAJECTORY_SITE.items():
        rows = labelled if site_name is None else labelled[labelled.site == site_name]
        share = (rows.groupby("activity_class").size() / max(len(rows), 1))
        mixes[trajectory] = share.reindex(by_class.index).fillna(0.0)
    mix = pd.DataFrame(mixes)
    mix = mix / mix.sum(axis=0)
    mix.index.name = "activity_class"

    args.out.mkdir(parents=True, exist_ok=True)
    by_class["daily_cv"] = labelled.groupby("activity_class")["daily_cv"].median().reindex(by_class.index)
    by_class.round(6).to_csv(args.out / "pue_class_profiles.csv")
    mix.round(6).to_csv(args.out / "pue_class_mix.csv")
    connection_intensity().round(6).to_csv(args.out / "pue_connection_intensity.csv")
    levels = levels_table(args.survey)
    levels.round(6).to_csv(args.out / LEVELS_FILE, index=False)

    print(f"{len(labelled)} enterprises profiled, {survey.shape[0]} classified by survey")
    print(f"{len(levels)} productive users of the record at their own levels, "
          f"{int(levels.f01.notna().sum())} with a year of readings; classes by source: "
          f"{levels.class_source.value_counts().to_dict()}")
    report = pd.concat([by_class[hours].sum(axis=1).round(2).rename("kWh_jour"),
                        by_class["daily_cv"].round(2), mix.round(3)], axis=1)
    print(report.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
