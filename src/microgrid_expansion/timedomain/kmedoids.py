"""Weighted k-medoids clustering, implemented here rather than taken from a library.

Representative days must be *actual observed days*, not averages of days: an average day
has neither the peak of the days it represents nor their calm, and a sizing driven by peaks
would be quietly wrong. That is what distinguishes medoids from means, and why k-medoids
rather than k-means.

The implementation is the partitioning-around-medoids scheme — a greedy build followed by
swap improvement — which is exact enough at the scale involved here, a few hundred days and
a handful of clusters. It lives in the repository because the only maintained package
offering it is binary-incompatible with current NumPy, and because a dependency for eighty
lines of well-understood algorithm is a liability rather than a convenience.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Clustering:
    """The outcome of a k-medoids partition."""

    medoids: np.ndarray          # (k,) indices of the representative observations
    labels: np.ndarray           # (n,) index into ``medoids`` for each observation
    weights: np.ndarray          # (k,) total weight each medoid represents
    inertia: float               # weighted sum of distances to the assigned medoid

    @property
    def n_clusters(self) -> int:
        return int(self.medoids.size)


def pairwise_distances(features: np.ndarray) -> np.ndarray:
    """Euclidean distance between every pair of observations."""
    x = np.asarray(features, dtype=float)
    square = (x ** 2).sum(axis=1)
    d2 = square[:, None] + square[None, :] - 2.0 * (x @ x.T)
    distances = np.sqrt(np.maximum(d2, 0.0))
    # The expanded form leaves a residue of order the square root of machine precision on
    # the diagonal; a point is at distance zero from itself, so it is set exactly.
    np.fill_diagonal(distances, 0.0)
    return distances


def _assign(distances: np.ndarray, medoids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sub = distances[:, medoids]
    labels = np.argmin(sub, axis=1)
    return labels, sub[np.arange(sub.shape[0]), labels]


def kmedoids(
    features: np.ndarray,
    n_clusters: int,
    weights: np.ndarray | None = None,
    max_iterations: int = 100,
) -> Clustering:
    """Partition observations around ``n_clusters`` medoids, minimising weighted distance.

    ``weights`` lets one observation stand for several, which is what makes the result
    usable when the input has already been aggregated. The build step is deterministic, so
    no seed is needed and repeated runs give the same partition.
    """
    x = np.asarray(features, dtype=float)
    n = x.shape[0]
    if n_clusters < 1:
        raise ValueError("n_clusters must be at least 1")
    if n_clusters > n:
        raise ValueError(f"cannot form {n_clusters} clusters from {n} observations")
    w = np.ones(n) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != (n,):
        raise ValueError(f"weights has {w.shape} entries for {n} observations")

    distances = pairwise_distances(x)

    # --- build: take the point minimising total weighted distance, then add greedily
    weighted = distances * w[:, None]
    medoids = [int(np.argmin(weighted.sum(axis=0)))]
    while len(medoids) < n_clusters:
        _, nearest = _assign(distances, np.array(medoids))
        gains = ((nearest[:, None] - distances) * w[:, None]).clip(min=0.0).sum(axis=0)
        gains[medoids] = -np.inf
        medoids.append(int(np.argmax(gains)))
    medoids = np.array(sorted(medoids))

    # --- swap: exchange a medoid for a non-medoid while the objective improves
    labels, nearest = _assign(distances, medoids)
    best = float((w * nearest).sum())
    for _ in range(max_iterations):
        improved = False
        for position in range(medoids.size):
            for candidate in range(n):
                if candidate in medoids:
                    continue
                trial = medoids.copy()
                trial[position] = candidate
                _, trial_nearest = _assign(distances, trial)
                cost = float((w * trial_nearest).sum())
                if cost < best - 1e-12:
                    medoids, best, improved = trial, cost, True
                    break
            if improved:
                break
        if not improved:
            break

    order = np.argsort(medoids)
    medoids = medoids[order]
    labels, nearest = _assign(distances, medoids)
    cluster_weights = np.array([w[labels == k].sum() for k in range(medoids.size)])
    return Clustering(medoids=medoids, labels=labels, weights=cluster_weights,
                      inertia=float((w * nearest).sum()))
