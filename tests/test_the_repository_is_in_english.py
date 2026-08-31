"""The published repository is in English, and stays that way.

The work is French-speaking and the tool is not: it is meant to be picked up by developers
who have no reason to read French, and half-translated software is worse than either
language alone -- a reader meets a French error message at the one moment they most need to
understand it.

Translating once was easy. Keeping it translated is not, because French is the language the
work is thought in and it comes back a comment at a time. So this asserts what a reviewer
would otherwise have to notice by eye.

Three things are deliberately exempt, and each is exempt for a reason rather than by
oversight:

* the translation catalogue, whose whole purpose is to hold both languages;
* the survey strings the activity classifier is tested against, which are data transcribed
  from the enumerators' sheets and would test a survey nobody ran if they were changed;
* the character class that lets a user name a project in their own language.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Only what git tracks. The supervisor's follow-up and the presentations live in this
#: working tree and are deliberately never pushed; they are written in French because that
#: is the language they are read in, and they are none of this test's business.
SUFFIXES = {".py", ".js", ".md", ".html", ".css", ".toml", ".yml", ".yaml", ".cfg", ".txt"}

EXEMPT = {
    "src/microgrid_expansion/ui/i18n.py",           # the catalogue: both languages, by design
    "tests/test_productive_demand.py",              # survey strings, transcribed as written
    "tests/test_the_repository_is_in_english.py",   # this file names what it forbids
}

#: A vendored library keeps whatever its authors wrote.
EXEMPT_DIRS = ("vendor/",)

ACCENTED = re.compile(r"[éèêëàâäçôöûùüîïœÉÈÊËÀÂÄÇÔÖÛÙÜÎÏŒ]")

#: A line may keep its accented characters by saying why, on the line itself or in the
#: comment above it. Used where the accents are not prose at all -- a character class that
#: lets a user name a project in their own language.
PERMITTED = "accents intentional"

#: Words that are French and are not also English, abbreviations, or identifiers. Kept short
#: on purpose: a long list catches variable names and file paths, and a test that cries wolf
#: gets suppressed rather than heeded.
FRENCH_WORDS = re.compile(
    r"(?<![\w-])(?:le|la|les|des|une|dans|pour|avec|cette|qui|sont|donc|chaque|entre|sans|"
    r"leur|mais|aussi|nous|vous|ainsi|alors|comme|quand|dont|est|par|plus|tout|toute|"
    r"aux|ses|son|elle|ils|elles|nest|cest|selon|puis|celui|celle|deja|encore|"
    r"parce|lorsque|afin|depuis|jusqu|avant|apres|pendant|toujours|jamais)(?![\w-])",
    re.IGNORECASE,
)

#: English words the pattern above would otherwise claim. "on", "in", "or", "do", "no", "it",
#: "son" (a person's), "est" (as in east) and the rest are excluded by not being listed; these
#: are the ones that share a spelling with a French word above.
LOOKS_FRENCH_IS_ENGLISH = re.compile(
    r"(?<![\w-])(?:la|les|des|est|son|tout|par|plus|puis|encore|comme)(?![\w-])", re.I)


def _files() -> list[Path]:
    try:
        listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                                text=True, timeout=30, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout; nothing to say about what is published")
    out = []
    for relative in sorted(listed):
        path = ROOT / relative
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if relative in EXEMPT or any(d in relative for d in EXEMPT_DIRS):
            continue
        out.append(path)
    return out


def test_the_scan_actually_reaches_the_source() -> None:
    """A glob that matched nothing would make every test below pass in silence."""
    files = _files()
    assert len(files) > 40, f"only {len(files)} files scanned; the walk is broken"
    names = {p.name for p in files}
    for expected in ("certify.py", "settings.py", "app.js", "README.md"):
        assert expected in names, f"{expected} was not reached by the scan"


def test_no_accented_french_in_the_source() -> None:
    """Accents are the cheap half of the check, and they catch most of it."""
    offenders = []
    for path in _files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            if not ACCENTED.search(line):
                continue
            above = "\n".join(lines[max(0, number - 4):number])
            if PERMITTED in above:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:90]}")
    assert not offenders, "French text in the published source:\n" + "\n".join(offenders[:20])


def test_no_unaccented_french_prose_in_the_source() -> None:
    """The other half: "le plancher de service" carries no accent at all."""
    offenders = []
    for path in _files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hits = [w for w in FRENCH_WORDS.findall(line)
                    if not LOOKS_FRENCH_IS_ENGLISH.fullmatch(w)]
            # One such word is a coincidence -- an English line may hold "la" as a note name
            # or "est" as a compass point. Two or more in one line is prose.
            if len(hits) >= 2:
                offenders.append(
                    f"{path.relative_to(ROOT)}:{number}: {line.strip()[:90]}  {hits}")
    assert not offenders, "French prose in the published source:\n" + "\n".join(offenders[:20])


@pytest.mark.parametrize("path", ["README.md", "pyproject.toml"])
def test_the_files_a_visitor_reads_first(path: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    assert not ACCENTED.search(text), f"{path} carries French"
