"""Per-stage scenario reduction.

Condenses the Monte-Carlo ensemble at each stage to a small set of representative
outcomes, each carrying the probability mass of its cluster. A medoid-based method
(k-medoids on a feature representation of the paths, or fast-forward selection) is
used so that representatives are actual sampled outcomes.

The reduction error relative to the full ensemble is returned so that the compression
stays transparent (no silent truncation). A persistent tree is reduced twice, once across
regimes and once within each, and :func:`distortion` measures what both trees lose on the
same scale, so that the two can be compared rather than each reporting on its own terms.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..scenarios.assemble import ScenarioPath


@dataclass
class StageReduction:
    """Result of reducing one stage's outcomes."""

    representatives: list[int]          # indices of representative paths
    assignment: np.ndarray              # path -> representative index
    weights: np.ndarray                 # probability mass per representative
    error: float                        # distortion vs full ensemble


def _feature_row(demand: np.ndarray, yield_: np.ndarray, costs: dict,
                 grid_connected: bool) -> list[float]:
    """What a sizing is sensitive to in one operating year, before any scaling."""
    daytime = demand.reshape(-1, 24)[:, 7:19].sum() / max(demand.sum(), 1e-9)
    return [
        demand.sum(),                       # energy to serve
        demand.max(),                       # peak
        daytime,                            # when it falls
        yield_.sum(),                       # resource
        float(np.corrcoef(demand, yield_)[0, 1]),   # how the two line up
        costs["fuel_price"],
        costs["capex_pv"],
        costs["capex_batt"],
        # Connected and unconnected futures must not be averaged into one representative:
        # they call for different plants, which is the whole reason for branching on the
        # arrival. Weighted well above the other channels so the medoids separate on it.
        10.0 * float(grid_connected),
    ]


def raw_stage_features(paths: list[ScenarioPath], stage_year: int) -> np.ndarray:
    """The unscaled feature row of each path's outcome at one stage."""
    rows = []
    for path in paths:
        draw = next(d for d in path.draws if d.stage_year == stage_year)
        rows.append(_feature_row(path.demand[stage_year], path.pv_unit[stage_year],
                                 draw.costs, getattr(draw, "grid_connected", False)))
    return np.array(rows, dtype=float)


def node_features(data) -> np.ndarray:
    """The unscaled feature row of a node, read from the arrays it carries."""
    return np.array(_feature_row(data.demand, data.pv_unit, data.costs,
                                 getattr(data, "grid_connected", False)), dtype=float)


@dataclass
class Scale:
    """How a set of feature rows was scaled, so that other rows can be put on its scale."""

    centre: np.ndarray
    spread: np.ndarray
    #: Channels that do not vary over the rows, and are set to zero rather than divided by a
    #: spread that is nothing but rounding.
    flat: np.ndarray

    def apply(self, rows: np.ndarray) -> np.ndarray:
        scaled = (np.asarray(rows, dtype=float) - self.centre) / self.spread
        scaled[..., self.flat] = 0.0
        return scaled


def _scaled(features: np.ndarray, centred: bool = True) -> tuple[np.ndarray, Scale]:
    """Each channel over its spread, and the channels that do not vary set to zero.

    A channel that does not vary has a spread of zero in exact arithmetic and of a few units
    of rounding in floating point: the prices of one cost future, or the year-0 prices every
    future starts from, give 1e-14. Divided by that, as the first version of this did, the
    channel became a constant of order 1e15, and the distance matrix of the k-medoids, which
    is computed in its expanded form, lost every other channel to cancellation: all the
    distances came out zero and the "medoid" was the first outcome of the list. A channel is
    therefore flat when its spread is below a billionth of its magnitude, and the features
    are centred, so that nothing large is left for the expanded form to cancel.

    ``centred=False`` is that first version, kept because the fan reads it (see
    ``ModelConfig.centre_features``).
    """
    if not centred:
        spread = features.std(axis=0)
        spread[spread <= 0] = 1.0
        return features / spread, Scale(np.zeros(features.shape[1]), spread,
                                        np.zeros(features.shape[1], dtype=bool))
    centre = features.mean(axis=0)
    spread = features.std(axis=0)
    flat = spread <= 1e-9 * np.maximum(np.abs(centre), 1.0)
    spread[flat] = 1.0
    scale = Scale(centre, spread, flat)
    return scale.apply(features), scale


def stage_features(paths: list[ScenarioPath], stage_year: int,
                   centred: bool = False) -> np.ndarray:
    """Feature vector of each path's outcome at one stage.

    A scenario is summarised by what a sizing is actually sensitive to: how much energy it
    must serve, how peaked that demand is, how much resource is available and how the two
    line up in the day, and what the fuel and capital prices are. Each channel is scaled by
    its own spread across the ensemble, so that a dollar and a kilowatt-hour do not compete
    on the accident of their units. ``centred`` chooses the scaling (``_scaled``).
    """
    features, _ = _scaled(raw_stage_features(paths, stage_year), centred=centred)
    return features


