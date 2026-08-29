"""Data structures describing the scenario tree.

The tree is the backbone of the formulation (Section "Sets and indices"). Each node
carries its stage, parent, path probability, discount factor and operating-years
weight, plus the reduced hourly arrays of its representative operating year.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class NodeData:
    """Reduced operating-year data and economics attached to one tree node."""

    demand: np.ndarray          # 8760 kW (pre time-domain reduction)
    pv_unit: np.ndarray         # 8760 kW/kW
    t_amb: np.ndarray           # 8760 degC
    costs: dict[str, float]     # fuel_price, capex_* for this node's stage
    resource: str               # SSP pathway
    policy: float               # penetration target
    grid_connected: bool = False   # has the national grid reached the village by now


@dataclass
class ScenarioTree:
    """Branching scenario tree (the deterministic-equivalent index structure).

    Attributes
    ----------
    nodes : list[int]
        Node identifiers; ``0`` is the root.
    stage : dict[int, int]
        Stage (milestone index) of each node.
    parent : dict[int, int | None]
        Parent node id (``None`` for the root).
    children : dict[int, list[int]]
        Child node ids.
    prob : dict[int, float]
        Path probability pi_n (product of branch probabilities to the node).
    disc : dict[int, float]
        Discount factor delta_n applied to costs at the node.
    n_years : dict[int, int]
        Operating-years weight Delta_n the node represents.
    leaves : list[int]
        Leaf nodes (complete scenarios); their probabilities sum to 1.
    node_data : dict[int, NodeData]
        Reduced operating data per node.
    """

    nodes: list[int] = field(default_factory=list)
    stage: dict[int, int] = field(default_factory=dict)
    parent: dict[int, int | None] = field(default_factory=dict)
    children: dict[int, list[int]] = field(default_factory=dict)
    prob: dict[int, float] = field(default_factory=dict)
    disc: dict[int, float] = field(default_factory=dict)
    n_years: dict[int, int] = field(default_factory=dict)
    leaves: list[int] = field(default_factory=list)
    node_data: dict[int, NodeData] = field(default_factory=dict)
    #: Mean distortion of each stage's reduction, in the scaled feature space, so
    #: that a compression which has lost something says so rather than passing.
    reduction_error: dict[int, float] = field(default_factory=dict)

    def ancestors(self, node: int) -> list[int]:
        """Return the chain from the root to ``node`` inclusive."""
        chain, cur = [], node
        while cur is not None:
            chain.append(cur)
            cur = self.parent[cur]
        return list(reversed(chain))

    def check_probabilities(self, tol: float = 1e-9) -> None:
        """Assert leaf probabilities sum to one (no silent mass loss)."""
        total = sum(self.prob[l] for l in self.leaves)
        if abs(total - 1.0) > tol:
            raise ValueError(f"Leaf probabilities sum to {total}, expected 1.0")
