r"""Does the year-0 plant depend on which price list it is sized against?

The prices the sizing annualises come from one procurement budget, and that budget quotes
every item twice: at the supplier's gate before shipping and duty, and bought in Benin with
the importer's margin in it. This operator imports and lands its own goods, so the landed
column is the one its projects face, and that is what the settings carry. But the choice is
a reading of a payment ledger rather than a fact about the equipment, and a reader is owed
what the answer would have been under the other readings.

Four sets are run, all from the same budget of October 2025 at 607.37 FCFA to the dollar:

* *low*, the supplier's price at the port of departure with nothing added;
* *central*, the same plus the 9.56 % duty and freight measured on the payment ledger. This
  is what the settings carry and what every other result in this work uses;
* *high*, the budget's local column wherever it has one. The generating sets of 30, 66 and
  80 kVA have no local price, so the 20 kVA one carries that family;
* *BYD storage*, the central set with the cells at the price of the BYD modules alone. The
  extensions of both reference villages are budgeted in BYD, while the capacity-weighted
  price is mostly DEYE, so this is the set the next extension would actually be bought at.

Every set carries the balance of plant that scales with its capacity, on its own basis, so
the comparison is between like figures rather than between a bare module and a wired array.

One capacity cannot move: the string inverters an alternating-coupled array needs. The
operator's budget buys none -- it builds on hybrid inverters -- so there is one quotation
for them, on the Beninese market, and it stands in all four sets. Every set therefore prices
the alternating side at retail, which tilts each of them the same way and by the same
amount; the divided array's selection should not be read as settled from this study.

What the study is for is a comparison with the noise, and nothing is concluded without it.
The same question asked of the same village with a different random draw moves the root by
tens of per cent, so a root that moves less than that between two price sets has not moved.
The noise is measured here on the central set rather than borrowed, because it is a property
of the draw *at these prices* and the prices are what the study changes.

The programme's values are exact to the solver's tolerance; the descent's are upper bounds,
and a difference between two of them is an estimate. Both are reported for every set.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

from ..config import ModelConfig
from ..model import build_model
from ..paths import RESULTS_DIR
from ..post import extract_solution
from ..run import _NodeInstance
from ..scenarios import sample_scenario_paths, space_from_settings
from ..settings import ProjectSettings, default_settings
from ..solve import solve
from ..timedomain import reduce_to_rep_days
from ..tree import build_tree
from .first_stage import _root_of
from .tree_certify import certify_tree
from .tree_value import _head

#: What one unit of each capacity costs, in dollars, on each basis. The figures beside each
#: are the FCFA the budget quotes, converted at 607.37; the array and the storage carry the
#: balance of plant that scales with them, derived by ``build_equipment_prices``.
#:
#: The string inverter is absent on purpose: it has one price and keeps it, see the module
#: docstring. The generator is per kVA, every other figure per kW or kWh.
PRICE_SETS: dict[str, dict[str, float]] = {
    # 83 848 / 61 949 / 64 699 / 80 224 FCFA, offshore, nothing added.
    "low": {"array_usd_kw": 138.05, "storage_usd_kwh": 102.00,
            "conversion_usd_kw": 106.52, "generator_usd_kva": 132.08},
    # 91 864 / 67 872 / 70 884 / 87 893 FCFA, the offshore price plus 9.56 %.
    "central": {"array_usd_kw": 151.2, "storage_usd_kwh": 111.7,
                "conversion_usd_kw": 116.7, "generator_usd_kva": 144.7},
    # 265 340 / 124 552 / 108 894 / 325 000 FCFA, bought in Benin.
    "high": {"array_usd_kw": 436.95, "storage_usd_kwh": 205.07,
             "conversion_usd_kw": 179.29, "generator_usd_kva": 535.09},
    # The central set with the cells at the BYD price: 124 898 FCFA/kWh landed, which is
    # the 205.6 the budget implies, plus the 8.4 of rack, busbars, cable and lugs that the
    # central set carries too.
    "byd": {"array_usd_kw": 151.2, "storage_usd_kwh": 214.0,
            "conversion_usd_kw": 116.7, "generator_usd_kva": 144.7},
}

#: The set every other result in this work is computed on.
REFERENCE = "central"

#: The capacities a reader compares, and how to read each off a root.
PARTS = (("field_kw", lambda r: r["pv_kw"] + r["pv_ac_kw"]),
         ("storage_kwh", lambda r: r["battery_kwh"]),
         ("conversion_kw", lambda r: r["inverter_kw"]),
         ("generator_kw", lambda r: r["generator_kw"]))


def settings_at(prices: dict[str, float]) -> ProjectSettings:
    """The project settings with one price set in place of the defaults."""
    settings = default_settings()
    settings.photovoltaic = replace(settings.photovoltaic,
                                    cost_usd_kw=prices["array_usd_kw"])
    settings.battery = replace(settings.battery, cost_usd_kwh=prices["storage_usd_kwh"])
    settings.inverter = replace(settings.inverter,
                                cost_usd_kw=prices["conversion_usd_kw"])
    settings.generators = [replace(g, cost_usd_kva=prices["generator_usd_kva"])
                           for g in settings.generators]
    return settings


def solve_once(cfg: ModelConfig, settings: ProjectSettings, verbose: bool = True) -> dict:
    """One tree, under the programme and then under the controller that will run it."""
    started = time.perf_counter()
    tree = build_tree(
        sample_scenario_paths(cfg, space_from_settings(settings), settings), cfg)
    tree.check_probabilities()
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), cfg.n_rep_days)
           for n in tree.nodes}
    architecture = settings.coupling.architectures()[0]

    at = time.perf_counter()
    programme = build_model(tree, rep, cfg, architecture=architecture, settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    if solved.objective == float("inf"):
        raise RuntimeError("no feasible plan at these prices")
    plans = extract_solution(programme, cfg, settings)
    programme_seconds = time.perf_counter() - at

    at = time.perf_counter()
    certificate = certify_tree(plans, tree, rep, solved.bound, architecture=architecture,
                               settings=settings, verbose=verbose)
    return {
        "architecture": architecture,
        "programme": {"expected_usd": float(solved.objective),
                      "bound_usd": float(solved.bound),
                      "root": _root_of(plans, tree),
                      "seconds": round(programme_seconds, 1)},
        "automaton": {"expected_usd": float(certificate.z_rule),
                      "root": _root_of(certificate.plans, tree),
                      "evaluations": certificate.evaluations,
                      "seconds": round(time.perf_counter() - at, 1)},
        "seconds_total": round(time.perf_counter() - started, 1),
    }


def _span(roots: list[dict], costs: list[float]) -> dict:
    """How far the answer moves when nothing changes but the seed."""
    out = {"expected_usd": {"least": min(costs), "most": max(costs),
                            "span": max(costs) - min(costs),
                            "span_pct": 100.0 * (max(costs) - min(costs)) / min(costs)}}
    for name, read in PARTS:
        values = [read(r) for r in roots]
        out[name] = {"least": min(values), "most": max(values),
                     "span": max(values) - min(values)}
    return out


def derive(stored: dict) -> dict:
    """Which price sets move the root further than the draw does, and which do not."""
    out = {}
    for oracle in ("programme", "automaton"):
        noise = stored["noise"][oracle]
        reference = stored["sets"][REFERENCE][oracle]["root"]
        sets = {}
        for name, block in stored["sets"].items():
            root, moved = block[oracle]["root"], {}
            for part, read in PARTS:
                shift = abs(read(root) - read(reference))
                moved[part] = {
                    "value": read(root),
                    "shift_from_reference": round(shift, 3),
                    "noise_span": round(noise[part]["span"], 3),
                    # A shift no larger than the span the seed alone produces is not a
                    # movement that can be attributed to the prices.
                    "beyond_the_noise": bool(shift > noise[part]["span"] + 1e-9),
                }
            sets[name] = {
                "expected_usd": block[oracle]["expected_usd"],
                "parts": moved,
                "any_part_beyond_the_noise": any(p["beyond_the_noise"]
                                                 for p in moved.values()),
            }
        out[oracle] = {"noise": noise, "sets": sets}
    return out


def draw_figure(stored: dict, path: Path, oracle: str = "programme") -> Path:
    """The year-0 plant under each price set, over the band the draw alone produces."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    block = stored["derived"][oracle]
    names = [n for n in PRICE_SETS if n in block["sets"]]
    # Kept short: four of them share the width of one panel.
    labels = {"low": "offshore\nno landing", "central": "landed\nreference",
              "high": "bought\nin Benin", "byd": "landed\nBYD cells"}

    fig, axes = plt.subplots(1, 3, figsize=(12.0, 4.0), sharex=True)
    for ax, (part, unit) in zip(axes, (("field_kw", "kW"), ("storage_kwh", "kWh"),
                                       ("conversion_kw", "kW"))):
        values = [block["sets"][n]["parts"][part]["value"] for n in names]
        reference = block["sets"][REFERENCE]["parts"][part]["value"]
        half = 0.5 * block["noise"][part]["span"]
        x = np.arange(len(names))
        ax.axhspan(reference - half, reference + half, color="0.86", zorder=0,
                   label="what the seed alone moves it by")
        ax.bar(x, values, color=["C0" if n != REFERENCE else "C1" for n in names],
               width=0.62, zorder=2)
        for k, v in enumerate(values):
            ax.annotate(f"{v:,.1f}", (k, v), ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x)
        ax.set_xticklabels([labels.get(n, n) for n in names], fontsize=8)
        ax.set_ylabel(f"{part.rsplit('_', 1)[0]} [{unit}]")
        ax.set_ylim(0.0, 1.22 * max(values))
    axes[0].legend(fontsize=7, loc="upper left")
    fig.suptitle(f"{stored['site']}: the year-0 plant against the price list "
                 f"({oracle}, seed {stored['config']['seed']}, "
                 f"noise over seeds {stored['config']['noise_seeds']})", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    defaults = ModelConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--seed", type=int, default=defaults.seed,
                        help="the seed every price set is drawn on")
    parser.add_argument("--noise-seeds", type=int, nargs="+", default=[0, 1, 2],
                        help="the seeds the reference set is repeated on, to measure "
                             "what the draw alone moves")
    parser.add_argument("--sets", nargs="+", default=list(PRICE_SETS),
                        choices=list(PRICE_SETS))
    parser.add_argument("--rep-days", type=int, default=defaults.n_rep_days)
    parser.add_argument("--mc-paths", type=int, default=defaults.n_mc_paths)
    parser.add_argument("--stage-years", type=int, nargs="+",
                        default=list(defaults.stage_years))
    parser.add_argument("--branching", type=int, nargs="+",
                        default=list(defaults.branching))
    parser.add_argument("--solver", default=defaults.solver)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--figure-only", action="store_true")
    args = parser.parse_args(argv)

    out = args.out or RESULTS_DIR / f"summary_price_sensitivity_{args.site.lower()}.json"
    if args.figure_only:
        drawn = draw_figure(json.loads(out.read_text()),
                            out.with_name(f"price_sensitivity_{args.site.lower()}.png"))
        print(f"written {drawn}")
        return 0

    base = ModelConfig(solver=args.solver, n_rep_days=args.rep_days,
                       n_mc_paths=args.mc_paths, seed=args.seed,
                       stage_years=tuple(args.stage_years),
                       branching=tuple(args.branching))
    base.site = args.site
    base.validate()

    started = time.perf_counter()
    stored = {"site": args.site, "commit": _head(),
              "config": {"seed": args.seed, "noise_seeds": list(args.noise_seeds),
                         "n_mc_paths": base.n_mc_paths, "n_rep_days": base.n_rep_days,
                         "stage_years": list(base.stage_years),
                         "branching": list(base.branching), "solver": base.solver},
              "price_sets": {n: PRICE_SETS[n] for n in args.sets},
              "string_inverter_usd_kw":
                  default_settings().coupling.string_inverter_cost_usd_kw,
              "sets": {}, "noise": {}}

    # The reference set first, on every noise seed: its own seed is one of them when it is
    # in the list, so the set is never solved twice for the same draw.
    runs: dict[int, dict] = {}
    for seed in dict.fromkeys([args.seed, *args.noise_seeds]):
        print(f"\n## {REFERENCE} prices, seed {seed}", flush=True)
        runs[seed] = solve_once(replace(base, seed=seed), settings_at(PRICE_SETS[REFERENCE]))
    stored["sets"][REFERENCE] = runs[args.seed]
    stored["noise"] = {
        oracle: _span([runs[s][oracle]["root"] for s in args.noise_seeds],
                      [runs[s][oracle]["expected_usd"] for s in args.noise_seeds])
        for oracle in ("programme", "automaton")}
    stored["noise_by_seed"] = {
        str(s): {o: {"root": runs[s][o]["root"], "expected_usd": runs[s][o]["expected_usd"]}
                 for o in ("programme", "automaton")} for s in args.noise_seeds}

    for name in args.sets:
        if name == REFERENCE:
            continue
        print(f"\n## {name} prices, seed {args.seed}", flush=True)
        stored["sets"][name] = solve_once(base, settings_at(PRICE_SETS[name]))

    stored["derived"] = derive(stored)
    stored["seconds_total"] = round(time.perf_counter() - started, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stored, indent=2), encoding="utf-8")

    for oracle in ("programme", "automaton"):
        block = stored["derived"][oracle]
        print(f"\n== {oracle} ==")
        noise = block["noise"]
        print(f"   seed to seed: field {noise['field_kw']['span']:.1f} kW, "
              f"storage {noise['storage_kwh']['span']:.0f} kWh, "
              f"conversion {noise['conversion_kw']['span']:.1f} kW, "
              f"cost {noise['expected_usd']['span_pct']:.1f} %")
        for name in args.sets:
            s = block["sets"][name]
            parts = " ".join(
                f"{p.rsplit('_', 1)[0]} {s['parts'][p]['value']:>6.1f}"
                f"{'*' if s['parts'][p]['beyond_the_noise'] else ' '}"
                for p, _ in PARTS)
            print(f"   {name:8s} {s['expected_usd']:>11,.0f} $   {parts}")
        moved = [name for name in args.sets
                 if block["sets"][name]["any_part_beyond_the_noise"]]
        print("   * moved further than the draw alone moves it" if moved else
              "   no capacity moved further than the draw alone moves it")

    drawn = draw_figure(stored,
                        out.with_name(f"price_sensitivity_{args.site.lower()}.png"))
    print(f"\nwritten {out}\nwritten {drawn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
