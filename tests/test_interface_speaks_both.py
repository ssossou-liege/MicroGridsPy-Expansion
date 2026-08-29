"""The page says the same thing in either language, and says it at all.

An interface translated by hand rots in three ways, all of them silent. A string added to
the page and forgotten in the catalogue renders as its own key, so the reader is shown
``f.tariff.hint`` where a sentence belongs. A string translated into one language and not
the other falls back without saying so, and a French reader meets an English sentence in
the middle of a French form. And a placeholder dropped in translation — ``{site}`` in the
English, absent in the French — silently loses the one part of the sentence that carried
the information.

None of these break anything the other tests exercise: the model is unaffected, the server
answers, the page renders. They are only visible to someone reading the page, which is why
they are asserted here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from microgrid_expansion.ui import i18n, projects, schema

STATIC = Path(i18n.__file__).parent / "static"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _keys_the_page_asks_for() -> set[str]:
    """Every catalogue key the page reaches for, from the script and the markup."""
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    markup = (STATIC / "index.html").read_text(encoding="utf-8")
    keys = set(re.findall(r'T\("([^"]+)"', script))
    keys |= set(re.findall(r'data-t="([^"]+)"', markup))
    # T("job." + job.status) is assembled at run time; its four values are named here so the
    # test still covers them.
    keys.discard("job.")
    keys |= {f"job.{s}" for s in ("running", "done", "failed", "cancelled")}
    return keys


def test_every_string_exists_in_both_languages() -> None:
    incomplete = {k: v for k, v in i18n.STRINGS.items()
                  if not v.get("en") or not v.get("fr")}
    assert not incomplete, f"catalogue entries missing a language: {sorted(incomplete)}"


def test_the_page_never_shows_a_key() -> None:
    asked = _keys_the_page_asks_for()
    # A regex that matched nothing would make this test pass without reading the page.
    assert len(asked) > 100, f"only {len(asked)} keys found; the scan is broken, not the page"
    missing = sorted(k for k in asked if k not in i18n.STRINGS)
    assert not missing, f"the page asks for strings the catalogue does not carry: {missing}"


def test_placeholders_survive_translation() -> None:
    """{site} in one language and not the other loses the site's name, quietly."""
    drifted = {
        key: (sorted(PLACEHOLDER.findall(entry["en"])),
              sorted(PLACEHOLDER.findall(entry["fr"])))
        for key, entry in i18n.STRINGS.items()
        if sorted(PLACEHOLDER.findall(entry["en"]))
        != sorted(PLACEHOLDER.findall(entry["fr"]))
    }
    assert not drifted, f"placeholders differ between languages: {drifted}"


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_every_form_field_is_translated(lang: str) -> None:
    """A field whose key is missing renders its key as its label. Catch that here."""
    groups = schema.describe(lang=lang)
    assert sum(len(g["fields"]) for g in groups) >= 30
    for group in groups:
        assert not group["title"].startswith(("group.", "f.")), group["title"]
        for field in group["fields"]:
            assert field["label"], f"{field['path']} has no label in {lang}"
            assert not field["label"].startswith("f."), field["label"]
            assert not field["hint"].startswith("f."), field["hint"]


def test_a_field_without_a_hint_shows_nothing_rather_than_its_key() -> None:
    """Several fields carry no hint; the catalogue has no entry for them by design."""
    hints = [f["hint"] for g in schema.describe(lang="en") for f in g["fields"]]
    assert "" in hints, "expected at least one field with no hint"
    assert not any(h.endswith(".hint") for h in hints)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_exports_follow_the_language(lang: str) -> None:
    result = {"site": "Samionta", "design": {"pv_kw": 32.5}, "lcoe_usd_kwh": 0.246}
    body = projects.as_csv(result, "size", lang)
    header = body.splitlines()[0]
    assert not header.startswith("csv."), header
    assert header == ("Quantity;Value" if lang == "en" else "Grandeur;Valeur")
    assert "Samionta" in body


def test_the_two_languages_are_actually_different() -> None:
    """A French catalogue copied from the English would pass every test above."""
    same = [k for k, v in i18n.STRINGS.items() if v["en"] == v["fr"]]
    # Some strings are genuinely identical in both: units, proper nouns, "Source".
    assert len(same) < len(i18n.STRINGS) // 4, f"suspiciously many untranslated: {same}"


def test_the_default_is_english() -> None:
    assert i18n.DEFAULT == "en"
    assert i18n.t("nav.community") == i18n.t("nav.community", "en")
    assert i18n.t("nav.community", "fr") != i18n.t("nav.community", "en")


