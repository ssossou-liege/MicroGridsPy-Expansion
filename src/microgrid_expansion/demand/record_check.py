r"""Set a village's brownfield year against its own meters: criterion S4ter-A1.

A village with a plant starts from its record: the households, the productive users and
the places of worship on its grid, month by month, up to the record's last month ``T``,
each at the level its own meter measured. This module builds the brownfield demand at the
village ages of the record's last twelve months, as the certified year of a brownfield run
builds it, under the village's own growth trajectory, and sets it against what the meters
billed over those months, in total and by category: households, productive users by
class, and the community buildings.

The meters are read from the archive with each reading over its own period
(``readings.timed_readings``). A customer's category is its type in the record
(``meter_status.csv``): households of every category, productive users by the class their
own level is drawn on (``own_levels.csv``), places of worship and the school. The model
is read off ``DemandYear.parts``, the billed load by who draws it, before any distribution
loss, which no meter sees. Several seeds are drawn and averaged: the criterion is about
what the model expects, not about one draw.

S4ter-A1 holds when the billed energy over the twelve months lies within ``TOLERANCE`` of
the meters at both villages, in total, for the households and for the productive users.
The held-out version takes every customer's level from the record up to ``HELD_OUT_LAST``
and sets the months after it against the meters: a customer connected after it is drawn from
the model's laws, a household through the mixture law of its cohort and a productive user
on its class's mean day. It is reported, and nothing is tuned on it.

Two tables are reported beside it, for the author: the households' energy per connected
household by village age and by the household's own age (decision 9 of the specification),
and each productive class's profile against the levels of its own units.

Offline: nothing the generation runs imports it::

    python -m microgrid_expansion.demand.record_check --seeds 4
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR
from ..sites import HOUSEHOLD_TYPES

REFERENCE_SITES = ("Samionta", "Gbowele")
#: The relative gap S4ter-A1 accepts, in total and for each of the two groups it names.
TOLERANCE = 0.10
#: The criterion's two groups, and the prefix of the categories each sums.
GROUPS = {"households": ("households",), "productive": ("productive:",)}
#: The last month the held-out levels are taken from.
HELD_OUT_LAST = "2026-04"
#: Seeds the model's expectation is averaged over, by default: a pool's size.
SEEDS = 4
#: Bands of age, in months, for the households' energy per connected household. The
#: generator's bands stop at 25 months; the last two split what lies beyond.
AGE_BANDS = ((0, 3), (4, 6), (7, 12), (13, 24), (25, 36), (37, None))

_COMMUNITY = {"CHU": "community:place_of_worship", "SCH": "community:school"}


def record_months(site_name: str, last: str | None = None,
                  count: int = 12) -> pd.PeriodIndex:
    """The ``count`` months of a site's record ending at ``last`` (default: its ``T``)."""
    from .connection import curve_row

    end = pd.Period(last or str(curve_row(site_name, "estimate").last_month), freq="M")
    return pd.period_range(end - (count - 1), end, freq="M")


def categories(site_name: str) -> pd.Series:
    """Each customer code's category in the comparison, from the record's types."""
    status = pd.read_csv(REFERENCE_DIR / "meter_status.csv", keep_default_na=False)
    status = status[status.site_name == site_name]
    levels = pd.read_csv(REFERENCE_DIR / "own_levels.csv", dtype={"shape": str})
    klass = levels[levels.customer_type == "PUE"].set_index("customer_code")["shape"]
    out = {}
    for row in status.itertuples():
        if row.customer_type in HOUSEHOLD_TYPES:
            out[row.customer_code] = "households"
        elif row.customer_type == "PUE":
            out[row.customer_code] = f"productive:{klass.get(row.customer_code, 'small_trade')}"
        elif row.customer_type in _COMMUNITY:
            out[row.customer_code] = _COMMUNITY[row.customer_type]
    return pd.Series(out, dtype=str)


