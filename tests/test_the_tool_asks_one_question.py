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


def test_each_page_asks_only_for_what_it_is_about() -> None:
    """A reanalysis knows nothing of households, and nor does the page that fetches it.

    The site page asks where the village is; the demand page asks what it consumes. Saving
    on the way out of either must check what that page collected and nothing else. Both
    halves of that have gone wrong. Fetching the series once refused with "no households to
    connect", which was true, unrelated, and arrived while the developer was still placing
    the point. And when the census moved to the demand page, leaving the site page still
    demanded one -- which made that page impossible to leave at all, since the boxes that
    would satisfy it were on the page behind the button.
    """
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'saveSite("site")' in script, (
        "fetching the series saves the site under the full validation")
    assert 'need === "demand" && households <= 0' in script, (
        "the household check is not conditioned on what the save has to satisfy")
    assert 'saveSite("site"))) return;\n    show("demand")' in script, (
        "leaving the site page demands a census the site page does not collect")
    assert 'saveSite("demand"))) return;\n    show("parameters")' in script, (
        "the demand page may be left without a census")


# ------------------------------------------------------- the weather of a nearby point
def test_two_points_in_one_grid_cell_receive_the_same_weather() -> None:
    """Which is what makes reusing a neighbour's series exact rather than approximate.

    The archive answers a point with the cell it falls in, about eleven kilometres across
    at this latitude. Distance alone will not do: two points six kilometres apart can
    straddle a boundary and land in different cells, and two eleven kilometres apart can
    share one. It is the cell that decides.
    """
    from microgrid_expansion.resource.era5 import GRID_DEG, distance_km, same_cell

    assert GRID_DEG == pytest.approx(0.1)
    assert distance_km(7.0, 2.0, 7.1, 2.0) == pytest.approx(11.1, abs=0.3)
    assert same_cell(7.095, 2.244, 7.099, 2.240)
    # Six kilometres apart, either side of a boundary: not the same numbers.
    assert not same_cell(7.0955, 2.2446, 7.1500, 2.2446)


def test_a_borrowed_series_says_whose_it_is() -> None:
    """A plant sized on a neighbour's sun is a fact about the result, not a detail.

    So the site records the village it borrowed from, and the cache key already carried the
    file name, which means a borrowed year is never served for an own-downloaded one.
    """
    from dataclasses import replace

    from microgrid_expansion.instances import _site_fingerprint
    from microgrid_expansion.sites import from_record, get_site, to_record

    site = get_site("Samionta")
    borrowed = replace(site, irradiance_file="elsewhere_weather_hourly_2016_2025.csv",
                       irradiance_source="Gbowele")
    assert from_record(to_record(borrowed)).irradiance_source == "Gbowele"
    assert _site_fingerprint(borrowed) != _site_fingerprint(site), (
        "a borrowed series keys the same as the site's own")

