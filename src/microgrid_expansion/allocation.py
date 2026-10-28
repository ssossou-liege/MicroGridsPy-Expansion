r"""The operator's allocation of funds, read as a payment ledger.

The procurement budget says what the equipment is quoted at. This file says what was paid,
to whom, and when: one line per disbursement over fifteen months, typed, named by vendor,
and with a column per site carrying the share charged to it. Two things it settles that a
quotation cannot.

Where the equipment comes from. Four fifths of it is invoiced by manufacturers outside the
customs union, which decides which of the budget's two price columns describes this project:
the operator buys at the supplier's price and pays the landing, so the offshore column plus
what the landing costs is the price it faces, and the local column is a retail price it does
not pay. ``landing_uplift`` measures that cost against the imported invoices.

Where the money goes that the sizing never sees. The plant's equipment is a little over half
of it; the rest is the turnkey construction contract, the poles, the civil works, the duty,
the inland transport, the land and the administration. The model prices the plant and leaves
the balance of plant at zero, and this says by how much.

Two limits hold throughout. Only a quarter of the money is charged to a site at all, the
rest being bought for the programme, so every per-site figure here is a floor and not a
cost. And a quarter of the value carries no description, so sums by vendor and by type are
sound while sums by what was bought are not.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

#: Site codes, in the order the ledger's columns run.
SITES = ("SAM", "GBO", "KOT", "AGL", "SIN", "DON", "KIN", "AHG")

#: Vendors invoicing from outside the customs union, by a distinctive fragment of the name.
#: Duty and sea freight are levied on their lines and not on the equipment bought in
#: Cotonou, so the uplift is measured against them alone.
FOREIGN = ("DEYE", "SANHE", "OUOU", "SUSTAIN", "YUEQING", "HEBEI", "MIBET", "LESOTHO",
           "SPARKMETER", "AMOSOLAR", "CHANGZHOU", "HUAZHAN", "NINGBO", "FUZHOU",
           "YANGZHOU", "ALIBABA", "MAERSK", "AFRICA GBC")

#: Lines that price equipment: the plant's own and the structures that carry the array.
EQUIPMENT = ("CONS - Equipement", "CONS - PV")

#: Lines that price the network between the plant and the customer.
DISTRIBUTION = ("CONS - Poles - Purchase", "CONS - Poles - Installation",
                "CONS - Mis / Dist Network")

#: Transport lines naming a sea leg or a container. The remaining transport is inland and
#: names poles, cranes and missions, so it is left out of the landing cost rather than
#: spread over it.
SEA_LEG = "fret|msc|container|conteneur|surestar"

SHEET = "Listing"
FIRST_LINE = 13                 # the ledger starts under its own header row
COLUMNS = 14                    # date, two descriptions, vendor, type, amount, 8 sites


def ledger(path: Path) -> pd.DataFrame:
    """Every disbursement, with its site shares and whether the vendor is an importer."""
    raw = pd.read_excel(path, sheet_name=SHEET, header=None)
    body = raw.iloc[FIRST_LINE:, :COLUMNS].copy()
    body.columns = ["date", "operation_fr", "operation", "vendor", "type",
                    "amount"] + list(SITES)
    body = body[body["amount"].notna()].reset_index(drop=True)
    body["date"] = pd.to_datetime(body["date"], errors="coerce")
    for column in ["amount", *SITES]:
        body[column] = pd.to_numeric(body[column], errors="coerce").fillna(0.0)
    # The English column is filled in for a quarter of the lines; the French one for most.
    body["label"] = body.operation_fr.fillna(body.operation).fillna("")
    body["allocated"] = body[list(SITES)].sum(axis=1)
    vendor = body.vendor.fillna("").str.upper()
    body["foreign"] = [any(k in name for k in FOREIGN) for name in vendor]
    return body


def landing_uplift(d: pd.DataFrame) -> dict:
    """What it costs to bring an imported invoice to site, as a share of that invoice.

    Measured as duty and the identifiable sea leg over the equipment invoiced by foreign
    manufacturers. It is a floor: the ledger's remaining transport lines are named for
    poles, crane hire and missions, but nine of them say only "Transport", and whatever
    part of those is an international leg belongs here and is not counted.
    """
    equipment = d[d.type.isin(EQUIPMENT)]
    imported = float(equipment.loc[equipment.foreign, "amount"].sum())
    duty = float(d.loc[d.type == "CONS - Import Charges", "amount"].sum())
    sea = float(d[(d.type == "CONS - Transport")
                  & d.label.str.contains(SEA_LEG, case=False, na=False)].amount.sum())
    everything = float(equipment.amount.sum())
    return {
        "equipment_xof": everything,
        "imported_xof": imported,
        "imported_share": imported / everything if everything else None,
        "duty_xof": duty,
        "sea_leg_xof": sea,
        "uplift_on_imported": (duty + sea) / imported if imported else None,
        "uplift_on_all_equipment": (duty + sea) / everything if everything else None,
    }


def by_type(d: pd.DataFrame) -> pd.DataFrame:
    """What was spent on each kind of thing, largest first."""
    out = d.groupby("type").agg(lines=("amount", "size"), xof=("amount", "sum"),
                                charged_to_a_site=("allocated", "sum"))
    out["share_pct"] = 100.0 * out.xof / out.xof.sum()
    return out.sort_values("xof", ascending=False)


def by_site(d: pd.DataFrame) -> pd.DataFrame:
    """What is charged to each site, by the part of the project it pays for.

    A floor on every count. The equipment bought for the programme is charged to no site,
    and the two villages already running appear here only through their consumables.
    """
    groups = {
        "equipment": EQUIPMENT,
        "distribution": DISTRIBUTION,
        "civil": ("CONS - Civil engineering",),
        "epc": ("EPC",),
        "development": ("ADM - Consultancy", "CONS - Consultancy"),
        "transport": ("CONS - Transport",),
        "duty": ("CONS - Import Charges",),
        "operating": ("O&M",),
    }
    frame = pd.DataFrame({name: d[d.type.isin(types)][list(SITES)].sum()
                          for name, types in groups.items()}).T
    frame.loc["total"] = frame.sum()
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True,
                        help="the operator's allocation of funds workbook")
    parser.add_argument("--xof-per-usd", type=float, default=607.37,
                        help="the rate the model's currency block states")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    d = ledger(args.ledger)
    rate = args.xof_per_usd
    total = float(d.amount.sum())
    unlabelled = d[d.label == ""]

    print(f"{len(d)} lines, {d.date.min():%Y-%m-%d} to {d.date.max():%Y-%m-%d}")
    print(f"total {total:,.0f} XOF = {total / rate:,.0f} USD")
    print(f"charged to a site {float(d.allocated.sum()):,.0f} XOF "
          f"({100 * float(d.allocated.sum()) / total:.0f} %)")
    print(f"no description    {len(unlabelled)} lines, "
          f"{float(unlabelled.amount.sum()):,.0f} XOF "
          f"({100 * float(unlabelled.amount.sum()) / total:.0f} % of the money)")

    print("\n-- where the money went --")
    for name, row in by_type(d).iterrows():
        print(f"   {name:30s} {row.xof:>15,.0f} XOF {row.share_pct:>5.1f} %")

    print("\n-- landing an imported invoice --")
    u = landing_uplift(d)
    print(f"   equipment and structures      {u['equipment_xof']:>15,.0f} XOF")
    print(f"   of it, foreign manufacturers  {u['imported_xof']:>15,.0f} XOF "
          f"({100 * u['imported_share']:.0f} %)")
    print(f"   duty                          {u['duty_xof']:>15,.0f} XOF")
    print(f"   sea leg named as such         {u['sea_leg_xof']:>15,.0f} XOF")
    print(f"   uplift on the imported part   {100 * u['uplift_on_imported']:>15.2f} %  "
          f"(a floor)")

    print("\n-- charged to each site, XOF (a floor) --")
    frame = by_site(d)
    print(f"   {'':14s}" + "".join(f"{s:>14s}" for s in SITES[:6]))
    for name, row in frame.iterrows():
        print(f"   {name:14s}" + "".join(f"{row[s]:>14,.0f}" for s in SITES[:6]))

    if args.json:
        payload = {
            "period": [str(d.date.min().date()), str(d.date.max().date())],
            "lines": len(d), "total_xof": total, "xof_per_usd": rate,
            "landing": u,
            "by_type_xof": {k: float(v) for k, v in d.groupby("type").amount.sum().items()},
            "by_site_xof": {s: float(d[s].sum()) for s in SITES},
            "by_site_part_xof": {k: {s: float(v) for s, v in row.items()}
                                 for k, row in by_site(d).iterrows()},
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwritten {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