def metered(site_name: str, months: pd.PeriodIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    """What the meters billed, month by month and by category: energy [kWh] and peak [kW].

    The peak is that of the category's hourly load, each code's readings averaged over the
    hour, which is the resolution the model draws at.
    """
    from .readings import timed_readings

    kinds = categories(site_name)
    readings = timed_readings(site_name)
    readings = readings[readings.customer_code.isin(kinds.index)
                        & readings.month.isin(months)].copy()
    readings["category"] = readings.customer_code.map(kinds)
    energy = (readings.groupby(["month", "category"]).kwh.sum().unstack(fill_value=0.0)
              .reindex(months, fill_value=0.0))
    readings["hour"] = readings.timestamp.dt.floor("h")
    hourly = readings.groupby(["hour", "customer_code"]).power_W.mean().reset_index()
    hourly["category"] = hourly.customer_code.map(kinds)
    load = hourly.groupby(["hour", "category"]).power_W.sum().unstack(fill_value=0.0) / 1e3
    load["total"] = load.sum(axis=1)
    peak = load.groupby(load.index.to_period("M")).max().reindex(months)
    energy["total"] = energy.sum(axis=1)
    return energy, peak


def _brownfield_schedule(site, observed=None):
    """The schedule ``certify --brownfield`` draws its year on, from ``observed`` if given."""
    from ..settings import default_settings, reference_plant
    from .connection import ConnectionSchedule, load_curves, own_curves, plan

    settings = default_settings()
    settings.installed = reference_plant(site.name)
    choice = settings.connection
    if observed is None:
        return plan(site, settings, brownfield=True).schedule(choice.trajectory)
    curves = (own_curves(site.name) if choice.brownfield_bracket == "own"
              else load_curves(settings))
    return ConnectionSchedule.brownfield(site, observed, curves[choice.trajectory])


def simulated(site_name: str, months: pd.PeriodIndex, seeds: int = SEEDS,
              trajectory: str | None = None, observed=None
              ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The brownfield demand at the village ages of ``months``, by category.

    Each calendar year the months span is drawn at the village age of its January, as
    ``certify --brownfield`` draws its year, with the site's own scaling, the shipped
    connection trajectory and, unless ``trajectory`` says otherwise, the village's own
    growth; ``observed`` replaces the record the schedule starts from. Returns the energy
    and the peak averaged over the seeds, and the energy of each seed.
    """
    from ..sites import get_site
    from . import archetypes
    from .connection import observed_state
    from .generator import simulate_demand_year

    from .growth import own_trajectory

    trajectory = trajectory or own_trajectory(site_name) or "central"
    site = get_site(site_name)
    record = observed_state(site_name) if observed is None else observed
    schedule = _brownfield_schedule(site, observed)
    rows = []
    for seed in range(int(seeds)):
        for year in sorted({m.year for m in months}):
            drawn = simulate_demand_year(site, year=year, seed=seed,
                                         maturity_months=record.age_in(f"{year}-01"),
                                         trajectory=trajectory,
                                         scaling=archetypes.scaling_for(site_name),
                                         connection=schedule)
            index = pd.date_range(f"{year}-01-01", periods=drawn.hourly_kw.size, freq="h")
            month_of = index.to_period("M")
            total = sum(drawn.parts.values())
            for month in (m for m in months if m.year == year):
                hours = month_of == month
                row = {"seed": seed, "month": month}
                for name, series in (*drawn.parts.items(), ("total", total)):
                    row[f"kwh|{name}"] = float(series[hours].sum())
                    row[f"peak|{name}"] = float(series[hours].max())
                rows.append(row)
    frame = pd.DataFrame(rows).fillna(0.0)
    mean = frame.drop(columns="seed").groupby("month").mean().reindex(months)
    split = lambda kind: mean[[c for c in mean if c.startswith(kind)]].rename(
        columns=lambda c: c.split("|", 1)[1])
    by_seed = frame.pivot_table(index="seed", values="kwh|total", aggfunc="sum")
    return split("kwh|"), split("peak|"), by_seed


def grouped(energy: pd.DataFrame) -> pd.Series:
    """The twelve months' energy in total, for each group of the criterion, and by
    category."""
    sums = energy.sum()
    out = {"total": float(sums.get("total", 0.0))}
    for group, prefixes in GROUPS.items():
        out[group] = float(sum(v for k, v in sums.items()
                               if any(k.startswith(p) for p in prefixes)))
    for k, v in sums.items():
        if k != "total":
            out[k] = float(v)
    return pd.Series(out)


def held_out_state(site_name: str, last: str = HELD_OUT_LAST, min_days: float | None = None):
    """The record with every customer's level taken from the readings up to ``last``.

    The shapes are the shipped table's; a customer connected after ``last`` has no level and
    is drawn from the model's laws, as is one whose readings up to ``last`` cover fewer than
    ``min_days`` days (default ``build_own_levels.MIN_LEVEL_DAYS``; zero is the check before
    that rule, which was found through this check).
    """
    from .build_own_levels import MIN_LEVEL_DAYS, filled_spreads, own_levels, record_users
    from .connection import observed_state
    from .connection import record_users as as_users

    observed = observed_state(site_name)
    users = record_users()
    users = users[users.site_name == site_name]
    shipped = pd.read_csv(REFERENCE_DIR / "own_levels.csv", dtype={"shape": str})
    shapes = shipped.set_index("customer_code")["shape"]
    days = MIN_LEVEL_DAYS if min_days is None else float(min_days)
    table = filled_spreads(own_levels(users, shapes, last=last, min_days=days)).fillna("")
    origin = observed.origin_month
    return replace(observed,
                   productive_users=as_users(table, origin, ("PUE",)),
                   household_users=as_users(table, origin, tuple(HOUSEHOLD_TYPES)),
                   community_users=as_users(table, origin, ("CHU",)))


def check(site_name: str, seeds: int = SEEDS, trajectory: str | None = None,
          held_out: bool = False, min_days: float | None = None) -> dict:
    """S4ter-A1 at one village, or its held-out version, whose levels need ``min_days``
    days of readings (``held_out_state``)."""
    if held_out:
        months = pd.period_range(pd.Period(HELD_OUT_LAST, freq="M") + 1,
                                 record_months(site_name)[-1], freq="M")
        observed = held_out_state(site_name, min_days=min_days)
    else:
        months, observed = record_months(site_name), None
    meter_energy, meter_peak = metered(site_name, months)
    model_energy, model_peak, by_seed = simulated(site_name, months, seeds, trajectory,
                                                  observed)
    from .growth import own_trajectory

    trajectory = trajectory or own_trajectory(site_name) or "central"
    meters, model = grouped(meter_energy), grouped(model_energy)
    gaps = {k: (model.get(k, 0.0) / meters[k] - 1.0) if meters.get(k, 0.0) > 0 else None
            for k in ("total", *GROUPS)}
    return {
        "site": site_name, "months": [str(months[0]), str(months[-1])],
        "held_out": held_out, "seeds": int(seeds), "trajectory": trajectory,
        "meters_kwh": meters.round(1).to_dict(), "model_kwh": model.round(1).to_dict(),
        "gap": {k: (None if v is None else round(v, 4)) for k, v in gaps.items()},
        "within": all(v is not None and abs(v) <= TOLERANCE for v in gaps.values()),
        "model_total_by_seed_kwh": by_seed["kwh|total"].round(1).tolist(),
        "monthly": pd.DataFrame({
            "meters_kwh": meter_energy["total"], "model_kwh": model_energy["total"],
            "meters_peak_kw": meter_peak["total"], "model_peak_kw": model_peak["total"],
            "meters_households_kwh": meter_energy.get("households", 0.0),
            "model_households_kwh": model_energy.get("households", 0.0),
            "meters_productive_kwh": meter_energy[[c for c in meter_energy
                                                   if c.startswith("productive:")]].sum(axis=1),
            "model_productive_kwh": model_energy[[c for c in model_energy
                                                  if c.startswith("productive:")]].sum(axis=1),
        }).round(1).rename(index=str).to_dict(orient="index"),
        "peak_by_category_kw": {
            "meters": meter_peak.max().round(2).to_dict(),
            "model": model_peak.max().round(2).to_dict()},
    }


def _band(age: int) -> str:
    for low, high in AGE_BANDS:
        if age >= low and (high is None or age <= high):
            return f"{low}-{high}" if high is not None else f"{low}+"
    raise ValueError(age)


def household_energy_by_age(site_name: str) -> dict[str, pd.DataFrame]:
    """Energy per connected household [kWh/day], over the whole record, by band of age.

    Two clocks: the village's age in the month, and the household's own, months since its
    connection. Every household on the grid in a month counts, a month without a reading
    counting as none; the share of household-months with a reading is given beside it.
    """
    from .connection import curve_row
    from .readings import timed_readings

    row = curve_row(site_name, "estimate")
    origin, last = pd.Period(row.origin_month, freq="M"), pd.Period(row.last_month, freq="M")
    status = pd.read_csv(REFERENCE_DIR / "meter_status.csv", keep_default_na=False)
    held = status[(status.site_name == site_name)
                  & status.customer_type.isin(HOUSEHOLD_TYPES)
                  & status.status.isin(("recording", "failed"))]
    readings = timed_readings(site_name)
    energy = (readings[readings.customer_code.isin(held.customer_code)]
              .groupby(["customer_code", "month"]).kwh.sum())
    months = []
    for household in held.itertuples():
        joined = pd.Period(household.connection_month, freq="M")
        left = (pd.Period(household.departure_month, freq="M")
                if household.departure_month else last + 1)
        for month in pd.period_range(joined, min(left - 1, last), freq="M"):
            read = (household.customer_code, month) in energy.index
            months.append({"village": _band((month - origin).n),
                           "own": _band((month - joined).n),
                           "kwh_per_day": (energy[(household.customer_code, month)]
                                           if read else 0.0) / month.days_in_month,
                           "read": read})
    frame = pd.DataFrame(months)
    order = [_band(low) for low, _ in AGE_BANDS]
    return {clock: frame.groupby(clock).agg(household_months=("read", "size"),
                                            kwh_per_day=("kwh_per_day", "mean"),
                                            share_read=("read", "mean")).reindex(order)
                                       .dropna(how="all")
            for clock in ("village", "own")}


def class_levels() -> pd.DataFrame:
    """Each productive class's profile [kWh/day] against its units' own levels, by village."""
    from .productive import ProductiveCalibration

    profiles = ProductiveCalibration.load().profiles
    per_day = profiles[[h for h in range(24) if h in profiles.columns]].sum(axis=1)
    levels = pd.read_csv(REFERENCE_DIR / "own_levels.csv", dtype={"shape": str})
    levels = levels[levels.customer_type == "PUE"].rename(columns={"shape": "activity_class"})
    table = levels.groupby(["activity_class", "site_name"]).agg(
        units=("customer_code", "size"), mean_kwh_per_day=("kwh_per_day", "mean"),
        median_kwh_per_day=("kwh_per_day", "median"))
    table["profile_kwh_per_day"] = [float(per_day.get(k, np.nan)) for k, _ in table.index]
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", action="append", choices=REFERENCE_SITES, default=None)
    parser.add_argument("--seeds", type=int, default=SEEDS)
    parser.add_argument("--trajectory", default="own",
                        choices=["slow", "central", "fast", "own"],
                        help="growth trajectory of the households; 'own', the default, is "
                             "each village's own law, slow at Samionta and fast at Gbowele, "
                             "which a brownfield run follows")
    parser.add_argument("--held-out", action="store_true")
    parser.add_argument("--min-days", type=float, default=None,
                        help="held out: the days of readings a level needs, by default "
                             "the shipped rule's 28; 0 is the check before the rule")
    parser.add_argument("--out", type=Path, default=None, help="a JSON of the results")
    args = parser.parse_args(argv)

    from .growth import own_trajectory

    results = []
    for site in args.site or REFERENCE_SITES:
        trajectory = own_trajectory(site) if args.trajectory == "own" else args.trajectory
        result = check(site, args.seeds, trajectory, args.held_out, args.min_days)
        results.append(result)
        print(f"\n{site}, {result['months'][0]} to {result['months'][1]}"
              f"{' (held out)' if args.held_out else ''}, growth {trajectory}, "
              f"{args.seeds} seeds: within {TOLERANCE:.0%}: {result['within']}")
        both = pd.DataFrame({"meters_kwh": result["meters_kwh"],
                             "model_kwh": result["model_kwh"]}).fillna(0.0)
        both["gap"] = both.model_kwh / both.meters_kwh.where(both.meters_kwh > 0) - 1.0
        print(both.round(3).to_string())
        print(pd.DataFrame(result["monthly"]).T.to_string())
    if not args.held_out:
        for site in args.site or REFERENCE_SITES:
            for clock, table in household_energy_by_age(site).items():
                print(f"\n{site}: energy per connected household by {clock} age [kWh/day]")
                print(table.round(3).to_string())
        print("\nProductive classes: profile against their units' own levels [kWh/day]")
        print(class_levels().round(2).to_string())
    print(f"\nS4ter-A1{' held out' if args.held_out else ''}: "
          f"{all(r['within'] for r in results)}")
    if args.out is not None:
        args.out.write_text(json.dumps(results, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
