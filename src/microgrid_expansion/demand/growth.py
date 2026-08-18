"""Demand growth after electrification, and its irreducible uncertainty.

The two reference villages start from the same place and then part company. Three months
after connection they consume 0.253 and 0.267 kWh per household per day, a difference of
5 %; two years later one has grown by a factor 2.31 and the other by 1.12. The initial
level therefore transfers to a new site, and the trajectory does not.

With two villages one cannot estimate how a third will grow -- there is one that grows and
one that does not, and no basis for choosing. Rather than average them into a single
trajectory that describes neither, the two observed behaviours are carried as an explicit
envelope: a slow trajectory, a fast one, and a central case between them. A sizing computed
under the slow trajectory and one computed under the fast trajectory bracket what the site
may require, and the width of that bracket is an honest statement of what the data support.

The trajectory is expressed as the *mixture law itself* rather than as a multiplier on
demand: each scenario is the maturity-conditioned law measured at one reference site, so
the growth is carried by the changing composition of behavioural archetypes and nothing is
extrapolated beyond what was observed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .maturity import (
    MATURITY_EDGES,
    MATURITY_LABELS,
    PRIOR_STRENGTH,
    STATES,
    balanced_law,
    residual_seasonality,
    with_maturity,
)

#: Named growth trajectories and the reference site whose behaviour each reproduces.
#: ``centrale`` is the site-balanced law, midway between the two by construction.
TRAJECTORIES = {
    "lente": "Samionta",
    "centrale": None,
    "rapide": "Gbowele",
}
DEFAULT_TRAJECTORY = "centrale"


def maturity_band(maturity_months: int) -> str:
    """Maturity band a site of a given age falls into."""
    if maturity_months < 0:
        raise ValueError("maturity_months must be non-negative")
    index = int(np.searchsorted(np.asarray(MATURITY_EDGES[1:]), maturity_months, side="left"))
    return MATURITY_LABELS[min(index, len(MATURITY_LABELS) - 1)]


def trajectory_law(
    trajectory: str = DEFAULT_TRAJECTORY,
    frame: pd.DataFrame | None = None,
    prior_strength: float = PRIOR_STRENGTH,
) -> pd.DataFrame:
    """Mixture law ``P(C | T, maturity)`` under one growth trajectory.

    A band with no record at the chosen site -- the fast trajectory has none beyond two
    years -- inherits the last band that does, a constant extrapolation that holds growth
    rather than inventing its continuation.
    """
    if trajectory not in TRAJECTORIES:
        raise ValueError(f"unknown trajectory {trajectory!r}; "
                         f"choose from {sorted(TRAJECTORIES)}")
    frame = with_maturity() if frame is None else frame
    site = TRAJECTORIES[trajectory]
    if site is not None:
        frame = frame[frame["site_name"] == site]

    rows: list[dict] = []
    last_seen: dict[str, pd.Series] = {}
    for band in MATURITY_LABELS:
        observations = frame[frame["maturity"] == band]
        if observations.empty:
            continue
        prior = balanced_law(observations)
        for customer_type, stratum in observations.groupby("customer_type"):
            empirical = balanced_law(stratum)
            support = float(len(stratum))
            weight = support / (support + prior_strength)
            posterior = weight * empirical + (1.0 - weight) * prior
            posterior = posterior / posterior.sum()
            last_seen[customer_type] = posterior
            rows.append({"customer_type": customer_type, "maturity": band,
                         "n_observations": int(support),
                         **{state: float(posterior[state]) for state in STATES}})

    table = pd.DataFrame(rows)
    # Carry the last observed band forward where the trajectory's record stops.
    for customer_type, posterior in last_seen.items():
        present = set(table.loc[table["customer_type"] == customer_type, "maturity"])
        for band in MATURITY_LABELS:
            if band not in present:
                rows.append({"customer_type": customer_type, "maturity": band,
                             "n_observations": 0,
                             **{state: float(posterior[state]) for state in STATES}})
    table = pd.DataFrame(rows)
    return table.set_index(["maturity", "customer_type"])[list(STATES)]


@dataclass(frozen=True)
class GrowthEnvelope:
    """Measured growth of each reference site, relative to its own first quarter."""

    factors: pd.DataFrame            # maturity band x site

    @property
    def spread(self) -> float:
        """Ratio of the fastest to the slowest trajectory at its widest."""
        finite = self.factors.dropna(how="any")
        if finite.empty:
            return float("nan")
        ratios = finite.max(axis=1) / finite.min(axis=1)
        return float(ratios.max())


def growth_envelope(frame: pd.DataFrame | None = None) -> GrowthEnvelope:
    """Energy growth factor of each reference site by maturity band."""
    from .partition import load_archetype_profiles

    frame = with_maturity() if frame is None else frame
    energy = load_archetype_profiles()["mean_daily_kwh"].to_dict()
    energy["inactive"] = 0.0
    energy.setdefault("outlier",
                      float(frame.loc[frame["cluster"] == "outlier", "mean_daily_kWh"].mean()))

    columns: dict[str, list[float]] = {}
    for site, group in frame.groupby("site_name"):
        levels = []
        for band in MATURITY_LABELS:
            band_rows = group[group["maturity"] == band]
            if band_rows.empty:
                levels.append(np.nan)
                continue
            law = balanced_law(band_rows)
            levels.append(float(sum(law[s] * energy.get(s, 0.0) for s in STATES)))
        base = levels[0] if levels and levels[0] == levels[0] else np.nan
        columns[site] = [level / base if base else np.nan for level in levels]
    return GrowthEnvelope(pd.DataFrame(columns, index=list(MATURITY_LABELS)))


def seasonal_index(frame: pd.DataFrame | None = None) -> pd.Series:
    """Calendar-month multiplier that survives conditioning on maturity, mean one.

    Applied to the simulated profile month by month, it restores the seasonal variation
    that is genuinely seasonal, having removed the part that was a cohort artefact of both
    records beginning in the same month.
    """
    table = residual_seasonality(frame)
    index = table["seasonal_index"]
    return index / index.mean()


def main() -> int:
    frame = with_maturity()
    envelope = growth_envelope(frame)
    print("Croissance de la demande après raccordement, par site")
    print("(facteur par rapport au premier trimestre du site)")
    print(envelope.factors.round(2).to_string())
    print(f"\néventail le plus large entre trajectoires : x{envelope.spread:.2f}")

    print("\nTrajectoires disponibles :")
    for name, site in TRAJECTORIES.items():
        law = trajectory_law(name, frame)
        hh1 = law.xs("HH1", level="customer_type")
        origin = site if site else "moyenne équilibrée des deux sites"
        print(f"\n  {name} ({origin}) — part de chaque état pour HH1 [%] :")
        print((100 * hh1.reindex(list(MATURITY_LABELS))).round(1).to_string())

    print("\nIndice saisonnier résiduel (moyenne 1) :")
    print(seasonal_index(frame).round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
