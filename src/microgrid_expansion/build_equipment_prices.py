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

Beside each family of units the script reports the balance of plant that scales with it:
what the array needs beyond its modules and what the pack needs beyond its cells. Those are
reported separately and then added, because the sizing spends one figure per kilowatt and
one per kilowatt-hour, and a balance of plant left out of them is a discount the sizing
grants itself. No such basket exists for the inverter: the budget prices nothing per
kilowatt of conversion that the array's or the pack's basket does not already carry, and
saying so here is better than leaving the absence to look like an oversight.

What this does *not* cover, and the sizing therefore still understates:

* *every hour of labour.* The operator's turnkey construction contract covers it, which
  makes it a cost per site and not a cost per kilowatt. It belongs to the project perimeter
  that the manuscript prices, not to a capacity cost the sizing multiplies.
* *what is bought once per site*, listed in ``NOT_PROPORTIONAL`` below with the reason. A
  plant twice the size buys one of each of them, so allocating them over capacity would
  make the second kilowatt pay for the first one's cabinet.

The script is deterministic given its inputs and writes nothing it is not asked to.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .paths import COSTS_DIR

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
#:
#: The second group is the direct side's protection and distribution, which the structure
#: and the cable do not carry: a string needs its fuse, its holder and its surge arrester,
#: the strings come together in a board sized by their number, and every module frame is
#: earthed. All of it is bought by the string or by the module, so all of it scales with the
#: array and none of it with the site. The budget's own designations: accents intentional.
ARRAY_EXTRAS = ("Structure métallique de fixation", "Câble solaire 1x6",
                "Connecteur module solaire MC4",
                # Protection of the strings; accents intentional.
                "Fusible 25A-1000VDC", "Porte fusibles 2P 25 A", "Parafoudre PV_T2",
                # Where the strings come together; accents intentional.
                "Coffret électrique de 6 modules", "Coffret électrique de 18 modules",
                "Coffret électrique de 30 modules",
                # The comb, and the frames' earth; accents intentional.
                "Peigne électrique horizontal 8 modules",
                "Boulon de mise à la terre des modules PV")

#: What the pack needs beyond its cells, allocated over the storage capacity the budget
#: buys. A pack is racked, its modules are bridged by busbars on their supports, its
#: direct side is broken by a fused isolator, and it is wired to the converters in cable
#: sized by current with a lug at each end: one rack, one busbar and one run of cable per
#: so many kilowatt-hours, which is what makes the basket proportional.
#:
#: The lugs are entered by section rather than by what they terminate, because the budget
#: does not say: the sections from 16 to 95 mm² are the battery cable's and are taken here,
#: while the 6 and 10 mm² lines are left out of both baskets since nothing in the budget
#: attaches them to the pack or to the array. One line of 16 mm² is excluded by name below,
#: being the network's and not the pack's. The budget's own designations, quoted as it
#: writes them: accents intentional.
BATTERY_EXTRAS = ("Rack de 06 batteries", "Busbars batterie",
                  "Support de fixation Busbar batterie", "BATFuse", "H07-VK",
                  # The lugs, by section; accents intentional.
                  "Cosse à sertir de 16", "Cosse à sertir de 25", "Cosse à sertir de 35",
                  "Cosse à sertir de 70", "Cosse à sertir de 95")

#: Balance of plant of the same budget that is deliberately *not* in either basket, with
#: the reason. These are read by no fragment above, and a test holds that.
#:
#: Everything here is bought once per site, whatever the plant's size: the battery
#: management unit, the cabinet and its copper, the alternating side's protection and
#: changeover, the supervision, the cameras, the lightning protection, the production
#: meters and the plant's own service equipment. A village with twice the array buys one of
#: each, so they are a cost per site and belong to the project perimeter beside the civil
#: works and the network, where the manuscript prices them.
#:
#: The charge controller is left out for a different reason: the budget prices the Victron
#: 250/100 at 25 000 XOF, a seventh of what the unit sells for anywhere, and a price that
#: cannot be right should not be carried into a sizing on the grounds that it is written
#: down. The budget's own designations: accents intentional.
NOT_PROPORTIONAL = ("Battery Box BMU BYD", "Armoire électrique", "Jeu de barre en cuivre",
                    # The cabinet's copper and the changeover; accents intentional.
                    "Support pour jeu de barres", "Barre de terre en cuivre",
                    "Inverseur de source manuel", "Cerbo GX", "GX Touch", "Caméra",
                    # Supervision, lightning, metering, service; accents intentional.
                    "Ensemble paratonnerre", "Compteurs powerhouse", "Nova",
                    "Controleur de charge 250V/100A Victron")

