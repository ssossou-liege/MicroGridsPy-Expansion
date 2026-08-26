"""Compression of an operating year into weighted representative days.

A year of hourly operation is clustered into a handful of days, each standing for the days
nearest to it and carrying their number as its weight. The medoids are real days, so the
compressed year retains genuine peaks and genuine calm spells rather than the flattened
average a centroid would produce.

**A day runs from sunrise to sunrise, not from midnight to midnight.** The calendar day cuts
the night in half, and the half it leaves at the end is the shorter one: on the reference site
the evening peak falls at nineteen hours, four hours before the array runs out, while the
night it opens lasts thirteen. A controller whose whole function is to carry that night sees
a third of it, provisions for a third of it, and starts its generator for the rest — which is
not a property of the plant but of where the day was cut. Rolling the year to the hour the
array starts producing puts the night inside the day it belongs to. The alignment is read
from the resource rather than declared, since it moves with the latitude and the season.

**What this is, and what it is not.** Time-domain reduction is an *approximation*, not a
relaxation: the weighted cost of the representative days is neither above nor below the
cost of the full year in general, and it is therefore not a valid bound. The certificate of
this work does not rest on it — the lower bound is computed over the full year, whose linear
relaxation is cheap enough to solve thousands of times. Representative days exist for the
tree, where a full year at every node and every scenario is out of reach, and their
reduction error is measured and reported rather than assumed small.

The compression uses the shape of both drivers at once, demand and resource. Clustering on
demand alone would merge a cloudy day with a sunny one of the same consumption, which are
entirely different problems for a plant whose storage must bridge the difference.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .kmedoids import kmedoids

HOURS_PER_DAY = 24


@dataclass
class RepDays:
    """Weighted representative days, on the ``(day, hour)`` grid."""

    weight: np.ndarray            # (k,) days represented; sums to the year's length
    demand: np.ndarray            # (k, 24) [kW]
    specific_yield: np.ndarray    # (k, 24) [kW/kW]
    t_amb_c: np.ndarray           # (k, 24) [degC]
    usable_fraction: np.ndarray   # (k, 24) [-]
    self_discharge: np.ndarray    # (k, 24) [-]
    medoid_days: np.ndarray       # (k,) index of each representative day in the year
    labels: np.ndarray            # (n_days,) which representative day each day maps to

    @property
    def n_days(self) -> int:
        return int(self.weight.size)

    def flat(self) -> dict[str, np.ndarray]:
        """The same arrays flattened to a single time axis, with hourly weights."""
        return {
            "demand_kw": self.demand.ravel(),
            "specific_yield": self.specific_yield.ravel(),
            "t_amb_c": self.t_amb_c.ravel(),
            "usable_fraction": self.usable_fraction.ravel(),
            "self_discharge": self.self_discharge.ravel(),
            "weights": np.repeat(self.weight, HOURS_PER_DAY),
        }

    def expand(self) -> dict[str, np.ndarray]:
        """Reconstruct a full year by repeating each representative day over its cluster."""
        order = np.argsort(self.labels, kind="stable")
        rebuilt = {}
        for name, array in (("demand_kw", self.demand),
                            ("specific_yield", self.specific_yield),
                            ("t_amb_c", self.t_amb_c)):
            stacked = array[self.labels]                      # (n_days, 24)
            rebuilt[name] = stacked.ravel()
        return rebuilt


def sunrise_hour(specific_yield: np.ndarray, threshold: float = 0.01) -> int:
    """Hour at which the array starts producing, on the mean day.

    Read from the data rather than declared: it moves with the latitude and with the season,
    and a site sized on a convention borrowed from another would carry that convention's
    error into every representative day.
    """
    days = specific_yield.size // HOURS_PER_DAY
    mean_day = specific_yield[:days * HOURS_PER_DAY].reshape(days, HOURS_PER_DAY).mean(axis=0)
    lit = np.flatnonzero(mean_day > threshold * max(mean_day.max(), 1e-12))
    return int(lit[0]) if lit.size else 0


def daily_features(demand_kw: np.ndarray, specific_yield: np.ndarray) -> np.ndarray:
    """Feature vector of each day: both daily shapes, scaled to comparable magnitude.

    Each channel is divided by its own standard deviation over the year so that neither
    driver dominates the distance merely because it is measured in larger numbers.
    """
    days = demand_kw.size // HOURS_PER_DAY
    demand = demand_kw[:days * HOURS_PER_DAY].reshape(days, HOURS_PER_DAY)
    yield_ = specific_yield[:days * HOURS_PER_DAY].reshape(days, HOURS_PER_DAY)

    scale_d = demand.std() or 1.0
    scale_y = yield_.std() or 1.0
    return np.hstack([demand / scale_d, yield_ / scale_y])


def reduce_to_rep_days(instance, n_rep: int = 12,
                       align_to_sunrise: bool = True) -> RepDays:
    """Compress a site-year into ``n_rep`` weighted representative days.

    Asking for as many days as the year holds — or more — returns the year itself, every
    day standing only for itself. That is not a degenerate case to be guarded against but
    the one setting under which the compression costs nothing, and it is what a study needs
    whenever the quantity being measured is destroyed by compressing: the price of the
    heuristic is the price of not knowing what tomorrow brings, and a representative day has
    no tomorrow of its own.
    """
    days = instance.demand_kw.size // HOURS_PER_DAY
    if n_rep >= days:
        # Nothing is compressed, so there are no day boundaries to worry about: the
        # simulation runs the hours in the order they occur. Alignment exists to stop an
        # independent day from cutting the night in half, and an uncompressed year has no
        # independent days.
        def as_days(array: np.ndarray) -> np.ndarray:
            return np.asarray(array)[:days * HOURS_PER_DAY].reshape(days, HOURS_PER_DAY)
        every = np.arange(days)
        return RepDays(weight=np.ones(days), demand=as_days(instance.demand_kw),
                       specific_yield=as_days(instance.specific_yield),
                       t_amb_c=as_days(instance.t_amb_c),
                       usable_fraction=as_days(instance.usable_fraction),
                       self_discharge=as_days(instance.self_discharge),
                       medoid_days=every, labels=every)

    # The year is rolled rather than trimmed, so that no day is lost to the offset: the
    # hours before the first sunrise belong to the night that closes the year.
    offset = (sunrise_hour(instance.specific_yield) if align_to_sunrise else 0)

    def as_days(array: np.ndarray) -> np.ndarray:
        rolled = np.roll(np.asarray(array)[:days * HOURS_PER_DAY], -offset)
        return rolled.reshape(days, HOURS_PER_DAY)

    clustering = kmedoids(
        daily_features(as_days(instance.demand_kw).ravel(),
                       as_days(instance.specific_yield).ravel()), n_rep)
    chosen = clustering.medoids
    return RepDays(
        weight=clustering.weights,
        demand=as_days(instance.demand_kw)[chosen],
        specific_yield=as_days(instance.specific_yield)[chosen],
        t_amb_c=as_days(instance.t_amb_c)[chosen],
        usable_fraction=as_days(instance.usable_fraction)[chosen],
        self_discharge=as_days(instance.self_discharge)[chosen],
        medoid_days=chosen,
        labels=clustering.labels,
    )


def reduction_error(instance, rep: RepDays) -> dict[str, float]:
    """How far the compressed year departs from the year it stands for.

    Reports the quantities a sizing is sensitive to: annual energy, peak demand and annual
    resource. The peak matters most and compresses worst — a handful of days cannot contain
    every extreme of a year — so it is reported separately rather than folded into an
    average.
    """
    hours_per_day = HOURS_PER_DAY
    days = instance.demand_kw.size // hours_per_day
    demand_days = instance.demand_kw[:days * hours_per_day].reshape(days, hours_per_day)
    yield_days = instance.specific_yield[:days * hours_per_day].reshape(days, hours_per_day)

    full_energy = float(demand_days.sum())
    rep_energy = float((rep.demand.sum(axis=1) * rep.weight).sum())
    full_yield = float(yield_days.sum())
    rep_yield = float((rep.specific_yield.sum(axis=1) * rep.weight).sum())

    def relative(a: float, b: float) -> float:
        return 100.0 * (a - b) / b if b else float("nan")

    return {
        "energy_error_pct": relative(rep_energy, full_energy),
        "yield_error_pct": relative(rep_yield, full_yield),
        "peak_error_pct": relative(float(rep.demand.max()), float(demand_days.max())),
        "days_represented": float(rep.weight.sum()),
        "n_rep_days": float(rep.n_days),
    }
