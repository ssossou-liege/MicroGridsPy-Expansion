"""Build the xarray coordinate system shared by all model variables.

Dimensions (formulation, Section "Sets and indices"):

* ``node``  -- scenario-tree node n.
* ``rday``  -- representative day t within a node.
* ``htod``  -- hour-of-day h in 0..23.
* ``gsize`` -- generator catalogue option s (single active unit; the PV array, battery
  and inverter are modular integer counts, not catalogue dimensions).

Because the number of representative days is uniform across nodes in the skeleton,
dispatch variables live on the dense ``(node, rday, htod)`` grid. Per-node scalars
(stage, parent, prob, disc, n_years) are carried as aligned coordinates, not extra
dimensions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import ModelConfig
from ..tree.tree_model import ScenarioTree
from ..timedomain.rep_days import RepDays


@dataclass
class Coords:
    """Coordinate arrays and aligned per-node attributes for model construction.

    The operating axis is a single continuous ``step`` per node rather than a day-by-hour
    grid, because the storage recursion has to run across the whole of a node's year. Split
    into independent days, the programme opens each one at the same state of charge and is
    handed a free recharge every morning — three hundred and sixty-five of them a year,
    worth about a sixth of the annualised cost on the reference site, and enough to put the
    lower bound below anything the plant could actually achieve.
    """

    node: np.ndarray
    step: np.ndarray
    gsize: np.ndarray
    parent: dict[int, int | None]
    prob: pd.Series          # indexed by node
    disc: pd.Series
    n_years: pd.Series
    hour_weight: np.ndarray  # days each hour stands for


def build_coords(
    tree: ScenarioTree,
    rep: dict[int, RepDays],
    cfg: ModelConfig,
) -> Coords:
    """Assemble the coordinate system from the tree, representative days and config."""
    nodes = np.array(tree.nodes)
    days = rep[int(nodes[0])]
    steps = np.arange(days.n_days * 24)
    return Coords(
        node=nodes,
        step=steps,
        gsize=np.arange(len(cfg.gen_catalog_kw)),
        parent=tree.parent,
        prob=pd.Series(tree.prob),
        disc=pd.Series(tree.disc),
        n_years=pd.Series(tree.n_years),
        hour_weight=np.repeat(days.weight, 24),
    )
