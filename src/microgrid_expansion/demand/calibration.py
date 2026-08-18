"""Reconciling the appliance calibration with the measured archetype statistics.

The appliance parameters in ``cluster_params.csv`` describe *what* each behavioural
archetype owns and *when* it uses it. Simulated as they stand, they do not reproduce the
daily energy and the peak power measured for those same archetypes: the low-consumption
archetypes come out too energetic, and the two archetypes with high measured peaks cannot
reach them at all, their calibrated appliance stock amounting to a fraction of the peak
observed on the meters. The discrepancy is a property of the calibration, not of the
simulator, and it is documented rather than absorbed silently.

This module fits, per archetype, the two factors that reconcile simulation and
measurement:

* a **power factor** scaling every appliance's rated power, which moves the peak and the
  daily energy in the same proportion;
* a **duration factor** scaling every appliance's usage time, which moves the daily energy
  alone.

Two targets -- mean daily energy and mean peak power -- and two degrees of freedom, so the
system is exactly determined. Matching both also matches the load factor, which is their
ratio. The fitted factors are written next to the calibration so that any run is
reproducible and the size of the correction stays auditable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR
from .generator import (
    ARCHETYPES,
    MINUTES_PER_DAY,
    ArchetypeScaling,
    _build_households,
    load_archetype_appliances,
)

#: Metering interval of the reference readings [minutes]. The measured peak is a mean over
#: this interval, so the simulated peak must be taken at the same resolution to be
#: comparable: a peak read at one-minute resolution is systematically higher.
METER_INTERVAL_MIN = 15

SCALING_PATH = REFERENCE_DIR / "archetype_scaling.csv"


@dataclass
class ArchetypeStatistics:
    """Simulated statistics of one archetype, per household."""

    archetype: str
    daily_energy_kwh: float
    peak_w: float

    @property
    def load_factor(self) -> float:
        mean_w = self.daily_energy_kwh * 1000.0 / 24.0
        return mean_w / self.peak_w if self.peak_w > 0 else 0.0


def measured_statistics() -> pd.DataFrame:
    """Measured per-household statistics of each archetype, from the segmentation."""
    profiles = pd.read_csv(REFERENCE_DIR / "global_cluster_profiles.csv")
    profiles["cluster"] = profiles["cluster"].astype(str)
    profiles = profiles[profiles["cluster"].isin(ARCHETYPES)].set_index("cluster")
    return profiles[["cluster_mean_daily_kWh", "cluster_mean_peak_power",
                     "cluster_mean_load_factor"]]


def simulate_archetype(
    archetype: str,
    appliances: pd.DataFrame,
    scaling: ArchetypeScaling | None = None,
    n_households: int = 40,
    n_days: int = 28,
    seed: int = 0,
) -> ArchetypeStatistics:
    """Simulate a sample of households of one archetype and return their statistics.

    Households are simulated individually rather than as one aggregate, because the
    measured peak is a *per-household* quantity: the peak of a community profile is far
    smoother than the mean of the households' own peaks, and comparing the two would
    understate the peak by a large factor.
    """
    from ramp import UseCase

    rng = np.random.default_rng(seed)
    users = _build_households(archetype, n_households, appliances, rng, scaling)
    if not users:
        return ArchetypeStatistics(archetype, 0.0, 0.0)

    energies, peaks = [], []
    for i, user in enumerate(users):
        case = UseCase(users=[user], date_start="2025-01-01",
                       date_end=f"2025-01-{n_days:02d}", random_seed=seed + i)
        profile = np.asarray(case.generate_daily_load_profiles(), dtype=float).ravel()
        energies.append(profile.sum() / 60.0 / 1000.0 / n_days)          # kWh/day
        interval = profile.reshape(-1, METER_INTERVAL_MIN).mean(axis=1)  # W, 15 min
        peaks.append(interval.max())
    return ArchetypeStatistics(archetype, float(np.mean(energies)), float(np.mean(peaks)))


def fit_scaling(
    n_households: int = 60,
    n_days: int = 28,
    seed: int = 0,
    n_iterations: int = 3,
) -> tuple[ArchetypeScaling, pd.DataFrame]:
    """Fit the power and duration factors that match the measured statistics.

    One pass suffices in principle, energy being proportional to the product of the two
    factors and the peak to the power factor alone; further passes absorb the residual
    non-linearity introduced by the window and duty-cycle bounds. Three passes over sixty
    households bring the residuals within roughly 8 % on the daily energy and 10 % on the
    peak, the remainder being Monte-Carlo noise of the sample.
    """
    appliances = load_archetype_appliances()
    measured = measured_statistics()

    power = {a: 1.0 for a in ARCHETYPES}
    time = {a: 1.0 for a in ARCHETYPES}
    rows: list[dict] = []

    for iteration in range(n_iterations):
        scaling = ArchetypeScaling(power=dict(power), time=dict(time))
        for archetype in ARCHETYPES:
            stats = simulate_archetype(archetype, appliances[archetype], scaling,
                                       n_households, n_days, seed)
            target_energy = float(measured.loc[archetype, "cluster_mean_daily_kWh"])
            target_peak = float(measured.loc[archetype, "cluster_mean_peak_power"])
            if stats.peak_w <= 0 or stats.daily_energy_kwh <= 0:
                continue
            # Peak is set by power alone; energy by the product of both factors.
            power[archetype] *= target_peak / stats.peak_w
            energy_ratio = target_energy / stats.daily_energy_kwh
            time[archetype] *= energy_ratio * stats.peak_w / target_peak
            rows.append({
                "iteration": iteration, "cluster": archetype,
                "sim_energy_kwh_day": stats.daily_energy_kwh,
                "sim_peak_w": stats.peak_w,
                "target_energy_kwh_day": target_energy,
                "target_peak_w": target_peak,
                "power_scale": power[archetype], "time_scale": time[archetype],
            })
    return ArchetypeScaling(power=power, time=time), pd.DataFrame(rows)


def write_scaling(scaling: ArchetypeScaling, path=SCALING_PATH) -> "pd.DataFrame":
    """Persist the fitted factors next to the calibration they correct."""
    table = pd.DataFrame({
        "cluster": list(ARCHETYPES),
        "power_scale": [scaling.power.get(a, 1.0) for a in ARCHETYPES],
        "time_scale": [scaling.time.get(a, 1.0) for a in ARCHETYPES],
    })
    table.to_csv(path, index=False)
    return table


def main() -> int:
    scaling, trace = fit_scaling()
    table = write_scaling(scaling)
    measured = measured_statistics()

    print("Facteurs d'ajustement par archétype")
    print(table.to_string(index=False))
    print("\nVérification après ajustement :")
    appliances = load_archetype_appliances()
    print(f"{'arch':>5s}{'énergie kWh/j':>26s}{'pointe W':>22s}")
    print(f"{'':5s}{'simulé':>11s}{'mesuré':>10s}{'écart':>8s}"
          f"{'simulé':>10s}{'mesuré':>8s}{'écart':>8s}")
    for archetype in ARCHETYPES:
        stats = simulate_archetype(archetype, appliances[archetype], scaling,
                                   n_households=60, seed=99)
        e_ref = float(measured.loc[archetype, "cluster_mean_daily_kWh"])
        p_ref = float(measured.loc[archetype, "cluster_mean_peak_power"])
        print(f"C{archetype:>4s}{stats.daily_energy_kwh:11.3f}{e_ref:10.3f}"
              f"{100 * (stats.daily_energy_kwh - e_ref) / e_ref:+7.1f}%"
              f"{stats.peak_w:10.0f}{p_ref:8.0f}"
              f"{100 * (stats.peak_w - p_ref) / p_ref:+7.1f}%")
    print(f"\nécrit {SCALING_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
