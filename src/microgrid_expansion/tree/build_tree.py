"""Nest reduced outcomes into a branching scenario tree.

A node at one stage gives rise to several children at the next; the path probability
of a node is the product of the conditional branch probabilities along its path.
A two-stage program is recovered as a tree with a single decision node at the first
stage (``cfg.branching == (1, ...)`` with a star of leaves).

Two nestings are built (``cfg.tree_mode``). The *fan* reduces each stage over the whole
ensemble and hangs the same children below every node of a stage. The *persistent* tree
branches over regimes at the first milestone after the root and holds each regime below
its branch, so that along every path the connection trajectory, the growth trajectory and
the cost future are those of one village.
"""
from __future__ import annotations

from ..config import ModelConfig
from ..scenarios.assemble import ScenarioPath
from .tree_model import ScenarioTree, NodeData
from . import reduce as _reduce


def build_tree(paths: list[ScenarioPath], cfg: ModelConfig) -> ScenarioTree:
    """Build the scenario tree from the Monte-Carlo ensemble, as ``cfg.tree_mode`` asks.

    Either way the first stage holds a single node, the here-and-now decision; leaf
    probabilities are checked to sum to one rather than assumed to, and the tree carries
    the distortion of its reduction measured on the ensemble it was drawn from.
    """
    cfg.validate()
    if cfg.tree_mode == "persistent":
        return _persistent(paths, cfg)
    return _fan(paths, cfg)


def _add(tree: ScenarioTree, cfg: ModelConfig, node: int, stage: int,
         parent: int | None, probability: float, path: ScenarioPath,
         operates: bool = True, invests: bool = True) -> None:
    """Attach one node, carrying the stage-``stage`` arrays of ``path``."""
    year = cfg.stage_years[stage]
    tree.nodes.append(node)
    tree.stage[node] = stage
    tree.parent[node] = parent
    tree.children[node] = []
    tree.prob[node] = probability
    tree.disc[node] = (1.0 + float(cfg.discount_rate)) ** (-year)
    tree.n_years[node] = cfg.spans()[stage] if operates else 0
    if not invests:
        tree.invests[node] = False
    draw = next(d for d in path.draws if d.stage_year == year)
    tree.node_data[node] = NodeData(
        demand=path.demand[year], pv_unit=path.pv_unit[year], t_amb=path.t_amb[year],
        costs=draw.costs, resource=draw.resource, policy=draw.policy,
        grid_connected=getattr(draw, "grid_connected", False),
        trajectory=str(getattr(draw, "trajectory", "central")),
        connection=str(getattr(draw, "connection", "census")),
        cost_scenario=str(getattr(draw, "cost_scenario", "central")),
        connected_households=int(getattr(draw, "connected_households", 0)),
        village_age_months=int(getattr(draw, "village_age_months", 0)))
    if parent is not None:
        tree.children[parent].append(node)


