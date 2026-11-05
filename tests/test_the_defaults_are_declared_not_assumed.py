"""Every read of a ``config`` constant outside ``config`` is declared here, with its reason.

``config`` derives its constants from ``default_settings()`` once, at import. Reading one of
them inside a calculation therefore answers about the default village, whatever project was
handed in -- and that is invisible in this repository's results, which use the defaults
throughout. Six such readings were found at once and repaired; this test exists so the
seventh has to be argued for rather than merely written.

A read is admissible in two shapes, and the whitelist records which:

* ``field`` or ``default`` -- a dataclass field or a parameter default, which a caller
  replaces. Admissible only where *every production caller does replace it*, and the entry
  says which caller.
* ``module`` or ``body`` -- a module-level constant or a read inside a function. Admissible
  only in the demonstration layer and in the diagnostic commands, which have no project to
  be handed.

The classification is made on the syntax tree rather than by name, so moving a read from a
default into a function body is a change this test sees.
"""
from __future__ import annotations

import ast
from pathlib import Path

import microgrid_expansion

PACKAGE = Path(microgrid_expansion.__file__).parent

#: Why a module may read a default out of ``config``. One reason per module and shape, and
#: the reason names what replaces it in production.
_TOY = ("the demonstration layer: ToyInstance and the two rule functions of the L1 "
        "exposition, reached by their own demos and tests and by nothing in the pipeline")
_ECONOMICS = ("defaults of the Economics bag, replaced in production by "
              "Economics.from_settings, which certify and certify_exhaustive call")
_OPERATING = ("defaults of the operating models, replaced in production by "
              "BatteryModel.from_spec, GeneratorModel.from_spec and the Controller built "
              "from settings.controller")
_APPRAISAL = ("the horizon and the rate of the appraisal, passed by "
              "post.appraisal.price_certified_design from the project's economics")
_DIAGNOSTIC = ("a verification command with no project to be handed: it runs the ordering "
               "check at the package defaults and reports on them")

ALLOWED: dict[tuple[str, str, str], str] = {
    ("exact/controller.py", "GEN_MIN_LOAD_FRAC", "module"): _TOY,
    ("exact/dispatch.py", "GEN_MIN_LOAD_FRAC", "body"): _TOY,
    ("exact/verify_bound.py", "DC_AC_RATIO_MAX", "body"): _DIAGNOSTIC,
    ("post/kpis.py", "DISCOUNT_RATE", "body"): (
        "the fallback of node_kpis' own rate argument, which run.py and ui.engine pass "
        "from settings.economics.discount_rate"),
}
for _name in ("PV_UNIT_KW", "BATT_UNIT_KWH", "INV_UNIT_KW", "GEN_CATALOG_KW",
              "GEN_SALVAGE_FRAC", "PV_COST_USD_KW", "BATT_COST_USD_KWH",
              "INV_COST_USD_KW", "GEN_COST_USD_KVA", "VOLL_USD_KWH", "ETA_CHARGE",
              "ETA_DISCHARGE", "SOC_MIN_FRAC", "SOC_MAX_FRAC", "GEN_MIN_LOAD_FRAC"):
    ALLOWED[("exact/dispatch.py", _name, "field")] = _TOY
for _name in ("PV_COST_USD_KW", "BATT_COST_USD_KWH", "INV_COST_USD_KW",
              "GEN_COST_USD_KVA", "PV_OM_RATE", "BATT_OM_RATE", "INV_OM_RATE",
              "GEN_OM_RATE", "PV_LIFETIME_Y", "BATT_LIFETIME_Y", "INV_LIFETIME_Y",
              "GEN_LIFETIME_Y", "CONV_STRING_USD_KW", "CONV_OM_RATE", "CONV_LIFETIME_Y",
              "DIESEL_PRICE_USD_L", "VOLL_USD_KWH", "DISCOUNT_RATE"):
    ALLOWED[("exact/lower_bound.py", _name, "field")] = _ECONOMICS
for _name in ("ETA_CHARGE", "ETA_DISCHARGE", "SOC_MIN_FRAC", "SOC_MAX_FRAC",
              "BATTERY_CHEMISTRY", "GEN_MIN_LOAD_FRAC", "DIESEL_PRICE_USD_L"):
    ALLOWED[("exact/simulator.py", _name, "field")] = _OPERATING
ALLOWED[("exact/simulator.py", "VOLL_USD_KWH", "default")] = (
    "the default of Dispatch.operating_cost, which certify passes from "
    "economics.voll_usd_kwh and the appraisal from the project's economics")
for _module in ("post/economics.py", "post/finance.py"):
    for _name in ("PROJECT_YEARS", "DISCOUNT_RATE"):
        ALLOWED[(_module, _name, "default")] = _APPRAISAL


def _reads(path: Path) -> list[tuple[str, str, int]]:
    """Every ``config.CONSTANT`` in one module, with the shape it is read in."""
    found: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, kind: str) -> None:
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "config" and node.attr.isupper()):
            found.append((node.attr, kind, node.lineno))
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d]
            for default in defaults:
                visit(default, "default")
            for statement in node.body:
                visit(statement, "body")
            return
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                visit(statement,
                      "field" if isinstance(statement, (ast.AnnAssign, ast.Assign))
                      else kind)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, kind)

    for statement in ast.parse(path.read_text(encoding="utf-8")).body:
        visit(statement, "module")
    return found


def _every_read() -> dict[tuple[str, str, str], list[str]]:
    out: dict[tuple[str, str, str], list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "config.py":
            continue
        module = str(path.relative_to(PACKAGE))
        for name, kind, line in _reads(path):
            out.setdefault((module, name, kind), []).append(f"{module}:{line}")
    return out


def test_no_calculation_reads_a_constant_it_was_not_allowed_to() -> None:
    """A new read of a config constant must be argued for in the whitelist above."""
    undeclared = {key: where for key, where in _every_read().items()
                  if key not in ALLOWED}
    assert not undeclared, (
        "these reads of config constants are not declared in ALLOWED; either take the "
        "figure from the settings the caller was handed, or add the entry with the "
        f"production caller that replaces it: {undeclared}")


def test_the_whitelist_holds_no_entry_that_has_gone() -> None:
    """A whitelist that outlives what it excused stops describing the code."""
    stale = sorted(key for key in ALLOWED if key not in _every_read())
    assert not stale, f"these entries no longer match any read: {stale}"


def test_every_entry_says_why() -> None:
    """An entry without a reason is a reader asking the next one to guess."""
    thin = sorted(key for key, reason in ALLOWED.items() if len(reason) < 40)
    assert not thin, f"these entries need a reason: {thin}"
