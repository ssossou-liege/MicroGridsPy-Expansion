r"""Calibrate the uses that are neither a household nor a trade, where meters allow.

Writes one table to ``data/ramp_params/reference/``:

``community_class_profiles.csv``
    Mean hourly load of one connected use of each class [kW], its mean daily energy, the
    spread of that energy from day to day, and what kind of load it is --- which category
    it belongs to, whether a customer is billed for it, and whether it sits on the
    distribution network.

Two classes come out of this, of the five such uses the model knows.

The places of worship are measured. Five are metered across the two villages and four have
drawn current; their shape is unmistakable once drawn, peaking in the evening with a second
rise through the morning service hours, and carrying a large share of its energy through the
night on what is presumably a security lamp. The level is low and the spread is wide, which
is what a building used on particular days rather than continuously looks like.

The four are averaged without weighting, each being one building and so one draw of what
"a place of worship" is. One of them is a very small church --- six kilowatt-hours over a
hundred supplying days, a fifteenth of the largest --- and it is kept rather than dropped,
because a village may well have one of those. It is what takes the class from about seven
tenths of a kilowatt-hour a day to about five.

The powerhouse is measured too, and at both plants. The air conditioning of the room the
inverters stand in is metered separately at each, and the two agree closely: a block
through the working day with a flat top, nothing at all through the small hours, and a
second block of about two hours before midnight. Neither is a customer --- nobody is
invoiced for either --- and the load sits at the plant rather than on the network, so no
distribution loss applies to it.

Neither is identified by its meter. Meters move: the operator lifts one and reassigns it,
so the serial the register shows today says nothing about whose load it recorded two years
ago. The one the register calls "SAM POWERHOUSE" was metering a place of worship in July
2024. So every class here is selected by the customer each reading names, and the
powerhouse is assembled per site over whatever names the operator has used for it.

The school is not measured, and the reason is administrative rather than technical. One
school is metered, at Gbowele since the tenth of May 2026, and over nine thousand seven
hundred readings it has drawn nothing at all: its credit balance has never left zero and
its relay has stood open for all but five of them. It is connected, and nobody has budgeted
to charge the meter. The record also falls almost entirely inside the July-to-September
holidays, so even credited it would have little to show. The other village has no school
meter. So there is no school load here to calibrate; what the record shows is one
administration's budget, not what a school draws.

The health centre is not measured either, for the plainer reason that neither pilot village
has one. The street lighting is not metered anywhere and needs no shape: it burns dusk to
dawn and a lamp count and a rating settle it.

Both therefore remain uses a developer declares, device by device, through the
specification in :mod:`microgrid_expansion.demand.uses`.

Every series is put on the site's own clock, which is the clock the model indexes an hour
by and the one the resource is converted to and checked against solar noon. Neither source
here arrives on it: the operator's monthly exports carry an explicit UTC offset, and the
harmonised archive strips that suffix and declares site local time without converting --
shifted one hour forward it reproduces, to the last digit, the archive the household and
productive calibrations are built from. An hour is the error a storage sizing is least able
to absorb, and it is the one error that shows up nowhere except in a check like that.

A reading is laid over the interval it covers rather than dropped into the hour of its
timestamp. The meters report every quarter of an hour and occasionally, after an outage or a
communication gap, post one reading covering several hours; that is one and a half per cent
of the energy, and dropping it all into a single hour moved one place of worship's peak from
eleven in the morning to eleven at night and trebled its apparent maximum power. The
interval is read as the gap to the previous reading, which matches the period the meter
reports to the minute on four million readings.

The script is deterministic given its inputs, and writes nothing outside ``--out``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR

#: What carries one of these uses, by the class it belongs to.
#:
#: Identified by the *customer*, never by the meter. A meter is movable plant: the operator
#: lifts one and gives it to whoever needs it, so what it recorded last year may belong to
#: somebody else entirely. The register bears this out. The meter it lists today as
#: "SAM POWERHOUSE" was recording a place of worship in July 2024, code 0004SAM, and keyed
#: on that serial those three kilowatt-hours would have entered the powerhouse class as the
#: plant's own supply. In the other direction, the Samionta powerhouse has been through
#: three meters under two spellings of its name. A serial answers "what hardware", and the
#: question here is "whose load".
#:
#: Customers with a code are named by it, which the harmonised archive is keyed on. The
#: powerhouse has no code -- it is not a customer who pays -- so it is named by the
#: customer name each reading carries, and read from the operator's exports, which keep
#: that name. One instance per site, assembled from whatever names the operator has used
#: for it over the years, because what is being calibrated is one plant room and not one
#: meter's career.
#:
#: ``billable`` and ``on_network`` travel with the shape because they decide what is done
#: with it: the first settles whether the energy can be invoiced, the second whether a
#: distribution loss reaches it. Written into the table, the generator reads them off the
#: calibration instead of carrying a list of keys of its own.
METERS: dict[str, dict] = {
    "place_of_worship": {
        "category": "community", "billable": True, "on_network": True,
        "codes": ("0004SAM", "0007SAM", "0153GBO", "0150GBO", "0056GBO"),
    },
    "school": {
        "category": "community", "billable": True, "on_network": True,
        "codes": ("0054GBO",),
    },
    "powerhouse": {
        "category": "self_consumption", "billable": False, "on_network": False,
        # Customer names as the exports record them, lowercased and stripped. Each site is
        # one instance; the spellings within a site are one customer renamed, or one load
        # handed from one customer record to the next.
        "names_by_site": {
            "Samionta": ("sam powerhouse", "sam_powerhouse", "sam climatiseur"),
            "Gbowele": ("clim gbo",),
        },
    },
}

#: Relay states in which the connection is actually supplying. Every other state is a meter
#: reporting while its relay stands open, and counting those hours would dilute a shape with
#: hours during which nothing could have been drawn. Across both sites the other states
#: carry three hundredths of a per cent of the energy.
SUPPLYING_STATES = (0, 1)

#: Below this, a meter has not drawn enough over its life for an hourly shape to mean
#: anything, and it is left out of the class it belongs to rather than flattening it.
MIN_KWH = 1.0

#: Nor has a meter with a shorter record, whatever it drew. Energy alone is the wrong test:
#: one powerhouse meter recorded three kilowatt-hours over seven days of July 2024, which
#: clears any energy floor low enough to admit a lightly used place of worship, and averaged
#: into its class it halved the class's daily energy and doubled its reported spread. A
#: month of supply is the least from which a daily mean and a day-to-day spread mean
#: anything; the meters this admits carry between a hundred and a thousand days.
MIN_DAYS = 30

#: What a reading is assumed to cover when it is the first of its meter and there is no
#: previous one to measure the gap against. The meters report every quarter of an hour.
DEFAULT_PERIOD_S = 900.0

#: Beyond this, a gap is a hole in the record rather than a period of supply: a meter that
#: went silent for a week and then posted its accumulated register did not draw that energy
#: evenly across the week. Such a reading is dropped, with its energy, rather than smeared.
MAX_PERIOD_H = 6.0

HOURS = tuple(range(24))

#: Which village each customer-code suffix belongs to, so that the site's own time offset
#: can be looked up.
SITE_OF_SUFFIX = {"SAM": "Samionta", "GBO": "Gbowele"}


def _local(frame: pd.DataFrame, site_name: str) -> pd.DataFrame:
    """Move a frame's timestamps onto the site's own clock, which is the model's clock.

    The archive and the operator's exports are both on UTC, whatever their labels say. The
    monthly exports carry an explicit "+00:00"; the harmonised archive strips that suffix
    and asserts site local time, and it is wrong to -- shifted one hour forward it
    reproduces, to the last digit over fifty-three thousand readings, the archive the
    household and productive calibrations are built from. The resource side converts ERA5
    to local time and checks the result against solar noon, so local is the clock the model
    indexes an hour by, and a calibration an hour early would put every evening peak an
    hour before the sun had set.
    """
    from ..sites import get_site

    try:
        offset = int(get_site(site_name).utc_offset_hours)
    except (KeyError, FileNotFoundError, ValueError):
        offset = 1                           # West Africa Time, where both villages are
    if offset:
        frame = frame.copy()
        frame["timestamp"] = frame["timestamp"] + pd.Timedelta(hours=offset)
    return frame


def _customer_readings(archive: Path, code: str) -> pd.DataFrame:
    """One customer's supplying readings, from the harmonised smart-meter archive.

    Readings whose customer code the archive reconstituted are left out. The archive
    recovers a malformed code through the meter register -- whoever holds that meter now --
    and a meter is movable plant, so the recovery is an inference about the past from the
    present. For one place of worship it covers four months of 2023 on a meter the exports
    first show under that customer in December of that year. Dropping them moves the class
    by three parts in a thousand, which is a cheap price for a calibration that says only
    what the readings say.
    """
    site = code[-3:]
    frame = pd.read_parquet(archive / f"{site}_readings.parquet",
                            columns=["timestamp", "kwh", "state", "customer_id",
                                     "code_recovered"])
    frame["customer_id"] = frame["customer_id"].astype(str)
    frame = frame[(frame["customer_id"] == code)
                  & (frame["state"].isin(SUPPLYING_STATES))
                  & (~frame["code_recovered"].astype(bool))]
    frame = frame.drop(columns=["customer_id", "state", "code_recovered"])
    return _local(frame, SITE_OF_SUFFIX.get(site, site))


def _named_readings(raw: Path, names: tuple[str, ...], site_name: str) -> pd.DataFrame:
    """Supplying readings of a customer named on the reading itself, from the exports.

    For the loads that are not customers who pay and so have no code the archive is keyed
    on. The name is read off each reading rather than off the register, which is the whole
    point: a meter that was later given to a household carries that household's name on the
    readings it took for them, and so contributes nothing here.

    The exports carry the timestamp as UTC, which the suffix of the monthly ones states
    outright; it is moved onto the site's clock by :func:`_local`, as every other series
    the model indexes by the hour is.
    """
    wanted = {name.strip().lower() for name in names}
    columns = ["heartbeat_end", "meter/customer/name", "state", "kilowatt_hours"]
    frames = []
    for path in sorted(raw.glob("sparkmeter_readings_daily_*.csv")):
        try:
            frame = pd.read_csv(path, usecols=columns, low_memory=False)
        except ValueError:                   # an export without these columns
            continue
        label = frame["meter/customer/name"].astype(str).str.strip().str.lower()
        frame = frame[label.isin(wanted)]
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["timestamp", "kwh"])
    out = pd.concat(frames, ignore_index=True)
    out = out[out["state"].isin(SUPPLYING_STATES)]
    stamp = out["heartbeat_end"].astype(str).str.replace("+00:00", "", regex=False)
    out["timestamp"] = pd.to_datetime(stamp.str.replace("T", " ", regex=False),
                                      errors="coerce")
    out = out.dropna(subset=["timestamp"])
    out = out.rename(columns={"kilowatt_hours": "kwh"})[["timestamp", "kwh"]]
    return _local(out, site_name)


def hourly_energy(frame: pd.DataFrame) -> pd.Series:
    """Hourly energy [kWh], each reading laid over the interval it actually covers.

    A reading is the energy accumulated since the previous one, so it belongs to the hours
    that interval spans and not to the hour its timestamp falls in. Nearly all of them cover
    a quarter of an hour and the distinction is immaterial; the few that cover several hours
    are what makes it matter, and dropping those into one hour invented a night-time peak.
    """
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp")
    gaps = (frame["timestamp"].diff().dt.total_seconds()
            .fillna(DEFAULT_PERIOD_S).clip(lower=60.0))
    totals: dict[pd.Timestamp, float] = {}
    for end, kwh, seconds in zip(frame["timestamp"], frame["kwh"], gaps):
        if not (kwh > 0) or seconds > MAX_PERIOD_H * 3600.0:
            continue
        start = end - pd.Timedelta(seconds=seconds)
        hour = start.floor("h")
        while hour < end:
            following = hour + pd.Timedelta(hours=1)
            share = (min(end, following) - max(start, hour)).total_seconds() / seconds
            totals[hour] = totals.get(hour, 0.0) + kwh * share
            hour = following
    if not totals:
        return pd.Series(dtype=float)
    return pd.Series(totals).sort_index()


def class_profiles(archive: Path, raw: Path | None = None) -> pd.DataFrame:
    """Hourly shape, daily energy and daily spread for each class with data."""
    rows = {}
    for klass, spec in METERS.items():
        shapes, daily, spreads, kept = [], [], [], []
        sources = [(code, lambda c=code: _customer_readings(archive, c))
                   for code in spec.get("codes", ())]
        if raw is not None:
            sources += [(site, lambda n=names, s=site: _named_readings(raw, n, s))
                        for site, names in spec.get("names_by_site", {}).items()]
        for label, load in sources:
            result = _one_record(load())
            if result is None:
                continue
            shape, mean_day, spread = result
            shapes.append(shape)
            daily.append(mean_day)
            spreads.append(spread)
            kept.append(label)
        if not shapes:
            continue
        mean_shape = pd.concat(shapes, axis=1).mean(axis=1)
        mean_shape = mean_shape / float(mean_shape.sum())
        energy = float(np.mean(daily))
        rows[klass] = {
            **{str(hour): float(mean_shape.get(hour, 0.0) * energy) for hour in HOURS},
            "kwh_per_day": energy,
            # Day to day, within one use. The median across the records, as the productive
            # classes do, so that one erratic building does not set the class's variability.
            "daily_cv": float(np.median(spreads)) if spreads else 0.0,
            # And how much the records differ from one another, which is a different thing
            # and is reported rather than simulated: it says how firmly the class's level is
            # known, and for the places of worship it is wide because one of the four is a
            # very small church drawing a fifteenth of what the largest does.
            "between_cv": (float(np.std(daily) / energy)
                           if len(daily) > 1 and energy else 0.0),
            "n_meters": len(kept),
            "meters": " ".join(kept),
            "category": spec["category"],
            "billable": bool(spec["billable"]),
            "on_network": bool(spec["on_network"]),
        }
    return pd.DataFrame(rows).T.rename_axis("community_class")


def _one_record(frame: pd.DataFrame) -> tuple[pd.Series, float, float] | None:
    """One record's normalised hourly shape, its mean day, and its day-to-day spread.

    The spread is that of this one use across its own days, which is what the simulator
    needs: it scales each simulated day by a draw of that width, so that repeating a mean
    day does not flatten the peaks a storage sizing is most sensitive to. Measured between
    buildings instead -- which is what this returned before -- it answered a different
    question entirely, how much one place of worship differs from another, and handed it to
    the simulator as though a single building swung that far from Tuesday to Wednesday. The
    productive calibration has always measured it per customer; this now matches.
    """
    if frame.empty or float(frame["kwh"].sum()) <= MIN_KWH:
        return None
    hourly = hourly_energy(frame)
    if hourly.empty:
        return None
    days = hourly.resample("D").sum()
    days = days[days > 0.01]              # days the use was not used say nothing of it
    if len(days) < MIN_DAYS:
        return None
    shape = hourly.groupby(hourly.index.hour).mean().reindex(HOURS, fill_value=0.0)
    total = float(shape.sum())
    if total <= 0:
        return None
    mean_day = float(days.mean())
    spread = float(days.std() / mean_day) if mean_day > 0 else 0.0
    return shape / total, mean_day, spread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True,
                        help="directory holding the harmonised meter archive")
    parser.add_argument("--raw", type=Path, default=None,
                        help="directory holding the operator's meter exports, for the "
                             "meters that are not customers and have no code")
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    args = parser.parse_args(argv)

    profiles = class_profiles(args.archive, args.raw)
    if profiles.empty:
        print("no class carries enough metered energy to calibrate")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    destination = args.out / "community_class_profiles.csv"
    profiles.to_csv(destination)
    print(f"written {destination}")
    for klass, row in profiles.iterrows():
        paid = "billed" if row["billable"] else "unbilled"
        where = "on the network" if row["on_network"] else "at the plant"
        print(f"  {klass}: {row['kwh_per_day']:.3f} kWh/day from {int(row['n_meters'])} "
              f"records [{row['meters']}], day-to-day spread {row['daily_cv']:.2f}, "
              f"between records {row['between_cv']:.2f} ({paid}, {where})")
    missing = sorted(set(METERS) - set(profiles.index))
    for klass in missing:
        print(f"  {klass}: no metered energy; it stays a use to be declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
