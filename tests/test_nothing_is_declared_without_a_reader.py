"""A definition this package does not call says who does.

A reachability scan over the package found nine top-level definitions nothing in it
mentions. The first scan read ``src`` and ``tests`` only, and it was wrong about one of
them: ``write_hourly_series`` builds the projected meteorology the resource model reads,
and its caller is the tracked acquisition script under ``data/irradiance``, which the scan
was not looking at. A guardrail blind to half the repository argues for deleting the only
code able to rebuild a document the model depends on, which is the defect of a figure
nobody can produce again rather than a cleanup.

The scan here reads every tracked Python file, and the whitelist carries the definitions
the package itself does not call, each with the reason it is kept. The next one is then a
decision rather than an accident.
"""
from __future__ import annotations

import ast
import collections
import re
import subprocess
from pathlib import Path

import pytest

import microgrid_expansion
from microgrid_expansion.paths import REFERENCE_DIR

PACKAGE = Path(microgrid_expansion.__file__).resolve().parent
ROOT = PACKAGE.parents[1]

#: Definitions the package does not call, and who does instead.
ALLOWED: dict[tuple[str, str], str] = {
    ("demand/uses.py", "community_catalogue"):
        "a description of what the surveyed villages hold and what nobody measured, not a "
        "calculation; the tests read it to check that an unmeasured use comes back empty "
        "rather than plausible",
    ("demand/uses.py", "self_consumption_catalogue"):
        "as above, for the loads the plant meets from its own array; the street lighting "
        "is the one entry that follows from a lamp count, and the test pins that it is the "
        "only one carrying figures",
    ("resource/era5.py", "deaccumulate"):
        "states the convention of the gridded ERA5-Land product, which this project does "
        "not use: the time-series product it downloads needs no deaccumulation. Kept "
        "because a user who brings the other product needs it, and tested against a hand-"
        "computed hour so the convention cannot drift",
    ("resource/cmip6.py", "write_hourly_series"):
        "called by data/irradiance/download.py, the tracked command line over the "
        "acquisition chain; it is what rebuilds the projected meteorology document, so it "
        "is the opposite of dead code",
}


def _tracked() -> list[Path]:
    """Every Python file the repository tracks, the scripts outside ``src`` included."""
    try:
        listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py"],
                                 capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:   # pragma: no cover
        pytest.skip(f"the repository cannot be listed: {exc}")
    return [ROOT / name for name in listing.split()]


def _definitions(tracked: list[Path]) -> dict[str, list[str]]:
    """Top-level functions and classes of the package, by name.

    Tracked files only. A module another session is working on is not yet part of the
    package, and holding its definitions against it would report somebody else's work.
    """
    defined: dict[str, list[str]] = collections.defaultdict(list)
    for path in tracked:
        if PACKAGE not in path.parents:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined[node.name].append(str(path.relative_to(PACKAGE)))
    return defined


def _mentions(paths: list[Path]) -> collections.Counter:
    """How often each identifier appears, comments and docstrings included.

    Deliberately lenient: a name discussed in a comment counts as mentioned. The test is a
    ratchet against definitions nobody can reach, not a linter.
    """
    counts: collections.Counter = collections.Counter()
    for path in paths:
        counts.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*",
                                 path.read_text(encoding="utf-8")))
    return counts


def _uncalled() -> dict[tuple[str, str], list[str]]:
    tracked = _tracked()
    defined = _definitions(tracked)
    inside = _mentions([p for p in tracked if PACKAGE in p.parents])
    out = {}
    for name, files in defined.items():
        if name.startswith("__"):
            continue
        if inside[name] - len(files) <= 0:
            out[(files[0], name)] = files
    return out


def test_the_package_calls_what_it_defines_or_says_who_does() -> None:
    undeclared = sorted(key for key in _uncalled() if key not in ALLOWED)
    assert not undeclared, (
        "nothing in the package calls these, and no reason is declared for them; either "
        "give them a caller, delete them, or add them to ALLOWED with the reason: "
        + ", ".join(f"{module}:{name}" for module, name in undeclared))


def test_no_declared_reason_is_stale() -> None:
    """An allowance outlives its definition, and then it excuses nothing."""
    uncalled = _uncalled()
    stale = sorted(key for key in ALLOWED if key not in uncalled)
    assert not stale, (
        "these are declared as uncalled and are not: "
        + ", ".join(f"{module}:{name}" for module, name in stale))


def test_each_allowance_says_why() -> None:
    thin = sorted(key for key, reason in ALLOWED.items() if len(reason) < 40)
    assert not thin, f"these allowances give no reason: {thin}"


def test_the_projected_meteorology_can_be_rebuilt_by_a_tracked_command() -> None:
    """What the first scan got wrong, pinned.

    The resource layer of the scenario tree reads one document per site, and this is the
    code that writes it. If the command line over it ever goes, the document becomes a file
    the repository can read and not produce.
    """
    script = ROOT / "data" / "irradiance" / "download.py"
    assert script.exists(), "the acquisition command line is gone"
    source = script.read_text(encoding="utf-8")
    assert "write_hourly_series" in source
    assert "cmip6" in source


def _described() -> tuple[set[str], set[str]]:
    """The two lists of the reference directory's own record, as sets of table names."""
    readme = REFERENCE_DIR / "README.md"
    assert readme.exists(), f"{readme} does not exist"
    section, listed = None, {}
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
            listed.setdefault(section, set())
        elif section:
            listed[section].update(re.findall(r"`([A-Za-z0-9_]+\.csv)`", line))
    for heading in ("read at generation", "written for inspection"):
        assert heading in listed, f"the record has no '{heading}' list"
    return listed["read at generation"], listed["written for inspection"]


def test_every_reference_table_says_whether_the_generation_reads_it() -> None:
    """The directory of calibration tables states, table by table, who reads it."""
    read, inspected = _described()
    on_disk = {path.name for path in REFERENCE_DIR.glob("*.csv")}
    assert read | inspected == on_disk, (
        f"described and not there: {sorted((read | inspected) - on_disk)}; "
        f"there and not described: {sorted(on_disk - (read | inspected))}")
    assert not read & inspected, f"described on both sides: {sorted(read & inspected)}"


def test_the_record_and_the_cache_key_agree_on_which_tables_are_read() -> None:
    """The record is load-bearing, not decorative.

    The key hashes every table of the directory but the ones named in
    ``_NOT_READ_AT_GENERATION``. Five more than that are written for inspection and were
    hashed all the same, so rebuilding the segmentation to look at it rebuilt every cached
    year. The two statements of the same fact must agree, or one of them is wrong and
    nobody can tell which.
    """
    from microgrid_expansion.instances import _NOT_READ_AT_GENERATION

    _, inspected = _described()
    assert inspected == set(_NOT_READ_AT_GENERATION), (
        "the record and the key disagree; hashed although written for inspection: "
        f"{sorted(inspected - set(_NOT_READ_AT_GENERATION))}; excluded although read: "
        f"{sorted(set(_NOT_READ_AT_GENERATION) - inspected)}")