#: Lines a basket's fragment would otherwise catch and must not, matched the same way.
#: Only one is needed so far, and it is worth its own constant because it is the kind of
#: line a fragment catches silently: the budget prices a lug of 16 mm² for an M14 bolt at
#: twelve thousand pieces and 500 XOF, fourteen times the price of the same section for the
#: M6 to M10 bolts the pack's cable terminates in, and in a quantity that belongs to the
#: distribution network's connections rather than to any power plant. Left in, that one
#: line adds four fifths to the storage basket and is nearly half of what is left.
#: The budget's own wording: accents intentional.
EXCLUDED_FROM_EXTRAS = ("pour boulon M14",)

#: Units of the budget's own unit column that already express a price per unit of capacity,
#: by the capacity unit they match. A line so priced is taken at its own price instead of
#: having its total allocated over the fleet, and the distinction is not cosmetic: the
#: budget buys 550.4 kWc of mounting structure for 518.6 kW of modules, one site having
#: structure standing without modules on it, so allocating the structure's total over the
#: modules would charge every kilowatt of array six per cent too much for holding itself up.
PER_CAPACITY_UNITS = {"kW": ("kwp", "kwc"), "kWh": ("kwh",)}

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


def proportional_extras(rows: list[dict], fragments: tuple[str, ...], capacity: float,
                        unit: str, xof_per_usd: float,
                        uplift: float = LANDING_UPLIFT) -> dict:
    """What a capacity costs beyond its own units, per unit of that capacity.

    Reported on the same two bases as the units themselves. These items are imported like
    them --- the budget's suppliers are manufacturers the ledger also pays --- so the
    landed figure is the one that belongs beside a landed unit price.

    A line already priced per unit of capacity is taken at its own price; every other line
    has its total spread over the capacity the budget buys. Both come out as a price per
    unit of capacity, which is what the sizing multiplies.
    """
    per_capacity = PER_CAPACITY_UNITS.get(unit, ())
    barred = tuple(" ".join(x.split()).lower() for x in EXCLUDED_FROM_EXTRAS)
    out = {}
    for fragment in fragments:
        local = offshore = 0.0
        for row in rows:
            designation = row["designation"].lower()
            if " ".join(fragment.split()).lower() not in designation:
                continue
            if any(x in designation for x in barred):
                continue
            if not row["quantity"]:
                continue
            own = str(row["unit"]).strip().lower() in per_capacity
            divisor = row["quantity"] if own else capacity
            if not divisor:
                continue
            local += (row["local_xof"] or 0.0) * row["quantity"] / divisor
            offshore += (row["offshore_xof"] or 0.0) * row["quantity"] / divisor
        if not (local or offshore):
            continue
        landed = offshore * (1.0 + uplift) if offshore else None
        out[fragment] = {
            f"local_xof_per_{unit.lower()}": local or None,
            f"offshore_xof_per_{unit.lower()}": offshore or None,
            f"landed_xof_per_{unit.lower()}": landed,
            f"landed_usd_per_{unit.lower()}": landed / xof_per_usd if landed else None,
        }
    return out


#: Where the derived prices are archived, so that the figures copied into the settings can
#: be checked against their derivation without the workbook.
ARCHIVE = COSTS_DIR / "equipment_prices.json"


