r"""Harmonise the operator's monthly meter exports into one archive per site.

The archive this writes, ``data/demand/{sam,gbo}_meter_readings.parquet``, is what every
calibration in this package reads: the household segmentation, the productive classes, the
community classes and the archetype shapes all begin here. It had been produced outside the
repository and copied in, which left the one input nothing could regenerate. This closes
that gap, so that extending the record by a month is a command rather than a transfer.

Three things have to be got right, and each of them is silent when it is got wrong.

*The clock.* The exports timestamp each reading with an explicit UTC offset. The archive
carries site local time, which is an hour ahead, and the two are told apart by nothing in
the file itself: both are plain numbers in a column. Shifted forward by that hour, this
reproduces the archive it replaces to the last digit, and the check is run rather than
asserted -- see ``--verify``. An hour is also the error a storage sizing is least able to
absorb, which is why it is worth a check of its own.

*The codes.* A reading belongs to the code that held the meter when it was taken. A
customer code is four digits and a site, and the exports do not always carry one: a
trailing space, a typo, an empty field. A code that reads as a customer code once its
spaces are removed and its letters raised is that code, since it is what the export held
at the time. Only a code that cannot be read so is recovered, through the meter serial,
and then to the meter's owner in the register. Recovery never overwrites a reading already
observed under a clean code, because a recovered attribution is weaker evidence than a
recorded one.

The order matters because the register holds the owner of today, not the owner of the day
the reading was taken. Recovered through the register first, the readings of two Gbowele
households who exchanged their meters on 11 May 2026 went to the wrong one: from December
2025 the export records one meter under 0173GBO and the other under " 0074GBO", with a
leading space, and the register, written after the exchange, gives that second meter to
0173GBO. Its readings were attributed to 0173GBO, which already had readings of its own at
the same quarter-hours, and so were lost: 0074GBO had no reading from 17 December 2025 to
11 May 2026. At Samionta a meter recorded "0048SAM " from June 2024 and "0097SAM" from February
2025, and the register gives it to the second, so eight months of the first were the
second's.

A reading under a test code belongs to no customer. During the test period of 2025, eleven
Gbowele meters were installed under the codes "test1" to "test11", and recovered through
the register they went to whoever holds the meter today: six customers each received up to
eleven months of a bench meter's record, and with it a first reading in January 2025.

What those rules leave standing is worth saying, because it is not nothing. About one
reading in ninety carries a perfectly legible code whose meter the register assigns to
somebody else: 41 802 of 3 830 096 at Samionta and 52 981 of 4 962 930 at Gbowele, on the
exports as of November 2026. Some are pairs of customers who exchanged meters, where the
export holds the assignment in force at the time and the register only the one in force
today; others are a code field left behind when a meter was reassigned. Nothing in either
file tells the two apart, so a legible code is kept as recorded and the recovery reaches
the unreadable ones alone. A household whose meter changed hands therefore carries a few
weeks of its neighbour's load.

*What is not a customer.* The plant's own meters and the operator's bench meters record real
power that nobody is billed for, and counting them as customers inflates the demand the
whole calibration is fitted to. They are dropped here by meter type, from the operator's
register of meters, rather than by name: meters move, and the serial the register shows
today says nothing about whose load it recorded two years ago. For the same reason the type
does not override a customer. A code the customer roster or the operator's field census
knows is a customer whatever the type of the meter its readings came through: 0193GBO, a
productive user of the roster, has recorded since December 2025 on a meter the register
types as a bench meter, and 0004SAM, a place of worship, recorded three weeks of July 2024
on the meter that later served the plant room. The exclusion by type stays for the codes
neither source knows.

The exports and the register are the operator's and live outside this repository, and so
does the field census, which holds personal data and of which only the code column is
read; all three are named on the command line rather than assumed::

    python -m microgrid_expansion.demand.build_meter_archive \
        --exports <directory of monthly exports> \
        --meters <the operator's register of meters> \
        --census Samionta=<workbook> --census Gbowele=<workbook>

Without the census, the codes it typed that the repository keeps, in
``data/demand/archive_customers.csv``, stand in for it.
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pcsv

from ..paths import DEMAND_DIR
# Each reading over its own period. Read at generation by the household segmentation, so it
# lives in a module of its own, which the cache key hashes; named here for the readers that
# have always found it in this one.
from .readings import FIRST_PERIOD_S, LONGEST_PERIOD_S, timed_readings, with_periods  # noqa: F401

#: A customer code: four digits and the site it belongs to.
VALID_CODE = re.compile(r"^0\d{3}(SAM|GBO)$")
#: The codes the operator gave the bench meters of the test period: "test1", "test 3".
TEST_CODE = re.compile(r"^\s*test\s*\d*\s*$", re.IGNORECASE)

#: Meters that record load nobody is invoiced for, by the type the operator's register
#: gives them: the plant's supply, the air conditioning of the room the inverters stand in,
#: and the bench the operator tests on. A code the roster or the census knows is a
#: customer on any of them.
NOT_A_CUSTOMER = ("PWH METER", "PWH AC", "INDUSTRIEL TEST")

#: The columns an export is read for, and what they are called afterwards. Everything else
#: in a thirty-column export is either constant, derived, or about the wallet.
COLUMNS = {"heartbeat_end": "timestamp", "meter/customer/code": "code_as_recorded",
           "true_power_avg": "power_W", "meter/serial": "meter_serial"}

#: Site local time, ahead of the offset the exports carry.
FROM_UTC = pd.Timedelta(hours=1)

SITES = {"SAM": "sam_meter_readings.parquet", "GBO": "gbo_meter_readings.parquet"}


def read_export(path: Path) -> pd.DataFrame:
    """One monthly export, in whichever of the two layouts it was written.

    The older exports carry twenty-seven columns and an ISO timestamp with its offset
    spelled out; the newer ones carry thirty-two, adding the wallet balances, and leave the
    timestamp bare. Some older files have no newline after the header, so the last column
    name runs into the first value of the first row. The header is therefore read as text
    and trimmed to the width of the first data row, rather than trusted.
    """
    with open(path) as handle:
        header = handle.readline().rstrip("\n")
        first_row = handle.readline().rstrip("\n")
    names = header.split(",")[:len(first_row.split(","))]
    for i, name in enumerate(names):
        if name.startswith("_uncertain_metadata"):
            names[i] = "_uncertain_metadata"

    types = {name: pa.string() for name in names}
    types["true_power_avg"] = pa.float64()
    table = pcsv.read_csv(
        path,
        read_options=pcsv.ReadOptions(column_names=names, skip_rows=1, block_size=1 << 26),
        convert_options=pcsv.ConvertOptions(include_columns=list(COLUMNS),
                                            column_types=types,
                                            include_missing_columns=True),
        # A row the parser cannot split is one row of one meter, and stopping the archive
        # for it would be worse than leaving it out.
        parse_options=pcsv.ParseOptions(invalid_row_handler=lambda row: "skip"))
    frame = table.to_pandas().rename(columns=COLUMNS)
    stamped = (frame["timestamp"].str.replace("T", " ", regex=False)
                                 .str.replace("+00:00", "", regex=False))
    frame["timestamp"] = pd.to_datetime(stamped, errors="coerce")
    return frame


def owners_and_exclusions(register: Path) -> tuple[dict[str, str], set[str]]:
    """Who each meter belongs to, and which meters are not a customer's."""
    meters = pd.read_csv(register, encoding="utf-8-sig")
    meters["customer_code"] = meters["customer_code"].astype(str).str.strip().str.upper()
    meters["meter_type"] = meters["meter_type"].astype(str).str.strip().str.upper()
    owners = meters[meters["customer_code"].str.match(VALID_CODE)].set_index(
        "meter_serial")["customer_code"].to_dict()
    excluded = set(meters.loc[meters["meter_type"].isin(NOT_A_CUSTOMER), "meter_serial"])
    return owners, excluded


