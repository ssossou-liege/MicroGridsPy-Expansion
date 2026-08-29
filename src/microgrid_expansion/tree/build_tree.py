"""Nest per-stage reduced outcomes into a branching scenario tree.

A node at one stage gives rise to several children at the next; the path probability
of a node is the product of the conditional branch probabilities along its path.
A two-stage program is recovered as a tree with a single decision node at the first
stage (``cfg.branching == (1, ...)`` with a star of leaves).
"""
from __future__ import annotations

from ..config import ModelConfig
from ..scenarios.assemble import ScenarioPath
from .tree_model import ScenarioTree, NodeData
from . import reduce as _reduce


def build_tree(paths: list[ScenarioPath], cfg: ModelConfig) -> ScenarioTree:
    """Build the scenario tree from the Monte-Carlo ensemble.

    The ensemble is reduced stage by stage, and the representatives are nested: every node
    of one stage gives rise to the same set of representative outcomes at the next, each
    carrying its conditional mass. That is a *fan* nesting rather than a conditional one,
    and it is the honest choice here — with two reference sites there is no basis for
    saying that a village which grew quickly to year five is more likely to grow quickly
    to year ten, and assuming otherwise would build a correlation into the tree that the
    data do not support. What the tree does carry is the persistence that *is* supported:
    the growth trajectory and the cost future are drawn once per path and held, so a
    representative outcome at a late stage inherits them from the path it comes from.

    The first stage holds a single node, the here-and-now decision; branching starts after
    it. Leaf probabilities are checked to sum to one rather than assumed to.
    """
    cfg.validate()
    stage_years = list(cfg.stage_years)
    branching = list(cfg.branching)
    if len(branching) < len(stage_years):
        branching = branching + [1] * (len(stage_years) - len(branching))

    reductions = [_reduce.reduce_stage(paths, year, branching[k], seed=cfg.seed)
                  for k, year in enumerate(stage_years)]

    tree = ScenarioTree()
    discount = 1.0 + getattr(cfg, "discount_rate", 0.08)

    def add(node: int, stage: int, parent: int | None, probability: float,
            path: ScenarioPath) -> None:
        year = stage_years[stage]
        span = (stage_years[stage + 1] - year if stage + 1 < len(stage_years)
                else getattr(cfg, "horizon_years", 25) - year)
        tree.nodes.append(node)
        tree.stage[node] = stage
        tree.parent[node] = parent
        tree.children[node] = []
        tree.prob[node] = probability
        tree.disc[node] = discount ** (-year)
        tree.n_years[node] = max(int(span), 1)
        draw = next(d for d in path.draws if d.stage_year == year)
        tree.node_data[node] = NodeData(
            demand=path.demand[year], pv_unit=path.pv_unit[year], t_amb=path.t_amb[year],
            costs=draw.costs, resource=draw.resource, policy=draw.policy,
            grid_connected=getattr(draw, "grid_connected", False))
        if parent is not None:
            tree.children[parent].append(node)

    counter = 0
    root_path = paths[reductions[0].representatives[0]]
    add(counter, 0, None, 1.0, root_path)
    frontier = [0]
    counter += 1

    for stage in range(1, len(stage_years)):
        reduction = reductions[stage]
        next_frontier = []
        for parent in frontier:
            for index, weight in zip(reduction.representatives, reduction.weights):
                add(counter, stage, parent, tree.prob[parent] * float(weight),
                    paths[index])
                next_frontier.append(counter)
                counter += 1
        frontier = next_frontier

    tree.leaves = [n for n in tree.nodes if not tree.children[n]]
    tree.check_probabilities()
    tree.reduction_error = {stage_years[k]: r.error for k, r in enumerate(reductions)}
    return tree
