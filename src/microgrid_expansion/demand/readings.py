"""The meter archive with each reading over its own period.

A reading carries the mean power since the meter's previous one, which is usually a
quarter-hour but not always: after a gap in communication the meter reports once, with the
mean over the whole gap. The archive keeps the power and the time of each reading, not its
period, so the period is restored here, and every reader that takes an energy from the
archive takes it through this module: the comparison with the meters, the levels a village
with a plant starts from, the productive class profiles and, at generation, the household
segmentation. Its own module because the last of those runs at generation, and the cache
key hashes what does.
"""
from __future__ import annotations

import pandas as pd

#: The longest stretch one reading is taken to cover, in seconds. Beyond a day the gap is
#: more often a meter that stopped reporting than one that caught up, and the reading is
#: given a day.
LONGEST_PERIOD_S = 86_400.0
#: The period of a code's first reading, which has no reading before it: the meters' own
#: quarter-hour.
FIRST_PERIOD_S = 900.0


def timed_readings(site_name: str) -> pd.DataFrame:
    """A site's archive with each reading over its own period, for the energy it bills.

    A reading carries the mean power since the meter's previous one, which is usually a
    quarter-hour but not always: after a gap in communication the meter reports once, with
    the mean over the whole gap. The archive keeps the power and the time, not the period,
    and its readers so far gave each reading a quarter-hour, which drops the rest of the
    gap: read so, Samionta's customers draw 14 % less than their meters' registers in June
    2026 and 11 % less in July, against 3 % in a month without outages. The period is the
    time since the code's previous reading, which is what the exports record in 99.98 % of
    the readings (checked against their own period column, June to October 2026), capped at
    ``LONGEST_PERIOD_S``. Read so, the archive stays 1 to 5 % below the registers in most
    months, at both villages, which is the gap between the mean power the archive keeps and
    the energy the meter counts.

    Returns the archive's columns, the period in ``seconds``, the energy in ``kwh`` and the
    calendar ``month``.
    """
    from ..sites import SITES

    return with_periods(pd.read_parquet(SITES[site_name].meter_path(),
                                        columns=["timestamp", "customer_code", "power_W"]))


def with_periods(readings: pd.DataFrame) -> pd.DataFrame:
    """Readings with the period each covers, its energy and its month (``timed_readings``)."""
    readings = readings.sort_values(["customer_code", "timestamp"], ignore_index=True)
    gap = readings.groupby("customer_code").timestamp.diff().dt.total_seconds()
    seconds = gap.fillna(FIRST_PERIOD_S).clip(upper=LONGEST_PERIOD_S)
    return readings.assign(seconds=seconds,
                           kwh=readings.power_W * seconds / 3.6e6,
                           month=readings.timestamp.dt.to_period("M"))
