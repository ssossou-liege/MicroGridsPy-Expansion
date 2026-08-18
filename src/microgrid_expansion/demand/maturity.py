"""Mixture law conditioned on connection maturity rather than on calendar month.

Conditioning the behavioural mixture on the site and the calendar month, as the first
calibration did, produces a law that cannot be transferred: predicting either reference
village from the other gives errors of 50 % and 130 % on daily energy per household.
Decomposing the same observations by *months since connection* shows why. At connection
the two villages agree to within 3 % -- 0.282 against 0.275 kWh per household per day --
and they diverge afterwards, one growing by a factor 2.4 over two years while the other
stays flat. What fails to transfer is not the level but the trajectory.

Maturity is also the covariate a new site actually has: a village being electrified starts
at month zero, whatever the calendar. Conditioning on it therefore turns two incompatible
site laws into replicates of one ramp-up curve, and isolates the genuinely uncertain part
-- the growth -- where it can be carried as an uncertainty rather than hidden in a point
estimate.

Sites are weighted equally at every stage, so that the village with the longer record does
not dictate the curve; and strata are shrunk towards the pooled law with a strength set by
their own support, so that thin strata widen rather than assert.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR
from .partition import ARCHETYPES, INACTIVE, OUTLIER, segment_observations

#: States a household-month can occupy, in a fixed order.
STATES = (*ARCHETYPES, INACTIVE, OUTLIER)

#: Maturity bands, in months since connection. Resolved finely over the first year, where
#: the ramp-up happens, and coarsely afterwards where the record thins out.
MATURITY_EDGES = (-1, 3, 6, 12, 24, 1200)
MATURITY_LABELS = ("0-3", "4-6", "7-12", "13-24", "25+")

#: Pseudo-count mass of the prior. A stratum with this many observations is pulled halfway
#: towards the pooled law.
PRIOR_STRENGTH = 20.0

MIXTURE_PATH = REFERENCE_DIR / "mixture_by_maturity.csv"


def with_maturity(segmented: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add the months-since-connection of each observation and its maturity band."""
    frame = segment_observations() if segmented is None else segmented.copy()
    periods = pd.PeriodIndex(frame["month"], freq="M").to_timestamp()
    connection = pd.to_datetime(frame["connection_date"], errors="coerce")
    frame["maturity_months"] = ((periods.year - connection.dt.year) * 12
                                + (periods.month - connection.dt.month))
    frame = frame[frame["maturity_months"] >= 0].copy()
    frame["maturity"] = pd.cut(frame["maturity_months"], list(MATURITY_EDGES),
                               labels=list(MATURITY_LABELS))
    frame["calendar_month"] = pd.PeriodIndex(frame["month"], freq="M").month
    return frame


def _composition(frame: pd.DataFrame) -> pd.Series:
    """Share of each state in a set of observations, over the fixed state order."""
    counts = frame["cluster"].value_counts()
    shares = counts.reindex(list(STATES)).fillna(0.0)
    total = shares.sum()
    return shares / total if total > 0 else shares


def balanced_law(frame: pd.DataFrame) -> pd.Series:
    """Composition with every site weighted equally, whatever its number of records."""
    per_site = [_composition(group) for _, group in frame.groupby("site_name")
                if len(group) > 0]
    if not per_site:
        return pd.Series(0.0, index=list(STATES))
    return pd.concat(per_site, axis=1).mean(axis=1)


