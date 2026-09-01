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


def test_the_generation_sources_are_the_ones_the_generator_reaches() -> None:
    """The listed modules must actually be on the path from tables to demand."""
    source = (DEMAND_DIR / "generator.py").read_text(encoding="utf-8")
    reached = {node.module for node in ast.walk(ast.parse(source))
               if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module}
    reached.add("generator")
    # archetypes is reached from instances rather than from the generator itself.
    reached.add("archetypes")
    listed = {name[:-3] for name in instances._GENERATION_SOURCES}
    assert listed == reached, f"listed {sorted(listed)} but the generator reaches {sorted(reached)}"


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
    real = instances.REFERENCE_DIR
    copy = tmp_path / "reference"
    copy.mkdir()
    for csv in real.glob("*.csv"):
        (copy / csv.name).write_bytes(csv.read_bytes())
    monkeypatch.setattr(instances, "REFERENCE_DIR", copy)
    before = instances._demand_fingerprint()
    target = sorted(copy.glob("*.csv"))[0]
    target.write_text(target.read_text() + "\n", encoding="utf-8")
    assert instances._demand_fingerprint() != before


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


@pytest.mark.parametrize("name", ["generator.py", "growth.py", "productive.py",
                                  "archetypes.py"])
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
