#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import DEMAND_DIR, REFERENCE_DIR


SITE_FILES = {
    "Gbowele": "gbo_meter_readings.parquet",
    "Samionta": "sam_meter_readings.parquet",
}

CENSUS_TOTALS = {
    "Gbowele": {"HH1": 143, "HH2": 5, "HH3": 11},
    "Samionta": {"HH1": 231, "HH2": 0, "HH3": 0},
}

HOUSEHOLD_TYPES = ["HH1", "HH2", "HH3"]
INTERVAL_HOURS = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build monthly household features and DBSCAN cluster summaries for "
            "Gbowele and Samionta."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEMAND_DIR,
        help="Directory containing parquet readings and household_customers.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REFERENCE_DIR,
        help="Directory where CSV outputs will be written.",
    )
    parser.add_argument(
        "--n-clusters",
        type=int,
        default=4,
        help="Fixed number of global clusters shared across all months and both sites.",
    )
    parser.add_argument(
        "--winsor-lower-quantile",
        type=float,
        default=0.01,
        help="Lower quantile used to cap extreme feature values before clustering.",
    )
    parser.add_argument(
        "--winsor-upper-quantile",
        type=float,
        default=0.99,
        help="Upper quantile used to cap extreme feature values before clustering.",
    )
    parser.add_argument(
        "--outlier-mad-threshold",
        type=float,
        default=4.5,
        help=(
            "Threshold on the maximum absolute robust z-score used to label a monthly "
            "observation as an outlier before K-means. Must match the value used by "
            "build_mixture_probabilities.py, since the two segmentations have to agree."
        ),
    )
    return parser.parse_args()


def infer_last_full_month(max_timestamp: pd.Timestamp) -> pd.Period:
    current_month = max_timestamp.to_period("M")
    month_start = current_month.to_timestamp()
    next_month_start = (current_month + 1).to_timestamp()
    expected_last_timestamp = next_month_start - pd.Timedelta(minutes=15)
    if max_timestamp >= expected_last_timestamp:
        return current_month
    if month_start == max_timestamp.normalize().replace(day=1):
        return current_month - 1
    return current_month - 1


def load_census(customers_path: Path) -> pd.DataFrame:
    customers = pd.read_csv(customers_path)
    customers = customers.loc[
        customers["site_name"].isin(SITE_FILES) & customers["customer_type"].isin(HOUSEHOLD_TYPES),
        ["customer_code", "customer_type", "site_name", "connection_date"],
    ].copy()
    customers["connection_date"] = pd.to_datetime(customers["connection_date"], errors="coerce")
    return customers.drop_duplicates(subset=["customer_code"])


def load_meter_readings(data_dir: Path, customers: pd.DataFrame) -> pd.DataFrame:
    customer_codes_by_site = customers.groupby("site_name")["customer_code"].apply(set).to_dict()
    frames = []

    for site_name, file_name in SITE_FILES.items():
        path = data_dir / file_name
        site_readings = pd.read_parquet(path, columns=["timestamp", "customer_code", "power_W"])
        site_readings = site_readings[site_readings["customer_code"].isin(customer_codes_by_site.get(site_name, set()))].copy()
        site_readings["site_name"] = site_name
        site_readings["timestamp"] = pd.to_datetime(site_readings["timestamp"])

        last_full_month = infer_last_full_month(site_readings["timestamp"].max())
        site_readings = site_readings[site_readings["timestamp"].dt.to_period("M") <= last_full_month].copy()
        frames.append(site_readings)

    if not frames:
        return pd.DataFrame(columns=["timestamp", "customer_code", "power_W", "site_name"])

    return pd.concat(frames, ignore_index=True)


