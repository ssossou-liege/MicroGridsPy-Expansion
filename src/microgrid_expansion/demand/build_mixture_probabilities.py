#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import build_monthly_household_clusters as clustering
from ..paths import DEMAND_DIR, REFERENCE_DIR

# Fixed reference cluster profiles (C0..C3) from RAMP calibration.
REFERENCE_CLUSTER_FEATURES = {
    "0": {"median_energy_kwh_day": 0.20, "median_peak_power_w": 21.5, "load_factor_median": 0.37},
    "1": {"median_energy_kwh_day": 0.15, "median_peak_power_w": 18.6, "load_factor_median": 0.36},
    "2": {"median_energy_kwh_day": 0.50, "median_peak_power_w": 53.6, "load_factor_median": 0.45},
    "3": {"median_energy_kwh_day": 0.23, "median_peak_power_w": 22.1, "load_factor_median": 0.44},
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build monthly household-type mixture probabilities P(C=c|T=t,m) "
            "from clustered observations."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEMAND_DIR,
        help="Directory with meter readings and household_customers.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REFERENCE_DIR,
        help="Directory where output CSV files are written.",
    )
    parser.add_argument("--n-clusters", type=int, default=4)
    parser.add_argument("--winsor-lower-quantile", type=float, default=0.01)
    parser.add_argument("--winsor-upper-quantile", type=float, default=0.99)
    parser.add_argument("--outlier-mad-threshold", type=float, default=4.5)
    parser.add_argument(
        "--prior-strength",
        type=float,
        default=15.0,
        help=(
            "Base pseudo-count mass for hierarchical empirical Bayes smoothing. "
            "Higher values increase shrinkage toward the global balanced base."
        ),
    )
    parser.add_argument(
        "--support-reference",
        type=float,
        default=20.0,
        help=(
            "Support level controlling adaptive shrinkage. Smaller type-month-site "
            "sample sizes produce smaller effective prior mass and wider intervals."
        ),
    )
    parser.add_argument(
        "--n-draws",
        type=int,
        default=2000,
        help="Number of Dirichlet draws for posterior interval estimates.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for posterior draw reproducibility.",
    )
    return parser.parse_args()