def test_an_unknown_language_falls_back_rather_than_failing() -> None:
    assert i18n.t("nav.community", "de") == i18n.t("nav.community", "en")


def test_an_unknown_key_is_returned_as_itself() -> None:
    """The page renders what it gets; a missing key must be visible, not blank."""
    assert i18n.t("no.such.key") == "no.such.key"
    assert not i18n.has("no.such.key")


def test_the_catalogue_serialises_for_the_page() -> None:
    for lang in i18n.LANGUAGES:
        payload = json.dumps(i18n.catalogue(lang))
        assert len(json.loads(payload)) == len(i18n.STRINGS)


# --------------------------------------------------------------------------- the script
# The catalogue was once wired into the page by a helper that was never written: every
# string on the page rendered blank, every test above passed, and only loading the page in
# a real engine showed it. A call to something the script never declares is exactly that
# class of defect, and it is cheap to catch here.

BROWSER_GLOBALS = frozenset("""
    fetch alert confirm print parseFloat parseInt isNaN String Number Boolean Array Object
    JSON Math Date Error Promise Set Map RegExp encodeURIComponent decodeURIComponent
    setTimeout setInterval clearInterval clearTimeout requestAnimationFrame structuredClone
    Event CustomEvent Blob URL FormData Intl localStorage sessionStorage console document
    window navigator location
    if for while switch catch return typeof function async await new delete void
""".split())

CALL = re.compile(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(")
DECLARED = re.compile(
    r"(?:(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"   # function foo(), async function foo()
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)"   # const foo = ...
    r"|([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?(?:function|\())"
)


def _code_only(script: str) -> str:
    """The script with its comments and string bodies blanked out.

    Done by walking the text rather than by regular expressions: a ``//`` inside a tile URL
    and an apostrophe inside a comment each break the naive version, and they break it
    silently, by swallowing the code in between.
    """
    out, i, n = [], 0, len(script)
    # What may precede a "/" that opens a regular expression rather than dividing. A regex
    # holding a quote -- /filename="([^"]+)"/ -- reads as a string opener otherwise, and the
    # scan then swallows every line up to the next quote in the file.
    avant_regex = set("(,=:[!&|?{};+-*%~^<>") | {"return", "typeof", "case", "in", "of"}
    while i < n:
        c = script[i]
        if c == "/" and i + 1 < n and script[i + 1] not in "/*":
            precedent = "".join(out).rstrip()
            dernier = precedent[-1] if precedent else "("
            mot = precedent.split()[-1] if precedent.split() else ""
            if dernier in avant_regex or mot in avant_regex:
                i += 1
                while i < n and script[i] != "/":
                    if script[i] == "\\":
                        i += 1
                    elif script[i] == "[":                 # a class may hold an unescaped /
                        while i < n and script[i] != "]":
                            i += 2 if script[i] == "\\" else 1
                    i += 1
                i += 1
                while i < n and script[i] in "gimsuy":     # the flags
                    i += 1
                out.append(' "" ')
                continue
        if c == "/" and i + 1 < n and script[i + 1] == "/":
            while i < n and script[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and script[i + 1] == "*":
            i = script.find("*/", i + 2)
            i = n if i < 0 else i + 2
        elif c in "\"'`":
            quote, i = c, i + 1
            while i < n and script[i] != quote:
                # A template literal can hold code inside ${...}; keep it.
                if quote == "`" and script[i] == "$" and script[i + 1:i + 2] == "{":
                    depth, i = 1, i + 2
                    start = i
                    while i < n and depth:
                        depth += (script[i] == "{") - (script[i] == "}")
                        i += 1
                    out.append(" " + _code_only(script[start:i - 1]) + " ")
                    continue
                i += 2 if script[i] == "\\" else 1
            i += 1
            out.append(' "" ')
        else:
            out.append(c)
            i += 1
    return "".join(out)


def test_the_script_calls_nothing_it_never_declares() -> None:
    stripped = _code_only((STATIC / "app.js").read_text(encoding="utf-8"))

    declared = {name for match in DECLARED.finditer(stripped) for name in match.groups()
                if name}
    called = {name for name in CALL.findall(stripped)}
    unknown = sorted(called - declared - BROWSER_GLOBALS)
    assert not unknown, f"the page calls what it never declares: {unknown}"


def test_the_page_and_the_script_agree_on_the_language_picker() -> None:
    markup = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="lang"' in markup, "the page has no language picker"
    assert '$("#lang")' in script, "the script never wires the picker up"
    assert "setLanguage" in script