def reduce_stage(paths: list[ScenarioPath], stage_year: int, n_repr: int,
                 seed: int = 0, centred: bool = False) -> StageReduction:
    """Reduce the ensemble of stage-``stage_year`` outcomes to ``n_repr`` medoids.

    Medoids rather than centroids, for the reason the time-domain reduction uses them: a
    representative must be an outcome that could occur, and the average of a dry scenario
    and a wet one is neither. The distortion reported is the mean distance of an outcome to
    the representative standing for it, in the scaled feature space, so that a compression
    that has lost something says so.
    """
    from ..timedomain.kmedoids import kmedoids

    features = stage_features(paths, stage_year, centred=centred)
    n_repr = max(1, min(int(n_repr), features.shape[0]))
    clustering = kmedoids(features, n_repr)

    weights = clustering.weights.astype(float)
    weights = weights / weights.sum()
    distances = np.linalg.norm(features - features[clustering.medoids][clustering.labels],
                               axis=1)
    return StageReduction(representatives=[int(m) for m in clustering.medoids],
                          assignment=clustering.labels.astype(int),
                          weights=weights,
                          error=float(distances.mean()))


# ------------------------------------------------------------------- regimes
def regime_of(path: ScenarioPath) -> tuple[str, str, str]:
    """A path's regime: its connection trajectory, growth trajectory and cost future.

    Drawn once and held, so every stage of the path must carry the same three; a path that
    does not was not drawn by the sampler, and is refused rather than read at one stage.
    """
    def of(draw) -> tuple[str, str, str]:
        return (str(getattr(draw, "connection", "census")), str(draw.trajectory),
                str(draw.cost_scenario))

    regime = of(path.draws[0])
    if any(of(draw) != regime for draw in path.draws[1:]):
        raise ValueError(f"path {path.path_id} changes regime between its stages")
    return regime


def node_regime(data) -> tuple[str, str, str]:
    """The regime a node's data were drawn under."""
    return (str(data.connection), str(data.trajectory), str(data.cost_scenario))


@dataclass
class RegimeTable:
    """The regimes of an ensemble, which paths follow each, and what each looks like."""

    regimes: list[tuple[str, str, str]]
    members: list[list[int]]            # path indices of each regime, in ensemble order
    of_path: list[int]                  # regime index of each path
    mass: np.ndarray                    # share of the paths in each regime
    #: The concatenation, over the stages after the root, of the mean over a regime's paths
    #: of the unscaled stage features, each channel then scaled by its spread across
    #: regimes. A single stage is described by itself.
    features: np.ndarray


def regime_table(paths: list[ScenarioPath], stage_years) -> RegimeTable:
    labels = [regime_of(path) for path in paths]
    regimes = sorted(set(labels))
    index = {regime: k for k, regime in enumerate(regimes)}
    of_path = [index[label] for label in labels]
    members = [[i for i, k in enumerate(of_path) if k == r] for r in range(len(regimes))]
    mass = np.array([len(m) for m in members], dtype=float) / len(paths)
    later = list(stage_years)[1:] or list(stage_years)[:1]
    blocks = []
    for year in later:
        raw = raw_stage_features(paths, year)
        blocks.append(np.array([raw[m].mean(axis=0) for m in members]))
    features, _ = _scaled(np.hstack(blocks), centred=True)
    return RegimeTable(regimes=regimes, members=members, of_path=of_path, mass=mass,
                       features=features)


@dataclass
class RegimeReduction:
    """Which regimes are branches of the tree, and which branch stands for each regime."""

    representatives: list[int]          # regime index of each branch
    assignment: np.ndarray              # regime -> branch
    weights: np.ndarray                 # mass of each branch: the paths of its cluster
    error: float                        # mass-weighted distance to the representative


def reduce_regimes(table: RegimeTable, n_branches: int) -> RegimeReduction:
    """Reduce the regimes to ``n_branches`` medoid regimes, if they outnumber them.

    Weighted by mass, so that a regime few paths follow does not pull a representative its
    way as hard as one most of them follow. A representative is a regime that occurs, and
    its branch carries the mass of its whole cluster; the paths below it are its own.
    """
    from ..timedomain.kmedoids import kmedoids

    count = len(table.regimes)
    if count <= int(n_branches):
        return RegimeReduction(representatives=list(range(count)),
                               assignment=np.arange(count), weights=table.mass.copy(),
                               error=0.0)
    clustering = kmedoids(table.features, int(n_branches), weights=table.mass)
    distances = np.linalg.norm(
        table.features - table.features[clustering.medoids][clustering.labels], axis=1)
    return RegimeReduction(representatives=[int(m) for m in clustering.medoids],
                           assignment=clustering.labels.astype(int),
                           weights=clustering.weights.astype(float),
                           error=float((table.mass * distances).sum()))


