"""A kilowatt of array is not a kilowatt of modules, and a kilowatt-hour is not a cell.

The sizing spends one figure per kilowatt and one per kilowatt-hour, so everything the
operator buys in proportion to those capacities has to be inside those two figures. Three
ways of getting that wrong are each silent, and each of them is held here.

A fragment can catch a line nobody meant it to. The budget prices a crimp lug of 16 mm² for
an M14 bolt at twelve thousand pieces, which is the distribution network's connections and
not the pack's cable; a fragment reading "Cosse à sertir de 16" takes it without a word and
five sixths of the storage basket is then the network's.

A line can be counted twice, by two fragments that overlap. And a line bought once per site
can be allocated over capacity, which makes a village's second kilowatt pay for the first
one's cabinet.

The arithmetic has one subtlety of its own, and it is worth a test rather than a comment:
a line the budget already prices per kilowatt-peak is taken at its own price, because
spreading its total over the modules bought charges the array for structure that is
standing empty at another site.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from microgrid_expansion.build_equipment_prices import (ARRAY_EXTRAS, BATTERY_EXTRAS,
                                                        EXCLUDED_FROM_EXTRAS, LANDING_UPLIFT,
                                                        NOT_PROPORTIONAL, PER_CAPACITY_UNITS,
                                                        proportional_extras, read_rows)
from microgrid_expansion.settings import default_settings

XOF_PER_USD = 607.37

#: The operator's procurement workbook, which lives outside this repository. The tests that
#: need it are skipped when it is not pointed at, and the ones that do not need it run on
#: the lines below.
BUDGET = os.environ.get("MGPY_BUDGET")

#: Lines of the budget, with its own designations and quantities and invented prices, so
#: that the matching and the allocation can be tested without the workbook. The prices are
#: round numbers chosen to make the expected totals readable; the designations and the
#: quantities are the budget's, since a fragment that does not match them is the defect
#: being looked for.
LINES = (
    # designation, unit, quantity, offshore price
    ("Module solaire 650 Wc Risen RSM132-8-650BMDG (unité)", "pcs", 764.0, 32_737.0),
    ("Structure métallique de fixation des modules solaires PV (kWc)", "kWp", 550.43,
     19_000.0),
    ("Câble solaire 1x6 mm² (rouge)", "ml", 4550.0, 500.0),
    ("Câble solaire 1x6 mm² (noir)", "ml", 4550.0, 500.0),
    ("Connecteur module solaire MC4 (mâle)", "pcs", 228.0, 425.0),
    ("Connecteur module solaire MC4 (femelle)", "pcs", 228.0, 425.0),
    ("Fusible 25A-1000VDC", "pcs", 200.0, 2_800.0),
    ("Porte fusibles 2P 25 A", "pcs", 71.0, 10_000.0),
    ("Parafoudre PV_T2_2 pôles_ 1000VDC_40kA", "pcs", 78.0, 9_000.0),
    ("Coffret électrique de 6 modules avec rails et borniers de terre", "pcs", 4.0,
     15_000.0),
    ("Coffret électrique de 18 modules avec rails et borniers de terre", "pcs", 1.0,
     20_000.0),
    ("Coffret électrique de 30 modules avec rails et borniers", "pcs", 9.0, 25_000.0),
    ("Peigne électrique horizontal 8 modules", "pcs", 35.0, 4_200.0),
    ("Boulon de mise à la terre des modules PV", "pcs", 2054.0, 100.0),
    ("Rack de 06 batteries Lithium 51,2V - 5 kWh", "pcs", 2.0, 25_000.0),
    ("Busbars batterie 600 A / 70V - 8 raccordements", "pcs", 10.0, 21_000.0),
    ("Busbars batterie 1250 A / 70V - 18 raccordements", "pcs", 0.0, 35_000.0),
    ("Support de fixation Busbar batterie", "pcs", 12.0, 5_500.0),
    ("BATFuse Sectionneur batterie 4P porte fusible de 100A-1000V", "pcs", 8.0, 30_000.0),
    ("Câble batterie souple multibrin H07-VK 1×16mm² (rouge) (ml)", "ml", 360.0, 1_097.0),
    ("Câble batterie souple multibrin H07-VK 1×95mm² (noir) (ml)", "ml", 100.0, 7_343.0),
    ("Cosse à sertir de 16 mm² pour boulon M8 (unité)", "pcs", 1688.0, 35.0),
    ("Cosse à sertir de 16 mm² pour boulon M14 (unité)", "pcs", 12165.3, 500.0),
    ("Cosse à sertir de 25 mm² pour boulon M8 (unité)", "pcs", 312.0, 53.0),
    ("Cosse à sertir de 35 mm² pour boulon M10 (unité)", "pcs", 315.0, 72.0),
    ("Cosse à sertir de 70 mm² pour boulon M10 (unité)", "pcs", 300.0, 190.0),
    ("Cosse à sertir de 95 mm² pour boulon M10 (unité)", "pcs", 320.0, 331.0),
    # Bought once per site, and in neither basket.
    ("Battery Box BMU BYD", "pcs", 8.0, 501_549.0),
    ("Armoire électrique_de 1m de large", "pcs", 8.0, 90_000.0),
    ("Cerbo GX", "pcs", 8.0, 131_517.0),
    ("GX Touch 50", "pcs", 8.0, 109_784.0),
    ("Caméra extérieur", "pcs", 6.0, 58_671.0),
    ("Ensemble paratonnerre (paratonnerre à tiges multiples, feuillard)", "pcs", 6.0,
     250_000.0),
    ("Compteurs powerhouse", "pcs", 22.0, 65_000.0),
    ("Nova", "pcs", 6.0, 395_280.0),
    ("Controleur de charge 250V/100A Victron", "pcs", 5.0, 25_000.0),
    ("Inverseur de source manuel 4P/400A", "pcs", 2.0, 35_000.0),
    # Left out of both baskets: nothing in the budget attaches them to either capacity.
    ("Cosse à sertir de 6mm²", "pcs", 2024.0, 500.0),
    ("Cosse à sertir de 10mm²", "pcs", 398.0, 625.0),
)


def _rows() -> list[dict]:
    return [{"designation": d, "unit": u, "quantity": q,
             "local_xof": None, "offshore_xof": p} for d, u, q, p in LINES]


def _caught(fragment: str, rows: list[dict]) -> list[dict]:
    """The lines a fragment takes, under the rule the builder applies."""
    wanted = " ".join(fragment.split()).lower()
    barred = tuple(" ".join(x.split()).lower() for x in EXCLUDED_FROM_EXTRAS)
    return [r for r in rows
            if wanted in r["designation"].lower()
            and not any(x in r["designation"].lower() for x in barred)]


@pytest.mark.parametrize("basket", [ARRAY_EXTRAS, BATTERY_EXTRAS],
                         ids=["array", "battery"])
def test_every_fragment_of_a_basket_matches_a_line_of_the_budget(basket) -> None:
    """A fragment that matches nothing is a line silently dropped from the price."""
    rows = _rows()
    unmatched = [f for f in basket if not _caught(f, rows)]
    assert not unmatched, f"these fragments match no line: {unmatched}"


@pytest.mark.parametrize("basket", [ARRAY_EXTRAS, BATTERY_EXTRAS],
                         ids=["array", "battery"])
def test_no_line_is_taken_by_two_fragments_of_the_same_basket(basket) -> None:
    """Two fragments that overlap charge the same item twice, and the sum says nothing."""
    rows = _rows()
    by_line: dict[str, list[str]] = {}
    for fragment in basket:
        for row in _caught(fragment, rows):
            by_line.setdefault(row["designation"], []).append(fragment)
    twice = {d: f for d, f in by_line.items() if len(f) > 1}
    assert not twice, f"counted twice: {twice}"


@pytest.mark.parametrize("basket", [ARRAY_EXTRAS, BATTERY_EXTRAS],
                         ids=["array", "battery"])
def test_what_is_bought_once_per_site_is_in_no_basket(basket) -> None:
    """A cabinet allocated over capacity makes the second kilowatt pay for the first."""
    rows = _rows()
    taken = {r["designation"] for f in basket for r in _caught(f, rows)}
    per_site = {r["designation"] for r in rows
                if any(" ".join(n.split()).lower() in r["designation"].lower()
                       for n in NOT_PROPORTIONAL)}
    assert not (taken & per_site), f"per-site lines in a basket: {sorted(taken & per_site)}"


def test_the_network_lug_is_kept_out_of_the_storage_basket() -> None:
    """The one line a section fragment catches and must not."""
    rows = _rows()
    assert any("M14" in r["designation"] for r in rows), "the fixture lost the trap"

    basket = proportional_extras(rows, BATTERY_EXTRAS, 1610.04, "kWh", XOF_PER_USD)
    kept = basket["Cosse à sertir de 16"]["offshore_xof_per_kwh"]

    # 1 688 lugs at 35 XOF over 1 610 kWh, and nothing else: the M14 line of the same
    # section would multiply this entry by a hundred.
    assert kept == pytest.approx(1688.0 * 35.0 / 1610.04, rel=1e-9)
    taken = {r["designation"] for f in BATTERY_EXTRAS for r in _caught(f, rows)}
    assert not any("M14" in d for d in taken)


def test_a_line_priced_per_kilowatt_peak_is_taken_at_its_own_price() -> None:
    """The structure, which the budget buys more of than there are modules to hold.

    Spreading its total over the modules bought charges the array for the structure
    standing empty at another site, which is six per cent of the structure's price.
    """
    rows = _rows()
    modules_kw = 764.0 * 0.65
    basket = proportional_extras(rows, ARRAY_EXTRAS, modules_kw, "kW", XOF_PER_USD)
    structure = basket["Structure métallique de fixation"]["offshore_xof_per_kw"]

    assert structure == pytest.approx(19_000.0, rel=1e-9)
    spread = 550.43 * 19_000.0 / modules_kw
    assert spread == pytest.approx(structure * 550.43 / modules_kw, rel=1e-9)
    assert "kwp" in PER_CAPACITY_UNITS["kW"]

    # On the budget's own quantities, 550.43 kWc of structure over 518.60 kW of modules,
    # that is the six per cent the settings' comment states.
    assert 550.43 / 518.60 == pytest.approx(1.06, abs=0.005)


def test_a_line_priced_by_the_piece_is_spread_over_the_capacity_bought() -> None:
    """Everything that is not priced per unit of capacity has to be allocated."""
    rows = _rows()
    modules_kw = 764.0 * 0.65
    basket = proportional_extras(rows, ARRAY_EXTRAS, modules_kw, "kW", XOF_PER_USD)

    comb = basket["Peigne électrique horizontal 8 modules"]
    assert comb["offshore_xof_per_kw"] == pytest.approx(35.0 * 4200.0 / modules_kw,
                                                        rel=1e-9)
    assert comb["landed_xof_per_kw"] == pytest.approx(
        comb["offshore_xof_per_kw"] * (1.0 + LANDING_UPLIFT), rel=1e-9)
    assert comb["landed_usd_per_kw"] == pytest.approx(
        comb["landed_xof_per_kw"] / XOF_PER_USD, rel=1e-9)


def test_the_settings_carry_the_price_of_the_array_and_of_the_pack() -> None:
    """The figures the sizing multiplies, which the builder derives and nothing enforces.

    Held to the hundredth of a dollar against the derivation written in the settings'
    own provenance, so that a basket changed in one place and not the other is caught.
    """
    settings = default_settings()

    assert settings.photovoltaic.cost_usd_kw == pytest.approx(91_864.2 / XOF_PER_USD,
                                                              abs=0.05)
    assert settings.battery.cost_usd_kwh == pytest.approx(67_872.1 / XOF_PER_USD, abs=0.05)
    for provenance, figure in ((settings.photovoltaic.provenance, "91 864"),
                               (settings.battery.provenance, "67 872")):
        assert figure in provenance.source
        assert provenance.verified


@pytest.mark.skipif(BUDGET is None,
                    reason="the operator's procurement workbook is not pointed at by "
                           "MGPY_BUDGET; the derivation is tested on the lines in this file")
def test_the_baskets_come_to_what_the_budget_says_they_do() -> None:
    """The two totals, on the workbook itself, at the quantities it buys."""
    rows = read_rows(Path(BUDGET))
    array = proportional_extras(rows, ARRAY_EXTRAS, 518.60, "kW", XOF_PER_USD)
    pack = proportional_extras(rows, BATTERY_EXTRAS, 1610.04, "kWh", XOF_PER_USD)

    direct_side = sum(array[f]["offshore_xof_per_kw"] for f in ARRAY_EXTRAS[3:])
    assert direct_side == pytest.approx(5_099.0, abs=2.0)

    storage = sum(b["offshore_xof_per_kwh"] for b in pack.values())
    assert storage == pytest.approx(4_655.0, abs=2.0)

    # What the excluded network lug would have done to that basket, on the quantities the
    # budget buys: four fifths on top of it, and nearly half of what would be left.
    excluded = next(r for r in read_rows(Path(BUDGET))
                    if "pour boulon M14" in r["designation"])
    admitted = excluded["quantity"] * excluded["offshore_xof"] / 1610.04
    assert admitted / storage == pytest.approx(0.81, abs=0.02)
    assert admitted / (storage + admitted) == pytest.approx(0.45, abs=0.02)
