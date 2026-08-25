r"""Calibrate productive-use archetypes from the meter records and the activity survey.

Writes three tables to ``data/ramp_params/reference/``:

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

The script is deterministic given its inputs, and ``tests/test_productive_demand.py``
re-runs it and asserts that it reproduces the committed tables.
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
TRAJECTORY_SITE = {"lente": "Samionta", "centrale": None, "rapide": "Gbowele"}

METER_FILES = {"Samionta": "sam_meter_readings.parquet",
               "Gbowele": "gbo_meter_readings.parquet"}


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
    frame = pd.DataFrame({"customer_code": codes, "classe": classes})
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
            rows.append({"customer_code": code, "site": site, "cv_jour": spread,
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
    labelled = profiles.join(survey.set_index("customer_code")["classe"])
    labelled["classe"] = labelled["classe"].fillna(UNSURVEYED)

    hours = [h for h in range(24)]
    by_class = labelled.groupby("classe")[hours].mean()
    by_class = by_class.reindex([c for c in CLASSES if c in by_class.index])
    by_class.index.name = "classe"

    # The mix belongs to the trajectory, not to the model. The two reference villages hold
    # populations of enterprises that differ in kind as well as in number: one has few and
    # large — mills, a sawmill, ice makers — the other many and small. Drawing both from a
    # pooled mix reproduces neither, overstating the second by more than twice. Each
    # trajectory therefore carries the mix of the site whose behaviour it reproduces.
    mixes = {}
    for trajectory, site_name in TRAJECTORY_SITE.items():
        rows = labelled if site_name is None else labelled[labelled.site == site_name]
        share = (rows.groupby("classe").size() / max(len(rows), 1))
        mixes[trajectory] = share.reindex(by_class.index).fillna(0.0)
    mix = pd.DataFrame(mixes)
    mix = mix / mix.sum(axis=0)
    mix.index.name = "classe"

    args.out.mkdir(parents=True, exist_ok=True)
    by_class["cv_jour"] = labelled.groupby("classe")["cv_jour"].median().reindex(by_class.index)
    by_class.round(6).to_csv(args.out / "pue_class_profiles.csv")
    mix.round(6).to_csv(args.out / "pue_class_mix.csv")
    connection_intensity().round(6).to_csv(args.out / "pue_connection_intensity.csv")

    print(f"{len(labelled)} enterprises profiled, {survey.shape[0]} classified by survey")
    report = pd.concat([by_class[hours].sum(axis=1).round(2).rename("kWh_jour"),
                        by_class["cv_jour"].round(2), mix.round(3)], axis=1)
    print(report.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
