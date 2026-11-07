r"""Fit how the reference villages' households joined the grid, and record who joined when.

Writes two tables to ``data/ramp_params/reference/``:

``connection_curves.csv``
    A logistic curve of the connected household stock at each reference village, under
    three plateau variants: the least-squares ``estimate``, the ``profile_lower_bound`` (the
    smallest plateau the record does not reject at 95 %) and the ``census`` (every
    household connected in the end). For the two fixed-plateau variants the rate and the
    midpoint are refitted at that plateau.
``connection_observed.csv``
    Households connected per site, category and connection month: the observed state a
    village with a plant and a record starts its plan from.

The fit is made on the *connected stock*, the households of the roster connected in or
before each month, and not on the households active in a month. The mixture law already
carries the connected households that consume nothing (its ``inactive`` state), so a
plateau fitted on active households and passed through that law would take those months
out twice.

The village clock starts at the site's earliest connection over every customer type, which
is the origin ``build_productive_profiles.connection_intensity`` takes, so the connection
curve and the productive-use intensity run on one clock.

Deterministic given its inputs; ``tests/test_progressive_connection.py`` re-runs it and
asserts that it reproduces the committed tables.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import DEMAND_DIR, REFERENCE_DIR
from ..sites import SITES

CURVES_FILE = "connection_curves.csv"
OBSERVED_FILE = "connection_observed.csv"

#: Confidence level of the plateau's profile interval.
LEVEL = 0.95

#: Bounds of the search, wide enough never to bind on these records: a rate between one
#: household in ten thousand a month and a step, a midpoint ten years either side.
RATE_BOUNDS = (1e-4, 5.0)
MIDPOINT_BOUNDS = (-120.0, 240.0)


def load_roster() -> pd.DataFrame:
    """The operator's customer roster, with each connection's calendar month."""
    roster = pd.read_parquet(DEMAND_DIR / "customer_info.parquet")
    roster["month"] = roster.connection_date.dt.to_period("M")
    return roster


def last_roster_month(roster: pd.DataFrame) -> pd.Period:
    """The last month the roster covers.

    The roster is one extract for both villages, so its last month is that of its latest
    connection, wherever it is. A village that connected nobody in that month still has it
    observed, as a month with no connection.
    """
    return roster.connection_date.max().to_period("M")


def household_stock(rows: pd.DataFrame, origin: pd.Period, last: pd.Period) -> np.ndarray:
    """Households connected in or before each village month ``0..T``."""
    ages = (rows.loc[rows.customer_type == "HH", "month"] - origin).apply(lambda p: p.n)
    span = np.arange((last - origin).n + 1)
    return np.array([(ages <= a).sum() for a in span], dtype=float)


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


def fit_site(name: str, roster: pd.DataFrame, last: pd.Period) -> tuple[list[dict], dict]:
    """The three plateau variants of one reference village, and what the profile found."""
    from scipy.stats import f as fisher

    rows = roster[roster.site_name == name]
    origin = rows.month.min()
    stock = household_stock(rows, origin, last)
    ages = np.arange(stock.size, dtype=float)
    census = int(SITES[name].n_households)
    n = stock.size
    observed = float(stock[-1])

    free = _fit(ages, stock, None, observed, float(census))
    ssr_free = 2.0 * float(free.cost)
    se = _standard_errors(free, n)

    # Profile of the plateau over every whole number of households it could be: no fewer
    # than are already connected, no more than the census.
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
    for variant, plateau in (("profile_lower_bound", interval[0]), ("census", census)):
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


def observed_table(roster: pd.DataFrame) -> pd.DataFrame:
    """Households connected per site, category and connection month.

    The category of each household comes from the household register, the roster carrying
    only that it is a household.
    """
    register = pd.read_csv(DEMAND_DIR / "household_customers.csv")
    households = roster[roster.customer_type == "HH"].merge(
        register[["customer_code", "customer_type"]].rename(
            columns={"customer_type": "category"}),
        on="customer_code", how="left")
    missing = households.category.isna().sum()
    if missing:
        raise ValueError(f"{missing} households of the roster have no category in the "
                         "household register")
    table = (households.groupby(["site_name", "category", "month"]).size()
             .rename("households").reset_index()
             .rename(columns={"category": "customer_type", "month": "connection_month"}))
    table["connection_month"] = table.connection_month.astype(str)
    return table.sort_values(["site_name", "connection_month", "customer_type"],
                             ignore_index=True)


def build() -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Both tables, and the profile of each reference village for the report."""
    roster = load_roster()
    last = last_roster_month(roster)
    rows, reports = [], []
    for name, site in SITES.items():
        if site.meter_file is None or not (roster.site_name == name).any():
            continue
        fitted, report = fit_site(name, roster, last)
        rows += fitted
        reports.append(report)
    columns = ["site_name", "variant", "plateau_households", "census_households",
               "plateau_share", "rate_per_month", "midpoint_months", "se_plateau",
               "se_rate", "se_midpoint", "identified", "n_months", "origin_month",
               "last_month"]
    curves = pd.DataFrame(rows)[columns]
    return curves, observed_table(roster), reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    parser.add_argument("--as-of", default=None,
                        help="month (YYYY-MM) at which to state each village's age; "
                             "defaults to the current month")
    args = parser.parse_args(argv)

    curves, observed, reports = build()
    args.out.mkdir(parents=True, exist_ok=True)
    curves.round(6).to_csv(args.out / CURVES_FILE, index=False)
    observed.to_csv(args.out / OBSERVED_FILE, index=False)

    as_of = (pd.Period(args.as_of, freq="M") if args.as_of
             else pd.Timestamp.today().to_period("M"))
    for report in reports:
        print(f"{report['site']}: origin {report['origin']}, last month {report['last']} "
              f"(village age {(report['last'] - report['origin']).n}), "
              f"{int(report['stock'][-1])} households connected; village age in {as_of}: "
              f"{(as_of - report['origin']).n} months")
        print(f"  plateau interval at {LEVEL:.0%}: {report['interval'][0]} to "
              f"{report['interval'][1]} households")
    print(curves.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
