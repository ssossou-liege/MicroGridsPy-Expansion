r"""Equipment prices, read off the operator's own procurement budget.

The capacity costs the sizing annualises were prices quoted once on the Beninese market. A
procurement budget settles them again, item by item, with the quantities the operator is
actually buying --- so the figures here are not a market survey but what one developer pays,
which is the quantity a sizing of that developer's project needs.

Two price columns run side by side in the budget and they are not interchangeable. The
offshore column is the supplier's price at the port of departure, and the budget's own
request for quotation says what it leaves out: shipping, duty and the inland leg. The local
column is what the same item costs bought in Benin, with the importer's margin in it.

Which of the two answers the model is not a matter of taste, and the payment ledger settles
it: four fifths of the equipment is invoiced by manufacturers outside the customs union, and
duty and freight are paid as separate lines. This operator buys offshore and lands the goods
itself. So the price it faces is the offshore price plus the landing, which is what this
script reports as the landed price and what the settings carry. The local column is reported
beside it because it is what a developer without that capacity would pay, and the gap
between the two --- a factor of one and a half to three and a half --- is worth seeing.

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
#: re-export with a reworded line still finds them. A fourth field set to ``False`` means
#: the line is read and printed but kept out of the weighted price: see the generators.
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
    # Only the smallest set is weighted. The budget buys four ratings from 20 to 80 kVA
    # and their offshore prices fall by half per kVA across that range, which is a real
    # economy of scale and not noise; the model's catalogue holds 10, 15 and 20 kVA units,
    # so a figure weighted over the large sets would price a village's standby generator
    # at the cost of a town's. The others are printed because that scale effect is worth
    # seeing, and because a catalogue of larger units would want them.
    # The designations below are the budget's own, and the budget is written in French:
    # accents intentional, since a fragment that drops them matches nothing.
    "generator": (
        ("Groupe électrogène 20 kVA", 20.0, "kVA"),
        ("Groupe électrogène 30 kVA", 30.0, "kVA", False),
        ("Groupe électrogène 66 kVA", 66.0, "kVA", False),   # accents intentional
        ("Groupe électrogène 80 kVA", 80.0, "kVA", False),
    ),
}

#: What the array needs beyond its modules. Allocated over the photovoltaic capacity the
#: same budget buys, and added to the module price, since the sizing spends one figure per
#: kilowatt of array. The budget's own designations: accents intentional.
ARRAY_EXTRAS = ("Structure métallique de fixation", "Câble solaire 1x6",
                "Connecteur module solaire MC4")

#: Duty and freight as a share of an imported invoice, measured on the payment ledger by
#: ``allocation.landing_uplift``. Stated here so that the script runs without the ledger and
#: says which figure it used; pass ``--ledger`` to measure it again from the records.
LANDING_UPLIFT = 0.0956

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


def _weighted(found: list[dict], basis: str) -> tuple[float | None, float]:
    """One price per unit of capacity, weighted by the capacity each line buys.

    Weighted by *capacity* and not by line, because a budget holding seven hundred of one
    module and forty of another is describing a fleet, and the price a sizing should carry
    is the price of the fleet's next kilowatt. A line the budget leaves unpriced on this
    basis drops out, and the weighting is taken over the rest.
    """
    priced = [f for f in found if f[f"{basis}_xof_per_unit"] and f["weighed"]]
    capacity = sum(f["capacity_bought"] for f in priced)
    if not capacity:
        return None, 0.0
    return (sum(f[f"{basis}_xof_per_unit"] * f["capacity_bought"] for f in priced)
            / capacity), capacity


def unit_prices(rows: list[dict], xof_per_usd: float,
                uplift: float = LANDING_UPLIFT) -> dict:
    """Price per kilowatt, kilowatt-hour or kilovolt-ampere, on each of the three bases."""
    out = {}
    for family, entries in ITEMS.items():
        found = []
        for entry in entries:
            fragment, capacity, unit = entry[:3]
            row = _match(rows, fragment)
            if row is None or not row["quantity"]:
                continue
            found.append({
                "designation": row["designation"], "unit": unit,
                "weighed": entry[3] if len(entry) > 3 else True,
                "capacity_each": capacity, "quantity": row["quantity"],
                "capacity_bought": row["quantity"] * capacity,
                "local_xof_per_unit": (row["local_xof"] / capacity
                                       if row["local_xof"] else None),
                "offshore_xof_per_unit": (row["offshore_xof"] / capacity
                                          if row["offshore_xof"] else None),
            })
        local, local_capacity = _weighted(found, "local")
        offshore, offshore_capacity = _weighted(found, "offshore")
        landed = offshore * (1.0 + uplift) if offshore else None
        out[family] = {
            "lines": found,
            "unit": entries[0][2],
            "capacity_bought": local_capacity,
            "capacity_bought_offshore": offshore_capacity,
            "local_xof_per_unit": local,
            "local_usd_per_unit": local / xof_per_usd if local else None,
            "offshore_xof_per_unit": offshore,
            "offshore_usd_per_unit": offshore / xof_per_usd if offshore else None,
            "landed_xof_per_unit": landed,
            "landed_usd_per_unit": landed / xof_per_usd if landed else None,
        }
    return out


def array_extras(rows: list[dict], photovoltaic_kw: float, xof_per_usd: float,
                 uplift: float = LANDING_UPLIFT) -> dict:
    """What the array costs beyond its modules, per kilowatt of that array.

    Reported on the same two bases as the modules. The structure is imported like them ---
    the budget's supplier is a Chinese manufacturer the ledger also pays --- so the landed
    figure is the one that belongs beside a landed module price.
    """
    out = {}
    for fragment in ARRAY_EXTRAS:
        local = offshore = 0.0
        for row in rows:
            if " ".join(fragment.split()).lower() not in row["designation"].lower():
                continue
            if not row["quantity"]:
                continue
            local += (row["local_xof"] or 0.0) * row["quantity"]
            offshore += (row["offshore_xof"] or 0.0) * row["quantity"]
        if not photovoltaic_kw or not (local or offshore):
            continue
        landed = offshore * (1.0 + uplift) / photovoltaic_kw if offshore else None
        out[fragment] = {
            "local_xof_per_kw": local / photovoltaic_kw if local else None,
            "landed_xof_per_kw": landed,
            "landed_usd_per_kw": landed / xof_per_usd if landed else None,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=Path, required=True,
                        help="the operator's procurement workbook")
    parser.add_argument("--ledger", type=Path, default=None,
                        help="the allocation of funds, to measure the landing cost on "
                             "rather than taking the figure recorded here")
    parser.add_argument("--uplift", type=float, default=None,
                        help="duty and freight as a share of an imported invoice, if "
                             "neither the recorded figure nor the ledger is wanted")
    parser.add_argument("--xof-per-usd", type=float, default=607.37,
                        help="the rate the model's currency block states")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the derived prices here as well as printing them")
    args = parser.parse_args(argv)

    uplift, source = LANDING_UPLIFT, "recorded in this script"
    if args.ledger is not None:
        from .allocation import landing_uplift, ledger

        measured = landing_uplift(ledger(args.ledger))
        uplift = float(measured["uplift_on_imported"])
        source = (f"measured on {args.ledger.name}: duty "
                  f"{measured['duty_xof']:,.0f} + sea leg {measured['sea_leg_xof']:,.0f} "
                  f"over {measured['imported_xof']:,.0f} XOF imported")
    if args.uplift is not None:
        uplift, source = args.uplift, "given on the command line"

    rows = read_rows(args.budget)
    prices = unit_prices(rows, args.xof_per_usd, uplift)
    extras = array_extras(rows, prices["photovoltaic"]["capacity_bought"],
                          args.xof_per_usd, uplift)

    print(f"{len(rows):,} priced lines read, at {args.xof_per_usd:.2f} XOF to the dollar")
    print(f"landing adds {100 * uplift:.2f} % to an offshore invoice ({source})\n")
    for family, block in prices.items():
        print(f"{family} [{block['unit']}]")
        for line in block["lines"]:
            local, offshore = line["local_xof_per_unit"], line["offshore_xof_per_unit"]
            print(f"   {line['designation'][:44]:46s} "
                  f"{line['quantity']:>7,.0f} x {line['capacity_each']:>6.2f} "
                  f"local {('%9.0f' % local) if local else '        -'}  "
                  f"offshore {('%9.0f' % offshore) if offshore else '        -'} XOF"
                  f"{'' if line['weighed'] else '   (not weighed)'}")
        if block["landed_usd_per_unit"]:
            print(f"   -> landed {block['landed_xof_per_unit']:>9,.0f} XOF "
                  f"= {block['landed_usd_per_unit']:>7,.2f} USD per {block['unit']}, "
                  f"over {block['capacity_bought_offshore']:,.0f} {block['unit']} bought")
        if block["local_usd_per_unit"]:
            print(f"      local  {block['local_xof_per_unit']:>9,.0f} XOF "
                  f"= {block['local_usd_per_unit']:>7,.2f} USD, which this operator "
                  f"does not pay")
        print()

    if extras:
        print("beyond the modules, per kW of array:")
        for name, block in extras.items():
            landed = block["landed_usd_per_kw"]
            print(f"   {name[:44]:46s} landed {block['landed_xof_per_kw']:>8,.0f} XOF/kW"
                  f" = {landed:>6,.2f} USD/kW")
        total = sum(b["landed_xof_per_kw"] for b in extras.values()
                    if b["landed_xof_per_kw"])
        print(f"   {'total':46s} landed {total:>8,.0f} XOF/kW "
              f"= {total / args.xof_per_usd:>6,.2f} USD/kW")
        # What the settings carry per kilowatt of array, which is the sum of the two: the
        # sizing spends one figure per kilowatt and the structure is not optional.
        module = prices["photovoltaic"]["landed_xof_per_unit"]
        if module:
            array = module + total
            print(f"\n   {'array, modules and the rest of it':46s} "
                  f"landed {array:>8,.0f} XOF/kW = {array / args.xof_per_usd:>6,.2f} USD/kW")

    if args.json:
        args.json.write_text(json.dumps({"prices": prices, "array_extras": extras,
                                         "xof_per_usd": args.xof_per_usd,
                                         "landing_uplift": uplift,
                                         "landing_uplift_source": source}, indent=2),
                             encoding="utf-8")
        print(f"\nwritten {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