def settings_archive(budget: Path, prices: dict, extras: dict, xof_per_usd: float,
                     uplift: float, source: str) -> dict:
    """The derived per-unit prices, in the form the settings carry them.

    Four figures live in ``settings.py`` as literals, copied by hand from this script's
    output: the array, the storage, the inverter and the generating set. They agree with it
    today, and nothing in the repository would notice if they stopped: the one test that
    reads the workbook is skipped unless ``MGPY_BUDGET`` points at it, which it does on one
    machine. Archiving the derivation makes the comparison available to anyone, and a test
    does it on every run.

    What is archived is the derived figures and nothing else. The line-by-line bill of
    quantities stays out: it is the operator's own prices, item by item, and publishing it
    is not what a guard against a typing error requires. The workbook is named and
    digested instead, so the archive says what it came from.
    """
    import hashlib

    families = {}
    for family, block in prices.items():
        if not block["landed_usd_per_unit"]:
            continue
        unit = block["unit"]
        basket = extras.get(family) or {}
        key = unit.lower()
        total = sum(b[f"landed_xof_per_{key}"] for b in basket.values()
                    if b[f"landed_xof_per_{key}"])
        whole = block["landed_xof_per_unit"] + total
        families[family] = {
            "unit": unit,
            "capacity_bought": block["capacity_bought_offshore"],
            "landed_xof_per_unit": block["landed_xof_per_unit"],
            "extras_landed_xof_per_unit": total,
            "whole_landed_xof_per_unit": whole,
            "settings_usd_per_unit": whole / xof_per_usd,
        }
    return {
        "derived_from": budget.name,
        "sha1": hashlib.sha1(budget.read_bytes()).hexdigest()[:16],
        "written_by": "python -m microgrid_expansion.build_equipment_prices "
                      "--budget <the workbook> --archive",
        "xof_per_usd": xof_per_usd,
        "landing_uplift": uplift,
        "landing_uplift_source": source,
        "families": families,
    }


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
                        help="write the derived prices here as well as printing them, "
                             "line by line; this is the operator's own bill of "
                             "quantities and does not belong in the repository")
    parser.add_argument("--archive", nargs="?", type=Path, const=ARCHIVE, default=None,
                        help="write the per-unit prices the settings carry to "
                             "data/costs/equipment_prices.json, which a test compares "
                             "the settings against")
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
    #: One basket per family that has one, by the family it is added to.
    baskets = {
        "photovoltaic": proportional_extras(
            rows, ARRAY_EXTRAS, prices["photovoltaic"]["capacity_bought"], "kW",
            args.xof_per_usd, uplift),
        "battery": proportional_extras(
            rows, BATTERY_EXTRAS, prices["battery"]["capacity_bought"], "kWh",
            args.xof_per_usd, uplift),
    }

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

    #: What each basket is called where it is printed, and what the sum of it and its
    #: family's unit price is called: the figure the settings carry.
    CALLED = {"photovoltaic": ("beyond the modules, per kW of array",
                               "array, modules and the rest of it"),
              "battery": ("beyond the cells, per kWh of storage",
                          "storage, cells and the rest of it")}
    totals = {}
    for family, basket in baskets.items():
        if not basket:
            continue
        unit = prices[family]["unit"]
        key = unit.lower()
        heading, whole = CALLED[family]
        print(f"{heading}:")
        for name, block in basket.items():
            print(f"   {name[:44]:46s} landed "
                  f"{block[f'landed_xof_per_{key}']:>8,.0f} XOF/{unit}"
                  f" = {block[f'landed_usd_per_{key}']:>6,.2f} USD/{unit}")
        total = sum(b[f"landed_xof_per_{key}"] for b in basket.values()
                    if b[f"landed_xof_per_{key}"])
        offshore = sum(b[f"offshore_xof_per_{key}"] for b in basket.values()
                       if b[f"offshore_xof_per_{key}"])
        totals[family] = total
        print(f"   {'total':46s} landed {total:>8,.0f} XOF/{unit} "
              f"= {total / args.xof_per_usd:>6,.2f} USD/{unit}, "
              f"{offshore:,.0f} XOF/{unit} offshore")
        # What the settings carry per unit of capacity, which is the sum of the two: the
        # sizing spends one figure per unit and this balance of plant is not optional.
        each = prices[family]["landed_xof_per_unit"]
        if each:
            print(f"   {whole:46s} landed {each + total:>8,.0f} XOF/{unit} "
                  f"= {(each + total) / args.xof_per_usd:>6,.2f} USD/{unit}")
        print()

    print("bought once per site, and therefore in none of the baskets above:")
    for fragment in NOT_PROPORTIONAL:
        row = _match(rows, fragment)
        if row is None or not row["quantity"] or not row["offshore_xof"]:
            continue
        print(f"   {row['designation'][:44]:46s} {row['quantity']:>7,.0f} x "
              f"{row['offshore_xof']:>9,.0f} = "
              f"{row['quantity'] * row['offshore_xof']:>11,.0f} XOF offshore")

    if args.json:
        args.json.write_text(json.dumps({"prices": prices, "extras": baskets,
                                         "extras_landed_xof_per_unit": totals,
                                         "xof_per_usd": args.xof_per_usd,
                                         "landing_uplift": uplift,
                                         "landing_uplift_source": source}, indent=2),
                             encoding="utf-8")
        print(f"\nwritten {args.json}")
    if args.archive:
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        args.archive.write_text(
            json.dumps(settings_archive(args.budget, prices, baskets, args.xof_per_usd,
                                        uplift, source), indent=2) + "\n",
            encoding="utf-8")
        print(f"\nwritten {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