def known_customers(census: dict[str, Path] | None = None) -> frozenset[str]:
    """The codes the customer roster or the operator's field census knows.

    The census is read for its code column alone, through the reader the connection curves
    use. Without it, the codes the census typed that the repository keeps stand in for it.
    """
    from .build_connection_curves import ARCHIVE_CUSTOMERS, read_census

    codes = set(pd.read_parquet(DEMAND_DIR / "customer_info.parquet").customer_code)
    if census:
        for name, path in census.items():
            codes |= set(read_census(path, name)[0].customer_code)
    elif ARCHIVE_CUSTOMERS.exists():
        kept = pd.read_csv(ARCHIVE_CUSTOMERS, dtype=str, keep_default_na=False)
        codes |= set(kept.loc[kept.source == "census", "customer_code"])
    return frozenset(codes)


def harmonise(frames: list[pd.DataFrame], site: str, owners: dict[str, str],
              excluded: set[str], known: frozenset[str] = frozenset()) -> pd.DataFrame:
    """Every export of one site, as one table of readings on the site's own clock.

    ``known`` holds the codes that are customers whatever their meter's type.
    """
    readings = pd.concat(frames, ignore_index=True)
    readings = readings[readings["timestamp"].dt.year > 2000]
    recorded = readings["code_as_recorded"].fillna("")
    readings = readings[~recorded.str.match(TEST_CODE)]

    recorded = readings["code_as_recorded"].fillna("")
    legible = recorded.str.match(VALID_CODE)
    clean = readings[legible].assign(customer_code=recorded[legible])

    unreadable = readings[~legible].copy()
    squeezed = (unreadable["code_as_recorded"].fillna("")
                .str.replace(r"\s+", "", regex=True).str.upper())
    owner = unreadable["meter_serial"].map(owners)
    unreadable["customer_code"] = squeezed.where(squeezed.str.match(VALID_CODE), owner)
    unreadable = unreadable[unreadable["customer_code"].notna()
                            & unreadable["customer_code"].str.endswith(site)]

    # A meter of a type that is nobody's still records a customer's load under that
    # customer's code.
    clean = clean[~clean["meter_serial"].isin(excluded) | clean["customer_code"].isin(known)]
    unreadable = unreadable[~unreadable["meter_serial"].isin(excluded)
                            | unreadable["customer_code"].isin(known)]

    clean = clean.drop_duplicates(["customer_code", "timestamp"], keep="last")
    unreadable = unreadable.drop_duplicates(["customer_code", "timestamp"], keep="last")
    # A reading whose code had to be recovered never displaces one that was recorded.
    seen = pd.MultiIndex.from_frame(clean[["customer_code", "timestamp"]])
    recovered = pd.MultiIndex.from_frame(unreadable[["customer_code", "timestamp"]])
    unreadable = unreadable[~recovered.isin(seen)]

    out = pd.concat([clean, unreadable], ignore_index=True)
    out["timestamp"] = out["timestamp"] + FROM_UTC
    out = out[["timestamp", "customer_code", "power_W"]]
    out["customer_code"] = out["customer_code"].astype(str)
    return out.sort_values(["timestamp", "customer_code"]).reset_index(drop=True)


