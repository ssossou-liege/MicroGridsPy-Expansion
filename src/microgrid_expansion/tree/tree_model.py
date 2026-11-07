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
    #: Which growth trajectory the path this node represents was drawn on. The demand array
    #: above already embodies it; the label is kept because the year-0 decision has to be
    #: certifiable against the demand the tree actually put under it, and a certificate
    #: needs to name the trajectory it was built from rather than infer it from a series.
    trajectory: str = "central"
    #: The rest of the path's regime, named for the same reason: the connection trajectory
    #: (``census`` under the whole census) and the cost future. With ``trajectory`` they
    #: let persistence be checked on the tree itself rather than trusted to its builder.
    connection: str = "census"
    cost_scenario: str = "central"
    #: Households connected in the first month of the year the demand stands for, every
    #: category together, and the village age of that month.
    connected_households: int = 0
    village_age_months: int = 0


@dataclass
class ScenarioTree:
    """Branching scenario tree (the deterministic-equivalent index structure).

    Attributes
    ----------
    nodes : list[int]
        Node identifiers; ``0`` is the root.
    stage : dict[int, int]
        Stage (milestone index) of each node. In a persistent tree the operating-only nodes
        below the root stand at stage 0 beside it.
    parent : dict[int, int | None]
        Parent node id (``None`` for the root).
    children : dict[int, list[int]]
        Child node ids.
    prob : dict[int, float]
        Path probability pi_n (product of branch probabilities to the node).
    disc : dict[int, float]
        Discount factor delta_n applied to costs at the node.
    n_years : dict[int, int]
        Operating-years weight Delta_n the node represents; zero at a persistent root whose
        span is operated by the nodes below it.
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
    #: The rate ``disc`` was computed at. A tree is evidence, and what it was discounted at
    #: has to travel with it: the capital charged against its nodes must be recovered at the
    #: same rate, and a consumer handed a tree and a settings object cannot otherwise tell
    #: whether the two agree. ``None`` on a tree assembled by hand, which claims nothing.
    discount_rate: float | None = None
    #: How the tree was nested, ``fan`` or ``persistent`` (``ModelConfig.tree_mode``).
    tree_mode: str = "fan"
    #: Nodes that may add capacity. A node absent from it invests, which is every node of
    #: a fan; a node mapped to ``False`` holds its parent's plant and buys nothing, which is
    #: what the operating-only nodes below a persistent root are.
    invests: dict[int, bool] = field(default_factory=dict)
    #: The five measures of what the reduction lost (``tree.reduce.distortion``).
    distortion: dict = field(default_factory=dict)

    def invests_at(self, node: int) -> bool:
        """Whether the plan may add capacity at ``node``."""
        return bool(self.invests.get(node, True))

    def operates(self, node: int) -> bool:
        """Whether ``node`` stands for any operating year; a persistent root may not."""
        return self.n_years[node] > 0

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