def _fan(paths: list[ScenarioPath], cfg: ModelConfig) -> ScenarioTree:
    """The ensemble reduced stage by stage, the representatives nested as a fan.

    Every node of one stage gives rise to the same set of representative outcomes at the
    next, each carrying its conditional mass. Consecutive nodes of a path therefore come
    from different Monte-Carlo paths, so the regime of a path of this tree is whatever its
    stage medoids happened to be drawn under, and it can change at every milestone: a
    village may grow quickly to year five, slowly to year ten and quickly again. The
    distortion report counts those paths. Kept because every stored result was drawn on it,
    with its features scaled as they were unless ``cfg.centre_features`` is set.
    """
    stage_years = list(cfg.stage_years)
    branching = list(cfg.branching)
    if len(branching) < len(stage_years):
        branching = branching + [1] * (len(stage_years) - len(branching))

    reductions = [_reduce.reduce_stage(paths, year, branching[k], seed=cfg.seed,
                                       centred=bool(cfg.centre_features))
                  for k, year in enumerate(stage_years)]

    # The rate is the configuration's, which the project sets; a literal fallback here was
    # a second source for a figure that must have one, and it would have answered for a
    # project that declared another rate.
    tree = ScenarioTree(discount_rate=float(cfg.discount_rate), tree_mode="fan")

    counter = 0
    root_path = paths[reductions[0].representatives[0]]
    _add(tree, cfg, counter, 0, None, 1.0, root_path)
    frontier = [0]
    counter += 1

    for stage in range(1, len(stage_years)):
        reduction = reductions[stage]
        next_frontier = []
        for parent in frontier:
            for index, weight in zip(reduction.representatives, reduction.weights):
                _add(tree, cfg, counter, stage, parent, tree.prob[parent] * float(weight),
                     paths[index])
                next_frontier.append(counter)
                counter += 1
        frontier = next_frontier

    tree.leaves = [n for n in tree.nodes if not tree.children[n]]
    tree.check_probabilities()
    tree.reduction_error = {stage_years[k]: r.error for k, r in enumerate(reductions)}
    tree.distortion = _reduce.distortion(
        tree, paths, stage_years, [0] * len(paths),
        {n: (None if tree.parent[n] is None else 0) for n in tree.nodes},
        _reduce.regime_table(paths, stage_years))
    return tree


