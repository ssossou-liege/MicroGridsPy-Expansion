"""When the feeder is energised, and when it is not.

A connection in these countries is not a source that is simply there. It is there most of
the time, absent for stretches, and the length of those stretches decides what the plant must
carry alone. Sizing against an average availability would size against a grid that dims
rather than one that goes out, and the difference is precisely a storage decision.

The pattern is generated from two figures an operator knows about their own feeder — the
share of hours it is live and how long an outage typically lasts — rather than read from a
recorded year, so that a sizing is not tuned to the particular outages of one year that will
not repeat.
"""
from __future__ import annotations

import numpy as np


def outage_pattern(hours: int, availability: float, mean_outage_hours: float,
                   seed: int = 0) -> np.ndarray:
    """A boolean series: ``True`` where the grid is energised.

    A two-state alternating renewal process. Outage lengths are geometric with the stated
    mean, and the live stretches between them are geometric with whatever mean makes the
    long-run share come out at ``availability``. Both are memoryless, which is the honest
    default when an operator can state an average and a typical duration and nothing more
    about the shape.
    """
    if availability >= 1.0:
        return np.ones(hours, dtype=bool)
    if availability <= 0.0:
        return np.zeros(hours, dtype=bool)

    mean_outage = max(float(mean_outage_hours), 1.0)
    # share = live / (live + outage), solved for the mean live stretch
    mean_live = mean_outage * availability / (1.0 - availability)
    rng = np.random.default_rng(seed)

    live = np.empty(0, dtype=bool)
    segments: list[np.ndarray] = []
    total = 0
    # Start energised or not in proportion to the availability, so a short horizon is not
    # biased by always beginning in the same state.
    energised = bool(rng.random() < availability)
    while total < hours:
        mean = mean_live if energised else mean_outage
        length = max(1, int(rng.geometric(1.0 / max(mean, 1.0))))
        segments.append(np.full(length, energised, dtype=bool))
        total += length
        energised = not energised
    live = np.concatenate(segments)[:hours]
    return live


def describe(live: np.ndarray) -> dict:
    """What the generated pattern actually delivers, for reporting beside what was asked."""
    n = int(live.size)
    if n == 0:
        return {"availability": 0.0, "outages": 0, "mean_outage_hours": 0.0,
                "longest_outage_hours": 0}
    changes = np.diff(live.astype(int))
    starts = int((changes == -1).sum()) + (1 if not live[0] else 0)
    down = ~live
    lengths, run = [], 0
    for value in down:
        if value:
            run += 1
        elif run:
            lengths.append(run); run = 0
    if run:
        lengths.append(run)
    return {"availability": float(live.mean()),
            "outages": starts,
            "mean_outage_hours": float(np.mean(lengths)) if lengths else 0.0,
            "longest_outage_hours": int(max(lengths)) if lengths else 0}
