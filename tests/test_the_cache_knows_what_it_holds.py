"""A cached demand year must not outlive the thing that produced it.

The demand cache exists because simulating a community-year takes a minute and a certified
sizing needs the same year thousands of times. It is keyed on a fingerprint, and the whole
value of the cache rests on that fingerprint being complete: whatever it omits can change
underneath a stored year, and the run then sizes a plant against demand that no model
currently in the repository would produce. There is no error and no warning -- just a
plausible number for the wrong village.

It had been omitting the generating code. The fix that made the generator reproducible --
RAMP seeds Python's global ``random`` only ``if self.random_seed:``, and this project's
default seed is zero -- invalidated nothing, so the pools drawn before it, unseeded, went on
being served for two days. What finally dislodged them was an unrelated rename of a column
in a calibration table, which is not a mechanism anyone should rely on.

These tests state the properties the fingerprint has to have, including the one that makes
it usable: that it does not churn on prose.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from microgrid_expansion import instances

DEMAND_DIR = Path(instances.__file__).parent / "demand"


def test_every_demand_module_is_classified() -> None:
    """A module added to the package must be placed on one side or the other.

    Without this the list goes stale silently: someone adds a module to the generation path,
    nobody adds it here, and the cache stops noticing changes to it -- the exact failure this
    whole file exists to prevent, reintroduced by omission.
    """
    present = {p.name for p in DEMAND_DIR.glob("*.py")}
    classified = set(instances._GENERATION_SOURCES) | set(instances._OFFLINE_SOURCES)
    assert present == classified, (
        f"unclassified: {sorted(present - classified)}; "
        f"listed but absent: {sorted(classified - present)}")


#: Where a simulated year starts: the generator itself, and the archetype library, which
#: ``instances`` reaches directly rather than through the generator.
ENTRY_POINTS = ("generator.py", "archetypes.py")


def _reached_from(entry_points) -> set[str]:
    """Every demand module reachable from the entry points, imports followed to the end.

    Direct imports are not the generation path. Following only the generator's own imports
    said that ``maturity`` and ``partition`` were offline modules, when every simulated
    month runs them: the generator asks ``growth`` for the mixture law, ``growth`` asks
    ``maturity``, ``maturity`` asks ``partition``, and ``partition`` re-reads and re-clusters
    the whole meter archive. A reach computed to its fixed point cannot be fooled that way.
    """
    seen: set[str] = set()
    frontier = list(entry_points)
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((DEMAND_DIR / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 1 or not node.module:
                continue
            imported = node.module.split(".")[0] + ".py"
            if (DEMAND_DIR / imported).exists() and imported not in seen:
                frontier.append(imported)
    return seen


def test_the_generation_sources_are_everything_the_generator_reaches() -> None:
    """The listed modules must be exactly the transitive reach of a simulated year."""
    reached = _reached_from(ENTRY_POINTS)
    listed = set(instances._GENERATION_SOURCES)
    assert listed == reached, (
        f"listed {sorted(listed)} but a simulated year reaches {sorted(reached)}")


def test_no_module_the_generation_runs_is_classified_offline() -> None:
    """The failure stated the other way round, which is the one that hid for months."""
    offline = set(instances._OFFLINE_SOURCES) & _reached_from(ENTRY_POINTS)
    assert not offline, (
        f"these modules run at generation and are listed as offline: {sorted(offline)}; "
        "a change to any of them would leave every cached year in place")


def test_a_change_to_the_generating_code_changes_the_fingerprint(tmp_path) -> None:
    """The property that was missing, stated directly."""
    original = (DEMAND_DIR / "generator.py").read_text(encoding="utf-8")
    before = instances._demand_fingerprint()
    try:
        (DEMAND_DIR / "generator.py").write_text(
            original.replace("import calendar", "import calendar\nSTRAY = 1", 1),
            encoding="utf-8")
        assert instances._demand_fingerprint() != before, (
            "the generator changed and the cache key did not; stored years would survive it")
    finally:
        (DEMAND_DIR / "generator.py").write_text(original, encoding="utf-8")
    assert instances._demand_fingerprint() == before, "the file was not restored"


def test_a_change_to_a_calibration_table_changes_the_fingerprint(monkeypatch, tmp_path) -> None:
    """Every table the generation reads, and not whichever one happens to sort first.

    The test used to touch ``sorted(glob)[0]`` and trust that it was read at generation. It
    was, until the tables of the segmentation were left out of the key and the first name
    alphabetically became one of them. The property the test is named for still held for the
    nine tables it is about, and the test had stopped asking about any of them.
    """
    copy = tmp_path / "reference"
    copy.mkdir()
    for csv in instances.REFERENCE_DIR.glob("*.csv"):
        (copy / csv.name).write_bytes(csv.read_bytes())
    monkeypatch.setattr(instances, "REFERENCE_DIR", copy)
    before = instances._demand_fingerprint()

    read_at_generation = sorted(path for path in copy.glob("*.csv")
                                if path.name not in instances._NOT_READ_AT_GENERATION)
    assert read_at_generation, "every table is declared unread; the key would hash none"
    for table in read_at_generation:
        original = table.read_bytes()
        table.write_bytes(original + b"\n")
        try:
            assert instances._demand_fingerprint() != before, (
                f"{table.name} is read at generation and a change to it left the key where "
                "it was; a stored year would survive the recalibration that moved it")
        finally:
            table.write_bytes(original)
    assert instances._demand_fingerprint() == before, "a table was not restored"


def test_prose_alone_does_not_invalidate_an_hour_of_cache(tmp_path) -> None:
    """A fingerprint that churns on comments gets worked around rather than trusted.

    Rebuilding the pools costs about an hour. If rewrapping a comment did it, the pressure
    would be to stop touching comments or to delete the check -- so the digest reads the
    syntax tree, not the text.
    """
    plain = tmp_path / "plain.py"
    plain.write_text('"""Docstring."""\nX = 1  # a note\n\n\ndef f():\n    return X\n')
    reworded = tmp_path / "reworded.py"
    reworded.write_text('"""A different docstring entirely."""\n'
                        'X = 1  # a note, rewritten at length\n\n\n'
                        'def f():\n'
                        '    """Added while we were here."""\n'
                        '    return X\n')
    assert instances._code_digest(plain) == instances._code_digest(reworded)

    changed = tmp_path / "changed.py"
    changed.write_text('"""Docstring."""\nX = 2  # a note\n\n\ndef f():\n    return X\n')
    assert instances._code_digest(plain) != instances._code_digest(changed)


def test_the_pool_cache_and_the_instance_cache_agree_on_the_key() -> None:
    """Two caches holding the same demand must invalidate together.

    They are keyed in different modules, and a fix applied to one and not the other would
    leave stale demand reachable by the path that was missed.
    """
    from microgrid_expansion.scenarios import demand_paths

    source = Path(demand_paths.__file__).read_text(encoding="utf-8")
    assert "_demand_fingerprint" in source, (
        "the pool cache does not use the demand fingerprint the instance cache uses")


@pytest.mark.parametrize("name", sorted(instances._GENERATION_SOURCES))
def test_each_generation_source_actually_moves_the_fingerprint(name) -> None:
    """Listing a module is not enough; it has to reach the digest."""
    path = DEMAND_DIR / name
    original = path.read_text(encoding="utf-8")
    before = instances._demand_fingerprint()
    try:
        path.write_text(original + "\nSTRAY_CONSTANT = 12345\n", encoding="utf-8")
        assert instances._demand_fingerprint() != before, f"{name} is listed but not hashed"
    finally:
        path.write_text(original, encoding="utf-8")


def test_the_prior_strength_of_the_mixture_reaches_the_key() -> None:
    """A figure of the segmentation, changed in its own module, must move the key.

    The prior strength shrinks each stratum of the mixture law towards the pooled law. It
    decides the composition every simulated month is drawn from, and it lived in a module
    the key treated as offline: changing it changed every year the model produces and
    invalidated nothing.
    """
    path = DEMAND_DIR / "maturity.py"
    original = path.read_text(encoding="utf-8")
    assert "PRIOR_STRENGTH = 20.0" in original
    before = instances._demand_fingerprint()
    try:
        path.write_text(original.replace("PRIOR_STRENGTH = 20.0",
                                         "PRIOR_STRENGTH = 50.0", 1),
                        encoding="utf-8")
        assert instances._demand_fingerprint() != before, (
            "the prior of the mixture law changed and the cache key did not")
    finally:
        path.write_text(original, encoding="utf-8")
    assert instances._demand_fingerprint() == before, "the file was not restored"


def _demand_copy(monkeypatch, tmp_path):
    """A writable copy of the measured inputs, in place of the repository's."""
    copy = tmp_path / "demand"
    copy.mkdir()
    for path in instances._measured_inputs():
        (copy / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(instances, "DEMAND_DIR", copy)
    return copy


def test_one_byte_of_the_meter_archive_changes_the_fingerprint(monkeypatch,
                                                               tmp_path) -> None:
    """The record the mixture law is estimated on is part of the key.

    Five months of readings were added to both archives in October 2026. Every cached year
    had been composed from a law estimated on the record as it stood before, and the key
    said nothing about it.
    """
    copy = _demand_copy(monkeypatch, tmp_path)
    before = instances._demand_fingerprint()
    archive = sorted(copy.glob("*.parquet"))[0]
    archive.write_bytes(archive.read_bytes() + b"\x00")
    assert instances._demand_fingerprint() != before, (
        f"{archive.name} grew and the cache key did not move")


def test_the_household_register_changes_the_fingerprint(monkeypatch, tmp_path) -> None:
    """Who is metered, and when they were connected, decides the maturity of each month."""
    copy = _demand_copy(monkeypatch, tmp_path)
    before = instances._demand_fingerprint()
    register = copy / instances._MEASURED_CENSUS
    register.write_text(register.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert instances._demand_fingerprint() != before


def test_rebuilding_a_table_nobody_reads_keeps_the_cache(monkeypatch, tmp_path) -> None:
    """Hashing what the generation does not open costs hours for nothing.

    The type-by-month mixture was superseded by the maturity-conditioned law. Only
    ``validate.py`` and the tests read it now, and rebuilding it invalidated every pool --
    thirty of them, an hour and a half of simulation apiece at four years each.
    """
    copy = tmp_path / "reference"
    copy.mkdir()
    for csv in instances.REFERENCE_DIR.glob("*.csv"):
        (copy / csv.name).write_bytes(csv.read_bytes())
    monkeypatch.setattr(instances, "REFERENCE_DIR", copy)
    before = instances._demand_fingerprint()
    for name in instances._NOT_READ_AT_GENERATION:
        target = copy / name
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert instances._demand_fingerprint() == before, (
        "a table the generation never opens moved the key")


#: The one function that still reads the superseded type-by-month mixture, and the modules
#: allowed to call it. It is defined in ``generator.py``, which is on the generation path,
#: but no simulated year calls it: the composition of a month comes from the
#: maturity-conditioned law instead. That is why the table may be left out of the key, and
#: this is the fact the exclusion rests on.
_SUPERSEDED_READER = "load_monthly_mixture"
_ALLOWED_CALLERS = {"validate.py", "__init__.py", "generator.py"}

#: Where a table left out of the key may be named on the generation path, and why each
#: place is safe. ``load_monthly_mixture`` reads the superseded mixture, and no simulated
#: year calls it. The two build scripts name the tables they *write*, which they must, and
#: nothing runs another module's ``main``. Naming a table, reading one and writing one are
#: three different things, and the exclusion turns on the second alone.
_ALLOWED_MENTIONS = {
    ("generator.py", _SUPERSEDED_READER),
    ("build_mixture_probabilities.py", "main"),
    ("build_monthly_household_clusters.py", "main"),
}


def _function_scopes(path: Path) -> dict[ast.AST, str]:
    """Every node of a module, mapped to the name of the innermost function holding it."""
    scopes: dict[ast.AST, str] = {}

    def descend(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            scopes[child] = inner
            descend(child, inner)

    descend(ast.parse(path.read_text(encoding="utf-8")), "<module>")
    return scopes


def _names_a_table_left_out(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant)
            and node.value in instances._NOT_READ_AT_GENERATION)


def _is_a_read(node: ast.AST) -> bool:
    """A call that opens a file in order to read it, by this package's conventions."""
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        name = node.func.attr
    elif isinstance(node.func, ast.Name):
        name = node.func.id
    else:
        return False
    return name.startswith(("read_", "load_", "open"))


def _callers_of(function: str, modules=None) -> set[str]:
    """Modules that call a function of that name, the script guard excluded.

    What a module does when it is run from the shell is not on the generation path, so the
    ``__main__`` block is dropped before the scan; counting it would attribute every
    script's own entry point to the generation that never runs it.
    """
    names = sorted(modules) if modules is not None else sorted(
        path.name for path in DEMAND_DIR.glob("*.py"))
    callers = set()
    for name in names:
        tree = ast.parse((DEMAND_DIR / name).read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body
                     if not (isinstance(node, ast.If)
                             and "__name__" in ast.unparse(node.test))]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == function:
                callers.add(name)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == function:
                callers.add(name)
    return callers


def test_a_table_left_out_of_the_key_is_named_only_where_no_simulated_year_reads_it() -> None:
    """Leaving a table out of the key is only safe while nothing on the path reads it.

    The test this replaces asserted that one module mentioned the one excluded table. That
    stopped being the fact when the six tables recording the segmentation were excluded as
    well: the script that writes them names them, as it must, and the test read a writer as
    a reader. So the scan separates the three uses, and it is the reads that have to stay
    where they are: one function, which no simulated year calls.
    """
    naming: set[tuple[str, str]] = set()
    reading: set[tuple[str, str]] = set()
    for module in instances._GENERATION_SOURCES:
        for node, scope in _function_scopes(DEMAND_DIR / module).items():
            if _names_a_table_left_out(node):
                naming.add((module, scope))
            if _is_a_read(node) and any(_names_a_table_left_out(inner)
                                        for inner in ast.walk(node)):
                reading.add((module, scope))

    assert naming == _ALLOWED_MENTIONS, (
        f"{sorted(naming ^ _ALLOWED_MENTIONS)} differ from the places a table left out of "
        "the cache key may be named; either the table belongs in the key, or the mention "
        "does not belong on the generation path")
    assert reading == {("generator.py", _SUPERSEDED_READER)}, (
        f"{sorted(reading)} read a table left out of the cache key: a simulated year would "
        "then rest on a table that rebuilding cannot invalidate")

    runners = _callers_of("main", instances._GENERATION_SOURCES)
    assert not runners, (
        f"{sorted(runners)} run another module's main; the build scripts name the tables "
        "they write, and that is safe only while the generation does not run them")

    callers = _callers_of(_SUPERSEDED_READER)
    assert callers <= _ALLOWED_CALLERS, (
        f"{sorted(callers - _ALLOWED_CALLERS)} call {_SUPERSEDED_READER}; the table it "
        "reads is left out of the cache key, so a simulated year must not depend on it")