# ---------------------------------------------------------------- distortion
def distortion(tree, paths: list[ScenarioPath], stage_years,
               path_branch: list[int], node_branch: dict[int, int | None],
               table: RegimeTable) -> dict:
    """The five measures of what a tree lost, on one scale for both ways of nesting it.

    Every distance is taken in the stage features of the whole ensemble, centred and each
    channel scaled by its spread across it (``_scaled``), so that a fan and a persistent tree
    drawn on the same ensemble are measured with the same ruler, whichever scaling built
    them. A node stands for the outcomes of its stage in its own
    branch: ``path_branch`` names the branch a path's regime belongs to and ``node_branch``
    the branch of a node, ``None`` for a root that stands for every path. A fan has a single
    branch.

    ``stage``
        per milestone, the mean distance of an outcome to the nearest operating node of its
        branch at that milestone; today's measure, conditioned on the regime.
    ``regime``
        the mass-weighted distance from each regime of the ensemble to the nearest regime
        the tree holds along a whole path from the first milestone after the root; zero
        when every regime is a branch, and ``None`` when no path of the tree keeps one.
    ``coverage``
        the mean, over the Monte-Carlo paths, of the distance from a path's whole trajectory
        to the nearest path of the tree.
    ``plausibility``
        the sum over leaves of the leaf's probability times the distance from its path to
        the nearest Monte-Carlo path.
    ``persistence_violations``
        the paths of the tree along which the connected stock falls, the regime changes
        after the root, or the grid leaves again; ``violations_by_kind`` splits them.
    """
    years = list(stage_years)
    scaled, scale = {}, {}
    for year in years:
        scaled[year], scale[year] = _scaled(raw_stage_features(paths, year), centred=True)
    feature = {n: scale[years[tree.stage[n]]].apply(node_features(tree.node_data[n]))
               for n in tree.nodes}
    path_branch = np.asarray(path_branch)

    # The node of each stage a leaf's path is operated by: the root, or in a persistent tree
    # the operating-only node of its regime.
    chains = {leaf: [n for n in tree.ancestors(leaf) if tree.operates(n)]
              for leaf in tree.leaves}
    for leaf, chain in chains.items():
        if [tree.stage[n] for n in chain] != list(range(len(years))):
            raise ValueError(f"the path to leaf {leaf} is not operated once a milestone")

    stage: dict[int, float] = {}
    for k, year in enumerate(years):
        candidates: dict[int | None, list[int]] = {}
        for n in tree.nodes:
            if tree.stage[n] == k and tree.operates(n):
                candidates.setdefault(node_branch[n], []).append(n)
        nearest = np.empty(len(paths))
        for branch in set(path_branch.tolist()):
            rows = np.flatnonzero(path_branch == branch)
            pool = candidates.get(branch, []) + candidates.get(None, [])
            if not pool:
                raise ValueError(f"no node of stage {k} stands for branch {branch}")
            centres = np.array([feature[n] for n in pool])
            gaps = np.linalg.norm(scaled[year][rows][:, None, :] - centres[None, :, :],
                                  axis=2)
            nearest[rows] = gaps.min(axis=1)
        stage[year] = float(nearest.mean())

    held = set()
    for leaf in tree.leaves:
        labels = {node_regime(tree.node_data[n]) for n in tree.ancestors(leaf)
                  if tree.parent[n] is not None}
        if len(labels) == 1:
            held.add(labels.pop())
    index = {regime: k for k, regime in enumerate(table.regimes)}
    held_rows = [index[r] for r in sorted(held) if r in index]
    if held_rows:
        gaps = np.linalg.norm(table.features[:, None, :]
                              - table.features[held_rows][None, :, :], axis=2)
        regime = float((table.mass * gaps.min(axis=1)).sum())
    else:
        regime = None

    trajectories = np.hstack([scaled[year] for year in years])
    leaves = list(tree.leaves)
    tree_paths = np.array([np.concatenate([feature[n] for n in chains[leaf]])
                           for leaf in leaves])
    gaps = np.linalg.norm(trajectories[:, None, :] - tree_paths[None, :, :], axis=2)
    coverage = float(gaps.min(axis=1).mean())
    plausibility = float(sum(float(tree.prob[leaf]) * gaps[:, j].min()
                             for j, leaf in enumerate(leaves)))

    kinds = {"connected_stock": 0, "regime": 0, "grid": 0}
    violating = 0
    for leaf in leaves:
        chain = tree.ancestors(leaf)
        stock = [tree.node_data[n].connected_households for n in chains[leaf]]
        grid = [bool(tree.node_data[n].grid_connected) for n in chain]
        found = {
            "connected_stock": any(b < a for a, b in zip(stock, stock[1:])),
            "regime": len({node_regime(tree.node_data[n]) for n in chain
                           if tree.parent[n] is not None}) > 1,
            "grid": any(a and not b for a, b in zip(grid, grid[1:])),
        }
        for kind, present in found.items():
            kinds[kind] += int(present)
        violating += int(any(found.values()))

    return {
        "stage": stage,
        "regime": regime,
        "coverage": coverage,
        "plausibility": plausibility,
        "persistence_violations": violating,
        "violations_by_kind": kinds,
        "tree_paths": len(leaves),
        "regimes": len(table.regimes),
        "regimes_held": len(held_rows),
    }
