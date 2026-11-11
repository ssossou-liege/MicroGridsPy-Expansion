r"""Calibrate productive-use archetypes from the meter records and the activity survey.

Writes three tables to ``data/ramp_params/reference/``:

``pue_class_profiles.csv``
    Mean hourly load of one connected enterprise of each class [kW]. Taken from the meters,
    not from an appliance model: the survey's nameplate powers are missing for forty-two
    per cent of the equipment it records, which is precisely the field a bottom-up model
    would rest on. Each reading counts over its own period (``readings.timed_readings``).
``pue_class_mix.csv``
    Share of connections belonging to each class, from the observed roster of both sites.
``pue_connection_intensity.csv``
    Enterprises connected per census household, by maturity band and growth trajectory.
    Enterprises cannot be counted in advance --- nobody knows who will start a business ---
    so their number is carried as a trajectory and bracketed by the two reference sites,
    exactly as household growth is.

An enterprise's class is the activity survey's, or its record's where the survey missed it
(``RECORD_CLASS``). The productive users a village's record holds are drawn at their own
levels, which ``build_own_levels`` writes from the classes given here.

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

#: Productive users the activity survey did not reach and whose class their record shows.
#: 0097SAM is not in the survey, which lists a maize mill at Samionta under the code "0017"
#: with no site, a code the roster gives to a household. Its mean day is a mill's: almost
#: nothing from 22:00 to 06:00 and 62 % of its energy between 07:00 and 18:00, against 71 %
#: for the class ``milling`` and 50 % for ``small_trade``, whose night floor would put 3 of
#: its 15 kWh a day after dark. The class tables read it as the survey's own (section 5.3 of
#: the specification, session 4 quinquies): typed a small trader, it lifted that class from
#: 0.50 kWh a day to 0.82 and left Samionta's mix one mill in fourteen where it has two.
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
    """Mean hourly load of every connected enterprise [kW], over its recent record.

    Each reading counts over its own period (``readings.timed_readings``): the enterprise's
    daily energy is its mean power over the time its readings cover, times a day, and its
    hourly profile, the mean of its readings by hour of day, is scaled to that energy. A
    reading after a gap in communication carries the gap's mean power, which a quarter-hour
    apiece dropped; the mean of the readings by hour is a mean of mean powers, which the
    period does not bias, so it gives the shape. The day-to-day spread is taken over the days
    the readings cover once (``build_own_levels.daily_spread``), where a quarter-hour apiece
    read a day of outages as a quiet day.
    """
    from .build_own_levels import daily_spread
    from .readings import timed_readings

    roster = pd.read_parquet(DEMAND_DIR / "customer_info.parquet")
    productive = roster[roster.customer_type == "PUE"]
    rows = []
    for site in METER_FILES:
        codes = set(productive.loc[productive.site_name == site, "customer_code"])
        if not codes:
            continue
        meters = timed_readings(site)
        meters = meters[meters.customer_code.isin(codes)]
        recent = meters[meters.timestamp
                        >= meters.timestamp.max() - pd.Timedelta(days=30 * months)]
        recent = recent.assign(hour=recent.timestamp.dt.hour)
        for code, group in recent.groupby("customer_code"):
            profile = (group.groupby("hour").power_W.mean()
                       .reindex(range(24), fill_value=0.0) / 1000.0)
            kwh_per_day = float(group.kwh.sum() / group.seconds.sum() * 86_400.0)
            total = float(profile.sum())
            if total > 0:
                profile = profile * (kwh_per_day / total)
            # Day-to-day variability, kept so that repeating a mean day does not flatten
            # the peaks a storage sizing is most sensitive to.
            spread = daily_spread(group, by_month=False)
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


def record_classes(survey: Path | None, codes: set[str]) -> tuple[pd.Series, pd.Series]:
    """The class of each code, and where the class comes from.

    The survey's class where it reaches the code, ``RECORD_CLASS`` where the record shows
    one the survey missed, and ``UNSURVEYED`` otherwise. The class tables and the own levels
    read the same classes.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", type=Path, required=True,
                        help="activity survey workbook")
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--months", type=int, default=12,
                        help="length of the meter window used for the profiles")
    args = parser.parse_args(argv)

    profiles = enterprise_profiles(args.months)
    classes, sources = record_classes(args.survey, set(profiles.index))
    labelled = profiles.join(classes.rename("activity_class"))
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

    print(f"{len(labelled)} enterprises profiled; classes by source: "
          f"{sources.value_counts().to_dict()}")
    report = pd.concat([by_class[hours].sum(axis=1).round(2).rename("kWh_jour"),
                        by_class["daily_cv"].round(2), mix.round(3)], axis=1)
    print(report.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