def _persistent(paths: list[ScenarioPath], cfg: ModelConfig) -> ScenarioTree:
    """Branch over regimes at the first milestone after the root, and hold them below.

    The regimes of the ensemble are reduced to ``cfg.regime_branches`` medoid regimes when
    they outnumber them, each branch carrying the mass of its cluster. Below a branch only
    the paths whose regime *is* the representative's are used -- not its whole cluster,
    whose other regimes would bring the mean reversion back -- and their outcomes at each
    stage are reduced to ``cfg.regime_fan[k]`` medoids, nested as a fan within the regime:
    climate and the year-to-year variability branch freely, the regime does not. Every
    reduction here centres its features: within one cost future the prices are the same at
    every stage, and the fan's scaling would let those flat channels decide the medoids.

    Under ``root_period = "regimes"`` the root invests and does not operate. One node per
    branch operates the root's span instead, on that regime's own year-0 outcomes, with the
    branch's mass and the root's plant: the year-0 plant is then operated under every regime
    it may meet, which is what deciding it before the regime is known means. Under
    ``"root"`` the root operates its span on the medoid of the whole ensemble, as the fan's
    does, and the bias of a year-0 plant that never sees the spread of its own span is kept.

    Where the grid's arrival is uncertain, the outcomes below a node are reduced separately
    for the paths whose grid state is the node's: a connected node's children come from the
    paths connected by then, and an unconnected node receives one set of children from the
    paths where the line arrives at the next milestone and one from those where it does
    not, each weighted by its share. No connected node then has an unconnected child.
    """
    stage_years = list(cfg.stage_years)
    fan = list(cfg.regime_fan)
    own_period = cfg.root_period == "root"
    table = _reduce.regime_table(paths, stage_years)
    regimes = _reduce.reduce_regimes(table, cfg.regime_branches)
    branches = len(regimes.representatives)
    members = [table.members[r] for r in regimes.representatives]

    connected = [[bool(next(d for d in p.draws if d.stage_year == y).grid_connected)
                  for y in stage_years] for p in paths]
    uncertain_grid = any(len({row[k] for row in connected}) > 1
                         for k in range(len(stage_years)))
    if len({row[0] for row in connected}) > 1:
        raise ValueError("the grid is there at year 0 on some paths and not on others; the "
                         "root's span cannot be split on it")

    reductions: dict[tuple, tuple[list[int], list[float], float]] = {}

    def reduced(branch: int, stage: int, group: tuple[int, ...], count: int):
        """Medoids of ``group``'s stage outcomes, as global path indices and weights."""
        key = (branch, stage, group, count)
        if key not in reductions:
            subset = [paths[i] for i in group]
            r = _reduce.reduce_stage(subset, stage_years[stage], count, seed=cfg.seed,
                                     centred=True)
            reductions[key] = ([group[j] for j in r.representatives],
                               [float(w) for w in r.weights], r.error)
        return reductions[key]

    def children(branch: int, stage: int, parent_connected: bool):
        """The medoids below a node of ``branch`` at ``stage - 1``, with their weights."""
        group = tuple(members[branch])
        if not uncertain_grid:
            picked, weights, _ = reduced(branch, stage, group, fan[stage])
            return list(zip(picked, weights))
        before = [i for i in group if connected[i][stage - 1] == parent_connected]
        if parent_connected:
            picked, weights, _ = reduced(branch, stage, tuple(before), fan[stage])
            return list(zip(picked, weights))
        arrives = tuple(i for i in before if connected[i][stage])
        stays = tuple(i for i in before if not connected[i][stage])
        out = []
        share_arrives = len(arrives) / len(before)
        counts = {arrives: max(1, round(fan[stage] * share_arrives)),
                  stays: max(1, fan[stage] - round(fan[stage] * share_arrives))}
        for part in (arrives, stays):
            if not part:
                continue
            picked, weights, _ = reduced(branch, stage, part, counts[part])
            out.extend((i, w * len(part) / len(before)) for i, w in zip(picked, weights))
        return out

    tree = ScenarioTree(discount_rate=float(cfg.discount_rate), tree_mode="persistent")
    node_branch: dict[int, int | None] = {0: None}
    root = _reduce.reduce_stage(paths, stage_years[0], 1, seed=cfg.seed, centred=True)
    _add(tree, cfg, 0, 0, None, 1.0, paths[root.representatives[0]], operates=own_period)
    counter = 1

    errors: dict[int, float] = {}
    if own_period:
        frontier = [(0, b) for b in range(branches)]
        errors[stage_years[0]] = root.error
    else:
        frontier = []
        for b in range(branches):
            picked, _, _ = reduced(b, 0, tuple(members[b]), fan[0])
            _add(tree, cfg, counter, 0, 0, float(regimes.weights[b]), paths[picked[0]],
                 invests=False)
            node_branch[counter] = b
            frontier.append((counter, b))
            counter += 1

    for stage in range(1, len(stage_years)):
        next_frontier = []
        for parent, b in frontier:
            # Below the root the branch's mass enters; below a regime's own node it is
            # already in the parent's probability.
            mass = float(regimes.weights[b]) if parent == 0 else 1.0
            for index, weight in children(b, stage, bool(
                    tree.node_data[parent].grid_connected)):
                _add(tree, cfg, counter, stage, parent,
                     tree.prob[parent] * mass * float(weight), paths[index])
                node_branch[counter] = b
                next_frontier.append((counter, b))
                counter += 1
        frontier = next_frontier

    # Each stage's reduction error is that of its reductions within the regimes, weighted
    # by the mass of the branch they were made for; each is in its own reduction's scale,
    # as the fan's is. ``distortion`` gives the comparable figure.
    for k, year in enumerate(stage_years):
        if k == 0 and own_period:
            continue
        total = 0.0
        for b in range(branches):
            made = [e for (bb, kk, _, _), (_, _, e) in reductions.items()
                    if bb == b and kk == k]
            if made:
                total += float(regimes.weights[b]) * (sum(made) / len(made))
        errors[year] = total

    tree.leaves = [n for n in tree.nodes if not tree.children[n]]
    tree.check_probabilities()
    tree.reduction_error = {year: errors[year] for year in stage_years}
    tree.distortion = _reduce.distortion(
        tree, paths, stage_years,
        [int(regimes.assignment[table.of_path[i]]) for i in range(len(paths))],
        node_branch, table)
    tree.distortion["regime_reduction_error"] = regimes.error
    return tree
