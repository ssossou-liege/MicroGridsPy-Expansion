"""Per-stage scenario reduction.

Condenses the Monte-Carlo ensemble at each stage to a small set of representative
outcomes, each carrying the probability mass of its cluster. A medoid-based method
(k-medoids on a feature representation of the paths, or fast-forward selection) is
used so that representatives are actual sampled outcomes.

The reduction error relative to the full ensemble is returned so that the compression
stays transparent (no silent truncation).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..scenarios.assemble import ScenarioPath


@dataclass
class StageReduction:
    """Result of reducing one stage's outcomes."""

    representatives: list[int]          # indices of representative paths
    assignment: np.ndarray              # path -> representative index
    weights: np.ndarray                 # probability mass per representative
    error: float                        # distortion vs full ensemble


def stage_features(paths: list[ScenarioPath], stage_year: int) -> np.ndarray:
    """Feature vector of each path's outcome at one stage.

    A scenario is summarised by what a sizing is actually sensitive to: how much energy it
    must serve, how peaked that demand is, how much resource is available and how the two
    line up in the day, and what the fuel and capital prices are. Each channel is scaled by
    its own spread across the ensemble, so that a dollar and a kilowatt-hour do not compete
    on the accident of their units.
    """
    rows = []
    for path in paths:
        demand = path.demand[stage_year]
        yield_ = path.pv_unit[stage_year]
        costs = next(d.costs for d in path.draws if d.stage_year == stage_year)
        daytime = demand.reshape(-1, 24)[:, 7:19].sum() / max(demand.sum(), 1e-9)
        rows.append([
            demand.sum(),                       # energy to serve
            demand.max(),                       # peak
            daytime,                            # when it falls
            yield_.sum(),                       # resource
            float(np.corrcoef(demand, yield_)[0, 1]),   # how the two line up
            costs["fuel_price"],
            costs["capex_pv"],
            costs["capex_batt"],
        ])
    features = np.array(rows, dtype=float)
    spread = features.std(axis=0)
    spread[spread <= 0] = 1.0
    return features / spread


def reduce_stage(paths: list[ScenarioPath], stage_year: int, n_repr: int,
                 seed: int = 0) -> StageReduction:
    """Reduce the ensemble of stage-``stage_year`` outcomes to ``n_repr`` medoids.

    Medoids rather than centroids, for the reason the time-domain reduction uses them: a
    representative must be an outcome that could occur, and the average of a dry scenario
    and a wet one is neither. The distortion reported is the mean distance of an outcome to
    the representative standing for it, in the scaled feature space, so that a compression
    that has lost something says so.
    """
    from ..timedomain.kmedoids import kmedoids

    features = stage_features(paths, stage_year)
    n_repr = max(1, min(int(n_repr), features.shape[0]))
    clustering = kmedoids(features, n_repr)

    weights = clustering.weights.astype(float)
    weights = weights / weights.sum()
    distances = np.linalg.norm(features - features[clustering.medoids][clustering.labels],
                               axis=1)
    return StageReduction(representatives=[int(m) for m in clustering.medoids],
                          assignment=clustering.labels.astype(int),
                          weights=weights,
                          error=float(distances.mean()))
