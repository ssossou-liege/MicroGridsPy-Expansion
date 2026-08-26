"""Write solution summaries to the results directory."""
from __future__ import annotations

import json
from pathlib import Path

from ..tree.tree_model import ScenarioTree


def write_report(plans: dict, kpis: list[dict], expected: dict, tree: ScenarioTree,
                 out_dir: Path, stem: str = "summary_tree") -> Path:
    """Record the plan, its indicators and how much the tree compressed.

    The reduction error travels with the result rather than in a log: a tree is a
    compression, and a compression whose distortion is not reported invites the reader to
    treat it as exact.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "nodes": len(tree.nodes),
        "leaves": len(tree.leaves),
        "stages": sorted(set(tree.stage.values())),
        "reduction_error": tree.reduction_error,
        "expected": expected,
        "root_plan": {
            "pv_kw": plans[0].pv_kw, "battery_kwh": plans[0].battery_kwh,
            "inverter_kw": plans[0].inverter_kw, "generator_kw": plans[0].generator_kw,
        },
        "per_node": kpis,
    }
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps(record, indent=2, default=float))
    return path