def posterior_intervals(
    posterior_alpha: np.ndarray,
    n_draws: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    draws = rng.dirichlet(posterior_alpha, size=n_draws)
    p05 = np.quantile(draws, 0.05, axis=0)
    p50 = np.quantile(draws, 0.50, axis=0)
    p95 = np.quantile(draws, 0.95, axis=0)
    return p05, p50, p95


def assign_clusters_from_reference_profiles(
    monthly: pd.DataFrame,
    winsor_lower_quantile: float,
    winsor_upper_quantile: float,
    outlier_mad_threshold: float,
) -> pd.DataFrame:
    clustered, winsorized_values, robust_values = clustering.prepare_feature_matrix(
        monthly,
        winsor_lower_quantile=winsor_lower_quantile,
        winsor_upper_quantile=winsor_upper_quantile,
        outlier_mad_threshold=outlier_mad_threshold,
    )

    clustered["cluster"] = "outlier"
    clustered.loc[clustered["is_inactive"], "cluster"] = "inactive"

    inlier_mask = (~clustered["is_outlier"].to_numpy()) & (~clustered["is_inactive"].to_numpy())
    if inlier_mask.any():
        _, winsor_median, winsor_iqr = clustering.robust_scale(winsorized_values)

        reference_clusters = list(REFERENCE_CLUSTER_FEATURES.keys())
        reference_raw = np.array(
            [
                [
                    REFERENCE_CLUSTER_FEATURES[c]["median_energy_kwh_day"],
                    REFERENCE_CLUSTER_FEATURES[c]["median_peak_power_w"],
                    REFERENCE_CLUSTER_FEATURES[c]["load_factor_median"],
                ]
                for c in reference_clusters
            ],
            dtype=float,
        )

        reference_transformed = np.column_stack(
            [
                np.log1p(reference_raw[:, 0]),
                np.log1p(reference_raw[:, 1]),
                reference_raw[:, 2],
            ]
        )

        # Apply the same winsorization and robust scaling used for observations.
        lower_bounds = np.quantile(winsorized_values, winsor_lower_quantile, axis=0)
        upper_bounds = np.quantile(winsorized_values, winsor_upper_quantile, axis=0)
        reference_winsorized = np.clip(reference_transformed, lower_bounds, upper_bounds)
        reference_robust = (reference_winsorized - winsor_median) / winsor_iqr

        distances = ((robust_values[inlier_mask, None, :] - reference_robust[None, :, :]) ** 2).sum(axis=2)
        nearest_indices = distances.argmin(axis=1)
        labels = np.array(reference_clusters, dtype=object)[nearest_indices]
        clustered.loc[inlier_mask, "cluster"] = labels

    return clustered.sort_values(["site_name", "month", "cluster"])


def build_probability_table(
    clustered: pd.DataFrame,
    prior_strength: float,
    support_reference: float,
    n_draws: int,
    seed: int,
) -> pd.DataFrame:
    work = clustered[["site_name", "month", "customer_type", "cluster", "customer_code"]].copy()
    work["cluster"] = work["cluster"].astype(str)

    clusters = sorted(work["cluster"].unique(), key=lambda x: (x not in {"inactive", "outlier"}, x))

    counts = (
        work.groupby(["site_name", "month", "customer_type", "cluster"], as_index=False, observed=True)
        .agg(n_obs=("customer_code", "nunique"))
    )

    observed_site_type_month = (
        work.groupby(["site_name", "month", "customer_type"], as_index=False, observed=True)["customer_code"]
        .nunique()
        .rename(columns={"customer_code": "n_total_type_month_site"})
    )
    template = observed_site_type_month[["site_name", "month", "customer_type"]].merge(
        pd.DataFrame({"cluster": clusters}),
        how="cross",
    )
    counts = template.merge(counts, on=["site_name", "month", "customer_type", "cluster"], how="left")
    counts["n_obs"] = counts["n_obs"].fillna(0).astype(int)
    counts["n_total_type_month_site"] = counts.groupby(["site_name", "month", "customer_type"])["n_obs"].transform("sum")
    counts["p_empirical"] = np.where(
        counts["n_total_type_month_site"] > 0,
        counts["n_obs"] / counts["n_total_type_month_site"],
        0.0,
    )

    # Site-specific empirical distributions P(C|T,m,s).
    site_empirical = counts[
        ["site_name", "month", "customer_type", "cluster", "n_obs", "n_total_type_month_site", "p_empirical"]
    ].copy()

    # Balanced global base across sites for each (T,m): each site has equal weight.
    phi_tm = (
        site_empirical.groupby(["month", "customer_type", "cluster"], as_index=False)["p_empirical"]
        .mean()
        .rename(columns={"p_empirical": "phi_balanced_tm_cluster"})
    )

    # Fallback base by household type if a specific month is sparse.
    phi_type = (
        site_empirical.groupby(["customer_type", "cluster"], as_index=False)["p_empirical"]
        .mean()
        .rename(columns={"p_empirical": "phi_balanced_type_cluster"})
    )

    counts = counts.merge(
        phi_tm,
        on=["month", "customer_type", "cluster"],
        how="left",
    )
    counts = counts.merge(
        phi_type,
        on=["customer_type", "cluster"],
        how="left",
    )

    counts["phi_balanced_tm_cluster"] = counts["phi_balanced_tm_cluster"].fillna(counts["phi_balanced_type_cluster"])
    counts["phi_balanced_tm_cluster"] = counts["phi_balanced_tm_cluster"].fillna(1.0 / len(clusters))

    # Adaptive shrinkage: weaker prior mass for low-support type-month-site cells.
    counts["support_weight"] = counts["n_total_type_month_site"] / (
        counts["n_total_type_month_site"] + support_reference
    )
    counts["kappa_effective"] = prior_strength * counts["support_weight"]
    counts["prior_alpha"] = counts["kappa_effective"] * counts["phi_balanced_tm_cluster"]
    counts["posterior_alpha"] = counts["n_obs"] + counts["prior_alpha"]

    rng = np.random.default_rng(seed)
    interval_rows: list[dict[str, float | str]] = []

    for (site_name, month, customer_type), group in counts.groupby(["site_name", "month", "customer_type"], sort=True):
        posterior_alpha = group["posterior_alpha"].to_numpy(dtype=float)
        posterior_sum = posterior_alpha.sum()
        p_shrunk = posterior_alpha / posterior_sum
        p05, p50, p95 = posterior_intervals(posterior_alpha, n_draws=n_draws, rng=rng)
        interval_width = p95 - p05

        for i, (_, row) in enumerate(group.iterrows()):
            interval_rows.append(
                {
                    "site_name": site_name,
                    "month": month,
                    "customer_type": customer_type,
                    "cluster": row["cluster"],
                    "n_obs": int(row["n_obs"]),
                    "n_total_type_month_site": int(row["n_total_type_month_site"]),
                    "p_empirical": float(row["p_empirical"]),
                    "p_shrunk": float(p_shrunk[i]),
                    "p05": float(p05[i]),
                    "p50": float(p50[i]),
                    "p95": float(p95[i]),
                    "uncertainty_width": float(interval_width[i]),
                    "phi_balanced_tm_cluster": float(row["phi_balanced_tm_cluster"]),
                    "kappa_effective": float(row["kappa_effective"]),
                    "support_weight": float(row["support_weight"]),
                    "prior_alpha": float(row["prior_alpha"]),
                    "posterior_alpha": float(row["posterior_alpha"]),
                }
            )

    out = pd.DataFrame(interval_rows).sort_values(["site_name", "month", "customer_type", "cluster"])
    return out


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    customers = clustering.load_census(args.data_dir / "household_customers.csv")
    readings = clustering.load_meter_readings(args.data_dir, customers)
    monthly = clustering.compute_monthly_features(readings, customers)
    clustered = assign_clusters_from_reference_profiles(
        monthly,
        winsor_lower_quantile=args.winsor_lower_quantile,
        winsor_upper_quantile=args.winsor_upper_quantile,
        outlier_mad_threshold=args.outlier_mad_threshold,
    )

    prob_table = build_probability_table(
        clustered,
        prior_strength=args.prior_strength,
        support_reference=args.support_reference,
        n_draws=args.n_draws,
        seed=args.seed,
    )

    output_path = args.output_dir / "mixture_probabilities_type_month.csv"
    prob_table.to_csv(output_path, index=False)
    print("Mixture probabilities written to", output_path)


if __name__ == "__main__":
    main()