def compute_monthly_features(readings: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    readings = readings.copy()
    readings["energy_kWh"] = readings["power_W"] * INTERVAL_HOURS / 1000.0
    readings["month"] = readings["timestamp"].dt.to_period("M")
    readings["date"] = readings["timestamp"].dt.normalize()

    monthly = (
        readings.groupby(["site_name", "customer_code", "month"], as_index=False)
        .agg(
            total_kWh=("energy_kWh", "sum"),
            peak_power=("power_W", "max"),
            mean_power=("power_W", "mean"),
            observed_days=("date", "nunique"),
            reading_count=("power_W", "size"),
        )
    )

    monthly["mean_daily_kWh"] = monthly["total_kWh"] / monthly["observed_days"]
    monthly["load_factor"] = np.where(
        monthly["peak_power"] > 0,
        monthly["mean_power"] / monthly["peak_power"],
        0.0,
    )

    monthly = monthly.merge(
        customers[["customer_code", "customer_type", "site_name", "connection_date"]],
        on=["customer_code", "site_name"],
        how="left",
    )
    monthly["month"] = monthly["month"].astype(str)
    return monthly[
        [
            "site_name",
            "month",
            "customer_code",
            "customer_type",
            "mean_daily_kWh",
            "peak_power",
            "load_factor",
            "total_kWh",
            "observed_days",
            "reading_count",
            "connection_date",
        ]
    ].sort_values(["site_name", "month", "customer_code"])


def zscore_features(values: np.ndarray) -> np.ndarray:
    mean = values.mean(axis=0)
    std = values.std(axis=0)
    std[std == 0] = 1.0
    return (values - mean) / std


def winsorize_values(
    values: np.ndarray,
    lower_quantile: float,
    upper_quantile: float,
) -> np.ndarray:
    lower_bounds = np.quantile(values, lower_quantile, axis=0)
    upper_bounds = np.quantile(values, upper_quantile, axis=0)
    return np.clip(values, lower_bounds, upper_bounds)


def robust_scale(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    median = np.median(values, axis=0)
    q1 = np.quantile(values, 0.25, axis=0)
    q3 = np.quantile(values, 0.75, axis=0)
    iqr = q3 - q1
    iqr[iqr == 0] = 1.0
    return (values - median) / iqr, median, iqr


def flag_outliers(robust_values: np.ndarray, threshold: float) -> np.ndarray:
    if len(robust_values) == 0:
        return np.array([], dtype=bool)
    return np.max(np.abs(robust_values), axis=1) > threshold


def prepare_feature_matrix(
    monthly_features: pd.DataFrame,
    winsor_lower_quantile: float,
    winsor_upper_quantile: float,
    outlier_mad_threshold: float,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    prepared = monthly_features.copy()
    prepared["is_inactive"] = (prepared["total_kWh"] <= 0) | (
        (prepared["mean_daily_kWh"] <= 0) & (prepared["peak_power"] <= 0)
    )
    prepared["feature_mean_daily_kWh"] = np.log1p(prepared["mean_daily_kWh"])
    prepared["feature_peak_power"] = np.log1p(prepared["peak_power"])
    prepared["feature_load_factor"] = prepared["load_factor"]

    feature_columns = [
        "feature_mean_daily_kWh",
        "feature_peak_power",
        "feature_load_factor",
    ]
    transformed_values = prepared[feature_columns].to_numpy(dtype=float)
    winsorized_values = winsorize_values(
        transformed_values,
        lower_quantile=winsor_lower_quantile,
        upper_quantile=winsor_upper_quantile,
    )
    robust_values, _, _ = robust_scale(winsorized_values)
    outlier_mask = flag_outliers(robust_values, threshold=outlier_mad_threshold)
    outlier_mask = outlier_mask & (~prepared["is_inactive"].to_numpy())
    prepared["is_outlier"] = outlier_mask
    return prepared, winsorized_values, robust_values


def run_kmeans(values: np.ndarray, n_clusters: int, max_iter: int = 100) -> tuple[np.ndarray, np.ndarray]:
    n_points = len(values)
    if n_points == 0:
        return np.array([], dtype=int), np.empty((0, values.shape[1] if values.ndim == 2 else 0))

    effective_clusters = min(n_clusters, n_points)
    initial_indices = np.linspace(0, n_points - 1, effective_clusters, dtype=int)
    centroids = values[initial_indices].copy()
    labels = np.zeros(n_points, dtype=int)

    for _ in range(max_iter):
        distances = ((values[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new_labels = distances.argmin(axis=1)
        if np.array_equal(labels, new_labels):
            break
        labels = new_labels

        new_centroids = centroids.copy()
        for cluster_id in range(effective_clusters):
            members = values[labels == cluster_id]
            if len(members) > 0:
                new_centroids[cluster_id] = members.mean(axis=0)
        centroids = new_centroids

    return labels, centroids


def assign_clusters(
    monthly_features: pd.DataFrame,
    n_clusters: int,
    winsor_lower_quantile: float,
    winsor_upper_quantile: float,
    outlier_mad_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    clustered, _, robust_values = prepare_feature_matrix(
        monthly_features,
        winsor_lower_quantile=winsor_lower_quantile,
        winsor_upper_quantile=winsor_upper_quantile,
        outlier_mad_threshold=outlier_mad_threshold,
    )
    clustered["cluster"] = "outlier"
    clustered.loc[clustered["is_inactive"], "cluster"] = "inactive"

    inlier_mask = (~clustered["is_outlier"].to_numpy()) & (~clustered["is_inactive"].to_numpy())
    inlier_values = robust_values[inlier_mask]
    if len(inlier_values) > 0:
        labels, centroids = run_kmeans(inlier_values, n_clusters=n_clusters)
        clustered.loc[inlier_mask, "cluster"] = labels.astype(str)
    else:
        centroids = np.empty((0, robust_values.shape[1]))

    centroid_profiles = pd.DataFrame(
        centroids,
        columns=["robust_mean_daily_kWh", "robust_peak_power", "robust_load_factor"],
    )
    centroid_profiles.insert(0, "cluster", np.arange(len(centroid_profiles)).astype(str))
    centroid_profiles["n_members"] = centroid_profiles["cluster"].map(clustered[clustered["cluster"].isin(centroid_profiles["cluster"])]["cluster"].value_counts()).fillna(0).astype(int)

    raw_centroids = (
        clustered[clustered["cluster"].isin([str(i) for i in range(len(centroids))])]
        .groupby("cluster", as_index=False)[["mean_daily_kWh", "peak_power", "load_factor"]]
        .mean()
        .rename(
            columns={
                "mean_daily_kWh": "cluster_mean_daily_kWh",
                "peak_power": "cluster_mean_peak_power",
                "load_factor": "cluster_mean_load_factor",
            }
        )
    )
    centroid_profiles = centroid_profiles.merge(raw_centroids, on="cluster", how="left")

    if (clustered["cluster"] == "outlier").any():
        outlier_profile = pd.DataFrame(
            {
                "cluster": ["outlier"],
                "robust_mean_daily_kWh": [np.nan],
                "robust_peak_power": [np.nan],
                "robust_load_factor": [np.nan],
                "n_members": [int((clustered["cluster"] == "outlier").sum())],
                "cluster_mean_daily_kWh": [clustered.loc[clustered["cluster"] == "outlier", "mean_daily_kWh"].mean()],
                "cluster_mean_peak_power": [clustered.loc[clustered["cluster"] == "outlier", "peak_power"].mean()],
                "cluster_mean_load_factor": [clustered.loc[clustered["cluster"] == "outlier", "load_factor"].mean()],
            }
        )
        centroid_profiles = pd.concat([centroid_profiles, outlier_profile], ignore_index=True)

    return clustered.sort_values(["site_name", "month", "cluster"]), centroid_profiles.sort_values("cluster")


def share_of_census(count: int, site_name: str, customer_type: str) -> float:
    total = CENSUS_TOTALS[site_name][customer_type]
    if total == 0:
        return 0.0
    return 100.0 * count / total


def monthly_connected_totals(customers: pd.DataFrame, site_name: str, months: pd.Index) -> pd.DataFrame:
    site_customers = customers[customers["site_name"] == site_name].copy()
    if site_customers.empty:
        return pd.DataFrame(columns=["month", *HOUSEHOLD_TYPES])

    site_customers["connection_month"] = site_customers["connection_date"].dt.to_period("M")
    rows = []
    for month in months:
        connected = site_customers[site_customers["connection_month"] <= month]
        row = {"month": str(month)}
        for customer_type in HOUSEHOLD_TYPES:
            row[customer_type] = int((connected["customer_type"] == customer_type).sum())
        rows.append(row)

    return pd.DataFrame(rows)


def build_cluster_summary(clustered: pd.DataFrame, customers: pd.DataFrame, site_name: str) -> pd.DataFrame:
    site_data = clustered[clustered["site_name"] == site_name].copy()
    if site_data.empty:
        return pd.DataFrame(columns=["month", "cluster", "mean_daily_kWh", "n_HH1", "n_HH2", "n_HH3", "pct_HH1", "pct_HH2", "pct_HH3", "peak_power"])

    summary = (
        site_data.groupby(["month", "cluster"], as_index=False)
        .agg(
            mean_daily_kWh=("mean_daily_kWh", "mean"),
            peak_power=("peak_power", "mean"),
        )
    )

    type_counts = (
        site_data.pivot_table(
            index=["month", "cluster"],
            columns="customer_type",
            values="customer_code",
            aggfunc="nunique",
            fill_value=0,
        )
        .reset_index()
    )

    for customer_type in HOUSEHOLD_TYPES:
        if customer_type not in type_counts.columns:
            type_counts[customer_type] = 0

    summary = summary.merge(type_counts, on=["month", "cluster"], how="left")

    month_totals = monthly_connected_totals(customers, site_name, pd.Index(sorted(site_data["month"].unique())))
    summary = summary.merge(month_totals, on="month", how="left", suffixes=("", "_connected"))

    for customer_type in HOUSEHOLD_TYPES:
        count_column = f"n_{customer_type}"
        pct_column = f"pct_{customer_type}"
        connected_column = f"{customer_type}_connected"
        summary[count_column] = summary[customer_type].astype(int)
        summary[pct_column] = np.where(
            summary[connected_column] > 0,
            100.0 * summary[count_column] / summary[connected_column],
            0.0,
        )

    summary = summary[
        [
            "month",
            "cluster",
            "mean_daily_kWh",
            "n_HH1",
            "n_HH2",
            "n_HH3",
            "pct_HH1",
            "pct_HH2",
            "pct_HH3",
            "peak_power",
        ]
    ].sort_values(["month", "cluster"])

    return summary


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    customers = load_census(args.data_dir / "household_customers.csv")
    readings = load_meter_readings(args.data_dir, customers)
    monthly_features = compute_monthly_features(readings, customers)
    clustered, cluster_profiles = assign_clusters(
        monthly_features,
        n_clusters=args.n_clusters,
        winsor_lower_quantile=args.winsor_lower_quantile,
        winsor_upper_quantile=args.winsor_upper_quantile,
        outlier_mad_threshold=args.outlier_mad_threshold,
    )

    gbowele_summary_path = args.output_dir / "gbowele_monthly_cluster_summary.csv"
    samionta_summary_path = args.output_dir / "samionta_monthly_cluster_summary.csv"
    cluster_profiles_path = args.output_dir / "global_cluster_profiles.csv"

    gbowele_summary = build_cluster_summary(clustered, customers, "Gbowele")
    samionta_summary = build_cluster_summary(clustered, customers, "Samionta")
    gbowele_summary.to_csv(gbowele_summary_path, index=False)
    samionta_summary.to_csv(samionta_summary_path, index=False)
    cluster_profiles.to_csv(cluster_profiles_path, index=False)

    sampled_counts = customers.groupby(["site_name", "customer_type"]).size().unstack(fill_value=0)
    print("Gbowele summary written to", gbowele_summary_path)
    print("Samionta summary written to", samionta_summary_path)
    print("Global cluster profiles written to", cluster_profiles_path)
    print("Sampled households found in household_customers.csv:")
    print(sampled_counts)
    print("Reference census totals used for normalization:")
    print(pd.DataFrame(CENSUS_TOTALS).T.fillna(0).astype(int))
    print("Global number of clusters:", args.n_clusters)
    print("Outlier observations:", int(clustered["is_outlier"].sum()))


if __name__ == "__main__":
    main()