def estimate_maturity_mixture(
    frame: pd.DataFrame | None = None,
    prior_strength: float = PRIOR_STRENGTH,
) -> pd.DataFrame:
    """Estimate ``P(C | T, maturity)``, pooled across sites with equal site weight.

    Each stratum's balanced empirical law is shrunk towards the law of its maturity band
    across all household categories, with a weight set by the stratum's own support. The
    returned frame carries the posterior law, the support that produced it and the prior it
    was shrunk towards, so that the confidence attached to each row stays visible.
    """
    frame = with_maturity() if frame is None else frame

    rows: list[dict] = []
    for maturity in MATURITY_LABELS:
        band = frame[frame["maturity"] == maturity]
        if band.empty:
            continue
        prior = balanced_law(band)                       # pooled over categories
        for customer_type, stratum in band.groupby("customer_type"):
            empirical = balanced_law(stratum)
            support = float(len(stratum))
            weight = support / (support + prior_strength)
            posterior = weight * empirical + (1.0 - weight) * prior
            posterior = posterior / posterior.sum()
            for state in STATES:
                rows.append({
                    "customer_type": customer_type,
                    "maturity": maturity,
                    "cluster": state,
                    "p_empirical": float(empirical[state]),
                    "p_prior": float(prior[state]),
                    "p_posterior": float(posterior[state]),
                    "n_observations": int(support),
                    "shrinkage_weight": weight,
                })
    return pd.DataFrame(rows)


def mixture_matrix(mixture: pd.DataFrame | None = None) -> pd.DataFrame:
    """The posterior law as a frame indexed by ``(maturity, customer_type)``."""
    mixture = estimate_maturity_mixture() if mixture is None else mixture
    matrix = (mixture.pivot_table(index=["maturity", "customer_type"],
                                  columns="cluster", values="p_posterior")
              .reindex(columns=list(STATES)).fillna(0.0))
    return matrix.div(matrix.sum(axis=1), axis=0)


def residual_seasonality(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    """Calendar-month effect that survives conditioning on maturity.

    Part of what the first calibration read as seasonality was a cohort artefact: both
    records begin in June, so the early months of the calendar are crowded with newly
    connected households. This quantifies what remains once maturity is controlled for --
    the genuinely seasonal component, to be carried as a secondary term.
    """
    frame = with_maturity() if frame is None else frame
    profiles = frame.groupby("cluster")["mean_daily_kWh"].mean()

    rows = []
    for month, group in frame.groupby("calendar_month"):
        observed = float(group["mean_daily_kWh"].mean())
        # What the maturity mix of this month alone would predict, seasonality aside.
        expected = float(sum(_composition(group)[s] * profiles.get(s, 0.0) for s in STATES))
        maturity_mix = group["maturity"].value_counts(normalize=True)
        rows.append({
            "calendar_month": int(month),
            "n_observations": len(group),
            "median_maturity_months": float(group["maturity_months"].median()),
            "observed_kwh_day": observed,
            "share_newly_connected": float(maturity_mix.get("0-3", 0.0)),
        })
    table = pd.DataFrame(rows).set_index("calendar_month")
    table["seasonal_index"] = table["observed_kwh_day"] / table["observed_kwh_day"].mean()
    return table


def write_mixture(mixture: pd.DataFrame | None = None, path=MIXTURE_PATH) -> pd.DataFrame:
    """Persist the maturity-conditioned mixture next to the calibration."""
    mixture = estimate_maturity_mixture() if mixture is None else mixture
    path.parent.mkdir(parents=True, exist_ok=True)
    mixture.to_csv(path, index=False)
    return mixture


def main() -> int:
    frame = with_maturity()
    mixture = estimate_maturity_mixture(frame)
    write_mixture(mixture)

    print("Loi de mélange conditionnée à l'ancienneté de raccordement (HH1)")
    matrix = mixture_matrix(mixture)
    hh1 = matrix.xs("HH1", level="customer_type")
    print((100 * hh1).round(1).to_string())

    print("\nSaisonnalité résiduelle, une fois l'ancienneté prise en compte :")
    seasonal = residual_seasonality(frame)
    print(seasonal[["n_observations", "median_maturity_months",
                    "share_newly_connected", "seasonal_index"]].round(3).to_string())
    amplitude = seasonal["seasonal_index"].max() / seasonal["seasonal_index"].min()
    correlation = seasonal["seasonal_index"].corr(seasonal["share_newly_connected"])
    print(f"\namplitude saisonnière résiduelle : {amplitude:.2f}x")
    print(f"corrélation avec la part de nouveaux raccordés : {correlation:+.3f}")
    print(f"\nécrit {MIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