def _reachable_functions(root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Which functions of the package can actually be reached, and what each one names.

    A call graph over the package, marked live from the places the outside world enters:
    module-level code, the interface's route handlers, every ``main``, and the dunder
    entry points. A function nobody calls is dead however complete it looks, and a setting
    read only inside a dead function is a setting nothing reads.
    """
    import ast

    names: dict[str, set[str]] = {}          # function -> identifiers it mentions
    calls: dict[str, set[str]] = {}          # function -> functions it refers to
    module_level: set[str] = set()
    entry: set[str] = set()

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        inner = {id(n) for f in functions for n in ast.walk(f)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)) and id(node) not in inner:
                module_level.add(node.id if isinstance(node, ast.Name) else node.attr)
        for function in functions:
            key = f"{path.name}:{function.name}"
            mentioned = {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
            mentioned |= {n.attr for n in ast.walk(function)
                          if isinstance(n, ast.Attribute)}
            names[key] = mentioned
            calls[key] = mentioned
            # A route handler is called by the web framework, a main by the shell, and a
            # nested function by the one that defines it; none of them is ever named.
            decorated = any(isinstance(d, (ast.Call, ast.Attribute))
                            for d in function.decorator_list)
            if decorated or function.name in ("main", "run") or path.name == "__main__.py":
                entry.add(key)

    live = {k for k in names if k in entry or k.split(":")[1] in module_level}
    changed = True
    while changed:                            # one fixed point over the call graph
        changed = False
        reached = set().union(*(calls[k] for k in live)) if live else set()
        for key in calls:
            if key not in live and key.split(":")[1] in reached:
                live.add(key)
                changed = True
    return live, names


def test_every_setting_the_form_offers_is_read_by_something_reachable() -> None:
    """A knob that changes nothing is worse than an absent one: it reads as an answer.

    "Treat the arrival as uncertain" sat on the form with a paragraph explaining that the
    expansion plan would branch on the arrival of the line. Nothing read it. The tree was
    always drawn over the library's default hazard, so a village with a line already in and
    a village with none were planned identically, and the switch that distinguishes them was
    a decoration.

    Naming the setting somewhere is not enough and the first version of this test made that
    mistake: with the wiring torn out again it still passed, because the function that reads
    the setting was left behind, unreachable and convincing. So the question asked here is
    whether anything that can actually run reads it.
    """
    import re
    from pathlib import Path

    from microgrid_expansion.ui.schema import GROUPS

    root = Path(__file__).resolve().parents[1] / "src" / "microgrid_expansion"
    live, names = _reachable_functions(root)
    assert len(live) > 100, f"only {len(live)} reachable functions; the scan is broken"
    read_live = set().union(*(names[k] for k in live))

    script = (root / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    unread = [f.path for _k, _t, group in GROUPS for f in group
              if f.path.split(".")[-1] not in read_live
              and not re.search(rf"\b{re.escape(f.path.split('.')[-1])}\b", script)]
    assert not unread, (
        "the form offers settings that nothing reachable reads; either wire them to the "
        f"model or take them off the form: {unread}")


def test_the_plan_is_configured_from_the_settings_and_not_from_the_defaults() -> None:
    """Every figure the tree configuration duplicates from the settings must be handed over.

    ``ModelConfig`` repeats a handful of the project settings because the tree is drawn
    before a settings object exists. Each repetition is a chance for the two to disagree,
    and they did: the interface built the configuration with the solver name alone, so every
    expansion plan it produced was Samionta's, whatever village had been described, and the
    connection age, the horizon, the discount rate, the storage chemistry and the network
    loss were all the library's defaults rather than the reader's answers.

    The test above asks whether a setting is read by anything reachable. This one asks the
    narrower question that fault turned on: whether the bridge between the two carries
    everything it has room for. Neither proves a setting reaches every computation it ought
    to; a behavioural check is the only thing that would, and the ones that matter most are
    held in the pricing tests.
    """
    import ast
    import dataclasses
    from pathlib import Path

    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.settings import ProjectSettings

    def paths(spec, prefix: str = "") -> set[str]:
        out = set()
        for field in dataclasses.fields(spec):
            out.add(f"{prefix}{field.name}")
            if dataclasses.is_dataclass(field.type) or field.name in (
                    "economics", "battery", "infrastructure", "solver", "grid",
                    "coupling", "controller"):
                out.add(field.name)
        return out

    shared = {f.name for f in dataclasses.fields(ModelConfig)}
    settings_names = paths(ProjectSettings)
    # A configuration field whose name also names a project setting, or sits inside one.
    nested = set()
    for name in ("economics", "battery", "infrastructure", "solver", "grid"):
        spec = ProjectSettings.__dataclass_fields__[name].type
        if dataclasses.is_dataclass(spec):
            nested |= {f.name for f in dataclasses.fields(spec)}
    duplicated = {name for name in shared
                  if name in settings_names or name in nested
                  or name in ("battery_chemistry", "network_loss_fraction")}

    source = (Path(__file__).resolve().parents[1] / "src" / "microgrid_expansion"
              / "ui" / "engine.py").read_text(encoding="utf-8")
    passed: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "ModelConfig"):
            passed |= {kw.arg for kw in node.keywords if kw.arg}
    assert passed, "the interface never builds a ModelConfig; this test is reading nothing"

    forgotten = sorted(duplicated - passed - {"seed", "stage_years"})
    assert not forgotten, (
        "the interface builds the tree configuration without handing over settings it "
        f"duplicates, so the plan will quietly use a default: {forgotten}")
