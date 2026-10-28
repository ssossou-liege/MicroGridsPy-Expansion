r"""Equipment prices, read off the operator's own procurement budget.

The capacity costs the sizing annualises are prices quoted on the Beninese market, and they
were quoted once. A procurement budget settles them again, item by item, with the quantities
the operator is actually buying --- so the figures here are not a market survey but what one
developer pays, which is the quantity a sizing of that developer's project needs.

Two price columns run side by side in the budget and they are not interchangeable. The
offshore column is the supplier's price at the port of departure, and the budget's own
request for quotation says what it leaves out: shipping, duty, the inland leg, and --- in so
many words --- batteries and inverters, which are priced separately. The local column is
what the same item costs delivered in Benin. The settings carry prices quoted on the
Beninese market, so the local column is the one that answers them, and it is the one read
here. The offshore column is reported beside it because the gap between the two is the cost
of getting the equipment there, which is a figure worth seeing even when nothing uses it.

What this does *not* cover, and the sizing therefore still understates: the mounting
structure, the direct-current cabling and connectors, and every hour of labour. Those sit in
the budget too and are reported, so that widening the basis is a decision someone takes
rather than an omission nobody noticed.

The script is deterministic given its inputs and writes nothing it is not asked to.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

#: Rows of the bill of quantities, by what they price and the capacity one unit carries.
#: Named by the designation the budget uses, matched on a distinctive fragment so that a
#: re-export with a reworded line still finds them.
ITEMS = {
    "photovoltaic": (
        ("Risen RSM132-8-650", 0.650, "kW"),
        ("LONGI LR5-72HBD-550", 0.550, "kW"),
    ),
    "battery": (
        ("DEYE SE-G10.2", 10.24, "kWh"),
        ("BYD LV Flex", 5.0, "kWh"),
    ),
    "inverter": (
        ("SUN-12K-SG04LP3", 12.0, "kW"),
        ("SUN-20K-SG05LP3", 20.0, "kW"),
    ),
    "generator": (
        ("Groupe électrogène 20 kVA", 20.0, "kVA"),
        ("Groupe électrogène 30 kVA", 30.0, "kVA"),
        ("Groupe électrogène 66 kVA", 66.0, "kVA"),
        ("Groupe électrogène 80 kVA", 80.0, "kVA"),
    ),
}

#: What the array needs beyond its modules, which the capacity cost does not carry today.
#: Allocated over the photovoltaic capacity the same budget buys.
ARRAY_EXTRAS = ("Structure métallique de fixation", "Câble solaire 1x6",
                "Connecteur module solaire MC4")

#: Columns of the bill of quantities, which carries two header rows.
SHEET = "BoQ GRIDS (SS)"
HEADER_ROW = 4
COL_DESIGNATION, COL_UNIT, COL_QUANTITY, COL_LOCAL, COL_OFFSHORE = 1, 6, 7, 8, 9


def read_rows(budget: Path) -> list[dict]:
    """Every priced line of the bill of quantities, as plain records."""
    import pandas as pd

    frame = pd.read_excel(budget, sheet_name=SHEET, header=None)
    rows = []
    for position in range(HEADER_ROW + 1, len(frame)):
        line = frame.iloc[position]
        designation = str(line[COL_DESIGNATION])
        if designation == "nan":
            continue
        rows.append({
            "designation": " ".join(designation.split()),
            "unit": str(line[COL_UNIT]),
            "quantity": _number(line[COL_QUANTITY]),
            "local_xof": _number(line[COL_LOCAL]),
            "offshore_xof": _number(line[COL_OFFSHORE]),
        })
    return rows


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number           # NaN is not a price


def _match(rows: list[dict], fragment: str) -> dict | None:
    wanted = " ".join(fragment.split()).lower()
    for row in rows:
        if wanted in row["designation"].lower():
            return row
    return None


def unit_prices(rows: list[dict], xof_per_usd: float) -> dict:
    """Price per kilowatt, kilowatt-hour or kilovolt-ampere, weighted by what is bought.

    Weighted by *capacity* and not by line, because a budget holding two hundred of one
    module and forty of another is describing a fleet, and the price a sizing should carry
    is the price of the fleet's next kilowatt.
    """
    out = {}
    for family, entries in ITEMS.items():
        found = []
        for fragment, capacity, unit in entries:
            row = _match(rows, fragment)
            if row is None or not row["quantity"]:
                continue
            bought = row["quantity"] * capacity
            found.append({
                "designation": row["designation"], "unit": unit,
                "capacity_each": capacity, "quantity": row["quantity"],
                "capacity_bought": bought,
                "local_xof_per_unit": (row["local_xof"] / capacity
                                       if row["local_xof"] else None),
                "offshore_xof_per_unit": (row["offshore_xof"] / capacity
                                          if row["offshore_xof"] else None),
            })
        priced = [f for f in found if f["local_xof_per_unit"]]
        total = sum(f["capacity_bought"] for f in priced)
        weighted = (sum(f["local_xof_per_unit"] * f["capacity_bought"] for f in priced)
                    / total) if total else None
        out[family] = {
            "lines": found,
            "capacity_bought": total,
            "local_xof_per_unit": weighted,
            "local_usd_per_unit": weighted / xof_per_usd if weighted else None,
            "unit": entries[0][2],
        }
    return out


def array_extras(rows: list[dict], photovoltaic_kw: float,
                 xof_per_usd: float) -> dict:
    """What the array costs beyond its modules, per kilowatt of that array."""
    out = {}
    for fragment in ARRAY_EXTRAS:
        total = 0.0
        for row in rows:
            if (" ".join(fragment.split()).lower() in row["designation"].lower()
                    and row["local_xof"] and row["quantity"]):
                total += row["local_xof"] * row["quantity"]
        if total and photovoltaic_kw:
            out[fragment] = {"xof_per_kw": total / photovoltaic_kw,
                             "usd_per_kw": total / photovoltaic_kw / xof_per_usd}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=Path, required=True,
                        help="the operator's procurement workbook")
    parser.add_argument("--xof-per-usd", type=float, default=600.0,
                        help="the rate the budget states on its summary sheet")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the derived prices here as well as printing them")
    args = parser.parse_args(argv)

    rows = read_rows(args.budget)
    prices = unit_prices(rows, args.xof_per_usd)
    extras = array_extras(rows, prices["photovoltaic"]["capacity_bought"],
                          args.xof_per_usd)

    print(f"{len(rows):,} priced lines read, at {args.xof_per_usd:.0f} XOF to the dollar\n")
    for family, block in prices.items():
        print(f"{family} [{block['unit']}]")
        for line in block["lines"]:
            local = line["local_xof_per_unit"]
            offshore = line["offshore_xof_per_unit"]
            print(f"   {line['designation'][:46]:48s} "
                  f"{line['quantity']:>7,.0f} x {line['capacity_each']:>6.2f} "
                  f"local {('%9.0f' % local) if local else '        -'} XOF  "
                  f"offshore {('%9.0f' % offshore) if offshore else '        -'}")
        if block["local_xof_per_unit"]:
            print(f"   -> {block['local_xof_per_unit']:,.0f} XOF per {block['unit']} "
                  f"= {block['local_usd_per_unit']:,.2f} USD, over "
                  f"{block['capacity_bought']:,.0f} {block['unit']} bought")
        print()

    if extras:
        print("beyond the modules, per kW of array, at local prices:")
        for name, block in extras.items():
            print(f"   {name[:46]:48s} {block['xof_per_kw']:>9,.0f} XOF/kW "
                  f"= {block['usd_per_kw']:>7,.2f} USD/kW")
        total = sum(b["xof_per_kw"] for b in extras.values())
        print(f"   {'total':48s} {total:>9,.0f} XOF/kW "
              f"= {total / args.xof_per_usd:>7,.2f} USD/kW")

    if args.json:
        args.json.write_text(json.dumps({"prices": prices, "array_extras": extras,
                                         "xof_per_usd": args.xof_per_usd}, indent=2),
                             encoding="utf-8")
        print(f"\nwritten {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