def reproduces(built: pd.DataFrame, existing: Path) -> str:
    """How much of the archive being replaced comes back unchanged, in one line.

    Reported rather than asserted. A rebuild that differs is not necessarily wrong -- a
    month arriving late, or a code recovered that was not before, both change it honestly --
    but a rebuild that differs *and says nothing* is how a calibration silently moves.
    """
    if not existing.exists():
        return "no archive to compare with"
    before = pd.read_parquet(existing)
    a = built.set_index(["customer_code", "timestamp"])["power_W"].sort_index()
    b = before.set_index(["customer_code", "timestamp"])["power_W"].sort_index()
    shared = a.index.intersection(b.index)
    apart = (a.loc[shared] - b.loc[shared]).abs()
    return (f"{len(shared):,} of {len(b):,} readings found again, "
            f"{int((apart <= 1e-9).sum()):,} of them identical "
            f"(largest difference {apart.max() if len(shared) else 0:.3f} W); "
            f"{len(b.index.difference(a.index)):,} gone, "
            f"{len(a.index.difference(b.index)):,} new")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", type=Path, required=True,
                        help="directory of the operator's monthly meter exports")
    parser.add_argument("--meters", type=Path, required=True,
                        help="the operator's register of meters, for code recovery")
    parser.add_argument("--census", action="append", default=[], metavar="SITE=WORKBOOK",
                        help="the operator's field census of a site, for the codes it "
                             "knows; once per reference site. Only the code column is read")
    parser.add_argument("--out", type=Path, default=DEMAND_DIR)
    parser.add_argument("--verify", action="store_true",
                        help="rebuild and report against the archive, writing nothing")
    args = parser.parse_args(argv)

    owners, excluded = owners_and_exclusions(args.meters)
    census = {name: Path(path) for name, _, path in
              (entry.partition("=") for entry in args.census)}
    known = known_customers(census)
    print(f"{len(known)} codes known to the roster or the census"
          + ("" if census else " (the census as the repository keeps it)"))
    for site, filename in SITES.items():
        started = time.perf_counter()
        pattern = f"sparkmeter_readings_daily_{site.lower()}_*.csv"
        files = sorted(args.exports.glob(pattern))
        if not files:
            print(f"{site}: no export matches {pattern} in {args.exports}")
            continue
        print(f"[{site}] {len(files)} exports", flush=True)
        frames = []
        for path in files:
            at = time.perf_counter()
            frames.append(read_export(path))
            print(f"   {path.name}: {len(frames[-1]):,} rows "
                  f"({time.perf_counter() - at:.1f} s)", flush=True)

        built = harmonise(frames, site, owners, excluded, known)
        target = args.out / filename
        print(f"   {len(built):,} readings, {built.customer_code.nunique()} customers, "
              f"{built.timestamp.min()} .. {built.timestamp.max()}")
        print(f"   against the archive: {reproduces(built, target)}")
        if args.verify:
            print("   nothing written (--verify)")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            built.to_parquet(target, index=False)
            print(f"   written {target}")
        print(f"   {time.perf_counter() - started:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
