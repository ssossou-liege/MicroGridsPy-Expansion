"""The interface answers one question, and answers it from what the field survey recorded.

Sizing a reference year and planning an expansion were two buttons, and the separation put
a choice to the developer that was never theirs: a plant is bought once, under an uncertain
future, and the year-0 decision of the scenario tree *is* the sizing. These tests hold the
merged shape in place, and hold the two things that shape depends on: a community described
by its survey rather than by a draw, and a cache that knows the difference.
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from microgrid_expansion.instances import _site_fingerprint
from microgrid_expansion.sites import Site, from_record, get_site, standard_offset, to_record
from microgrid_expansion.ui import engine, i18n, projects

STATIC = Path(__file__).resolve().parents[1] / "src" / "microgrid_expansion" / "ui" / "static"


# --------------------------------------------------------------------------- one question
def test_the_engine_answers_the_decision_and_not_two_studies() -> None:
    """One entry point, and it carries both halves of the answer it returns."""
    assert hasattr(engine, "size")
    source = __import__("inspect").getsource(engine.size)
    assert "plan_expansion(" in source and "size_site(" in source, (
        "the decision no longer rests on both the tree and the certified year")


def test_the_page_offers_one_run_and_not_a_choice_between_two() -> None:
    """``/api/size`` is the whole answer; the plan is no longer a second study."""
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    markup = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/api/size" in script
    for gone in ("/api/plan", "/api/decide", "run-size", "run-plan"):
        assert gone not in script and gone not in markup, f"{gone} survived the merge"
    # One POST starts work, and it is the sizing.
    starts = re.findall(r'fetch\("(/api/[a-z-]+)", \{\s*\n?\s*method: "POST"', script)
    assert starts.count("/api/size") == 1


def test_the_answer_says_which_half_of_it_is_proven() -> None:
    """The reference year is certified; the year-0 decision is not, and must say so.

    This is the standing of the whole result, not a footnote to it. A page that reported
    the tree's root under the certificate's badge would be claiming a proof that has not
    been produced -- closing a bound on the first stage is the open piece of this work.
    """
    source = __import__("inspect").getsource(engine.size)
    assert '"reference_year": bool(certificate["proven"])' in source
    assert '"first_stage": False' in source
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "sizing.proven.yes" in script and "sizing.proven.no" in script
    for key in ("sizing.proven.hint", "sizing.reference.hint"):
        assert key in i18n.STRINGS, f"{key} is claimed by the page and absent here"


def test_a_sizing_exports_both_halves_under_their_own_headings() -> None:
    """Two sections, because both carry a row called "storage" and they are not the same."""
    result = {"site": "Samionta", "architecture": "mixed",
              "plant": {"pv_kw": 57.5, "battery_kwh": 135.0},
              "expected": {"expected_lcoe_usd_kwh": 0.1819},
              "tree": {"nodes": 13, "leaves": 8},
              "proven": {"first_stage": False, "reference_year": True},
              "reference": {"site": "Samionta", "design": {"battery_kwh": 120.0},
                            "lcoe_usd_kwh": 0.2104, "proven": True}}
    body = projects.as_csv(result, "en")
    assert body.count("Storage (kWh)") == 2, "the two plants are not told apart"
    assert "BUILD THIS YEAR" in body and "REFERENCE YEAR, CERTIFIED" in body
    assert "135.0" in body and "120.0" in body


# ------------------------------------------------------------------- what the survey says
def test_the_roster_reaches_the_year_that_is_cached_for_it() -> None:
    """Two villages with different enterprises must not share one cached year."""
    site = get_site("Samionta")
    three = _site_fingerprint(replace(site, productive_mix={"milling": 3}))
    four = _site_fingerprint(replace(site, productive_mix={"milling": 4}))
    other = _site_fingerprint(replace(site, productive_mix={"sawmill": 3}))
    assert len({three, four, other}) == 3


def test_a_community_that_declared_no_roster_keys_as_it_always_did() -> None:
    """Adding the field must not throw away every year already computed.

    A pool takes about ten minutes to rebuild and there are some thirty of them, so writing
    an empty roster into the key would have cost every user hours to record the absence of
    something.
    """
    site = get_site("Samionta")
    plain = _site_fingerprint(site)
    assert _site_fingerprint(replace(site, productive_mix={})) == plain
    assert _site_fingerprint(replace(site, productive_mix=None)) == plain
    assert "milling" not in plain


def test_the_roster_survives_being_written_down_and_read_back() -> None:
    site = Site(name="Probe", census={"HH1": 40}, latitude=11.1, longitude=2.9,
                productive_mix={"milling": 2, "refrigeration": 1}, origin="user")
    assert from_record(to_record(site)).productive_mix == {"milling": 2, "refrigeration": 1}


# ------------------------------------------------------------------------- the time zone
@pytest.mark.parametrize("longitude, offset", [
    (2.24, 0),        # Benin: the sun says UTC+0, the state keeps UTC+1
    (-17.4, -1),      # Dakar
    (45.0, 3),
    (None, 1),        # no coordinate yet: the old default, unchanged
])
def test_the_time_zone_is_taken_from_the_longitude(longitude, offset) -> None:
    """Asked for, it is an hour of error waiting to happen; derived, it is arithmetic."""
    assert standard_offset(longitude) == offset


def test_the_page_states_the_zone_it_derived_and_lets_it_be_corrected() -> None:
    """Benin keeps UTC+1 against a solar UTC+0, so the derivation has to be correctable."""
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "site.utc.derived" in script, "the page never says which zone it chose"
    assert "site.utc.adjust" in script, "the derived zone cannot be corrected"
    assert "utc_offset_hours" in script, "a correction never reaches the server"
