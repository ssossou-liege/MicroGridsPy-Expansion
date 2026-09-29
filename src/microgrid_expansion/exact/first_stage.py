"""Certify the decision the developer actually takes: what to build in year zero.

The reference year is certified by exhaustion: its design space is a lattice of some six
hundred thousand points, a bound removes two thirds of them for nothing, and the rest are
simulated. A *plan* over the tree admits no such treatment — it is a capacity vector at each
of forty-six nodes, and the product of forty-six lattices is not a set anyone enumerates.
That is why the plan has been reported from a coordinated descent, which is an honest upper
bound and no more.

But the plan is not what is being decided. Only the root is bought; everything to the right
of it is a future the plan is merely ready for, and a developer who commits to the root has
committed to the whole of what this tool is for. The object to certify is therefore a single
design, not a plan, and that is a problem the same size as the reference year's.

The scheme is Corollary 1 of the formulation with the box taken in root coordinates alone:

    lower oracle   the deterministic-equivalent programme with the root confined to a box
                   and every descendant left free. By Proposition 1 its value minorises the
                   rule-based cost of *every* plan whose root lies in that box, so a box
                   whose value already exceeds a plan in hand can be discarded whole.
    upper oracle   the coordinated descent with the root pinned, which returns a buildable
                   plan and therefore a true cost.

Between them sits a bound that costs nothing, and on the tree it is far stronger than it is
on a single year. Capacity accumulates down the tree, so a module bought at the root is paid
for at every node after it: the root's annualised capital is multiplied by the whole horizon
weight, some thirteen node-years, while operating cost is incurred once per node. On the
reference instance the chosen root's capital alone accounts for six-sevenths of the plan's
entire cost, which leaves very little room for anything dearer.

What this module does not do is decide the plan. The branches remain the descent's, and
remain an upper bound; it is the year-0 design, and only that, which comes out proven.
"""
from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field, replace

from ..config import ModelConfig
from ..settings import ProjectSettings, default_settings
from ..timedomain.rep_days import RepDays
from ..tree.tree_model import ScenarioTree
from .certify import Lattice


@dataclass(frozen=True)
class RootBox:
    """A box of year-0 plants, in module counts rather than kilowatts.

    Counts, because the programme's variables are counts and a box has to be expressible as
    bounds on them. The generator is a choice from a catalogue rather than a quantity, so it
    is carried as the set of ratings the box still allows.
    """

    n_pv: tuple[int, int]
    n_batt: tuple[int, int]
    n_inv: tuple[int, int]
    n_pv_ac: tuple[int, int]
    generator_ratings: tuple[float, ...]

    @property
    def modules(self) -> dict[str, tuple[int, int]]:
        """The bounds as the programme wants them, keyed by variable name."""
        return {"b_pv": self.n_pv, "b_batt": self.n_batt,
                "b_inv": self.n_inv, "b_pv_ac": self.n_pv_ac}

    @property
    def n_points(self) -> int:
        """Plants inside the box, buildable or not.

        This is the box's extent, which is what the splitting works on. It counts corners
        an inverter would refuse, so it runs above the admissible count the lattice
        reports; the two are printed side by side rather than conflated.
        """
        return ((self.n_pv[1] - self.n_pv[0] + 1)
                * (self.n_batt[1] - self.n_batt[0] + 1)
                * (self.n_inv[1] - self.n_inv[0] + 1)
                * (self.n_pv_ac[1] - self.n_pv_ac[0] + 1)
                * max(len(self.generator_ratings), 1))

    @property
    def is_singleton(self) -> bool:
        return self.n_points == 1

    @classmethod
    def around(cls, lattice: Lattice) -> "RootBox":
        """The whole admissible set, as one box."""
        return cls(n_pv=lattice.n_pv, n_batt=lattice.n_batt, n_inv=lattice.n_inv,
                   n_pv_ac=lattice.n_pv_ac,
                   generator_ratings=tuple(lattice.generator_ratings))

    def corner(self, low: bool = True) -> dict[str, float]:
        """The cheapest or dearest point of the box, as module counts and a rating."""
        pick = min if low else max
        return {"b_pv": self.n_pv[0] if low else self.n_pv[1],
                "b_batt": self.n_batt[0] if low else self.n_batt[1],
                "b_inv": self.n_inv[0] if low else self.n_inv[1],
                "b_pv_ac": self.n_pv_ac[0] if low else self.n_pv_ac[1],
                "generator_kw": pick(self.generator_ratings)}

    def split(self) -> tuple["RootBox", "RootBox"]:
        """Halve the box along whichever coordinate is widest.

        Widest in points rather than in kilowatts: the coordinates are counted in different
        units -- modules of array, of storage, of conversion -- and splitting by physical
        extent would keep returning to whichever unit happens to be smallest.
        """
        widths = {"n_pv": self.n_pv[1] - self.n_pv[0],
                  "n_batt": self.n_batt[1] - self.n_batt[0],
                  "n_inv": self.n_inv[1] - self.n_inv[0],
                  "n_pv_ac": self.n_pv_ac[1] - self.n_pv_ac[0]}
        widest = max(widths, key=lambda k: widths[k])
        if widths[widest] <= 0:
            # Every quantity is settled; only the catalogue is left to split.
            half = max(1, len(self.generator_ratings) // 2)
            return (replace(self, generator_ratings=self.generator_ratings[:half]),
                    replace(self, generator_ratings=self.generator_ratings[half:]))
        low, high = getattr(self, widest)
        middle = (low + high) // 2
        return (replace(self, **{widest: (low, middle)}),
                replace(self, **{widest: (middle + 1, high)}))

    def describe(self, lattice: Lattice) -> str:
        pv, ac = lattice.pv_unit_kw, lattice.pv_unit_kw
        return (f"pv {self.n_pv[0] * pv:.1f}-{self.n_pv[1] * pv:.1f}"
                f"+{self.n_pv_ac[0] * ac:.1f}-{self.n_pv_ac[1] * ac:.1f} kW  "
                f"batt {self.n_batt[0] * lattice.batt_unit_kwh:.0f}-"
                f"{self.n_batt[1] * lattice.batt_unit_kwh:.0f} kWh  "
                f"inv {self.n_inv[0] * lattice.inv_unit_kw:.1f}-"
                f"{self.n_inv[1] * lattice.inv_unit_kw:.1f} kW  "
                f"gen {min(self.generator_ratings):.0f}-"
                f"{max(self.generator_ratings):.0f} kW")


@dataclass
class TreeWeights:
    """What a node's costs are worth in the objective, and what the whole tree weighs."""

    per_node: dict[int, float]
    total: float
    root: float

    @classmethod
    def of(cls, tree: ScenarioTree) -> "TreeWeights":
        w = {n: tree.prob[n] * tree.disc[n] * tree.n_years[n] for n in tree.nodes}
        root = min(tree.nodes)
        return cls(per_node=w, total=sum(w.values()), root=w[root])


@dataclass
class FreeBound:
    """A lower bound on any plan rooted in a box, costing no solver call at all.

    Two terms, each valid on its own and both from the same two facts: capacity accumulates
    down the tree, and operating cost is non-negative.

    The capital term. Every descendant holds at least what the root holds, and annualised
    capital is increasing in every capacity, so the plan's capital is at least the box's
    cheapest corner charged at every node. That is the whole horizon weight, not one year,
    which is why this bites so much harder here than on a single year.

    The energy term. At the root the capacity *is* the root's, and the array cannot deliver
    more than its yield. Storage moves energy and loses a little doing so, so it cannot
    raise that ceiling. Whatever the array cannot cover must come from the generating set,
    at no less than the catalogue's most efficient marginal litre, or go unserved at the
    value of lost load -- and the set cannot produce more than its rating for every hour of
    the year. Applied at the root alone: the descendants may add capacity, so nothing can be
    asserted about what they will have to burn.
    """

    weights: TreeWeights
    unit_costs: tuple[float, float, float, float, float]   # pv, batt, inv, gen, pv_ac
    lattice: Lattice
    demand_kwh: float
    yield_kwh_per_kw: float
    round_trip: float
    fuel_usd_kwh: float
    voll_usd_kwh: float
    hours: float = 8760.0

    def capital(self, n_pv: int, n_batt: int, n_inv: int, n_pv_ac: int,
                generator_kw: float) -> float:
        a_pv, a_batt, a_inv, a_gen, a_pv_ac = self.unit_costs
        return (a_pv * n_pv * self.lattice.pv_unit_kw
                + a_pv_ac * n_pv_ac * self.lattice.pv_unit_kw
                + a_batt * n_batt * self.lattice.batt_unit_kwh
                + a_inv * n_inv * self.lattice.inv_unit_kw
                + a_gen * generator_kw)

    def root_operating(self, n_pv: int, n_pv_ac: int, generator_kw: float) -> float:
        """Least the root node can spend running, given the array and the set it holds."""
        array_kwh = (self.round_trip * (n_pv + n_pv_ac)
                     * self.lattice.pv_unit_kw * self.yield_kwh_per_kw)
        residual = max(0.0, self.demand_kwh - array_kwh)
        from_set = min(residual, generator_kw * self.hours)
        return self.fuel_usd_kwh * from_set + self.voll_usd_kwh * (residual - from_set)

    def of(self, box: RootBox) -> float:
        """The bound for a box: its cheapest capital, its least possible running cost."""
        low = box.corner(low=True)
        capital = self.capital(low["b_pv"], low["b_batt"], low["b_inv"], low["b_pv_ac"],
                               min(box.generator_ratings))
        # The array at its smallest and the set at its largest both lower the running cost,
        # and taking each at the corner that minimises it keeps the bound a bound even
        # though no single design sits at both.
        operating = self.root_operating(box.n_pv[0], box.n_pv_ac[0],
                                        max(box.generator_ratings))
        return self.weights.total * capital + self.weights.root * operating


@dataclass(order=True)
class _Open:
    """An open box, ordered by its bound so the queue is explored best-first."""

    bound: float
    serial: int
    box: RootBox = field(compare=False)


@dataclass
class FirstStageCertificate:
    """What the year-0 plant is, and on what grounds."""

    root: dict[str, float]
    z_rule: float
    lower_bound: float
    proven: bool
    boxes_opened: int
    boxes_pruned_free: int
    boxes_pruned_programme: int
    programmes_solved: int
    descents: int
    #: Single plants whose bound stayed under the incumbent and which the descent could
    #: therefore not exclude. A proof requires none.
    unresolved: int
    lattice_size: int
    seconds: float

    @property
    def gap_abs(self) -> float:
        return self.z_rule - self.lower_bound

    @property
    def gap_rel(self) -> float:
        return 100.0 * self.gap_abs / max(self.z_rule, 1.0)

    def summary(self) -> str:
        state = ("proven optimal" if self.proven
                 else f"gap {self.gap_rel:.2f} %, {self.unresolved} plants unresolved")
        return (f"year-0 plant {self.root} -- {state}; "
                f"{self.boxes_opened} boxes, {self.boxes_pruned_free} pruned free, "
                f"{self.programmes_solved} programmes, {self.descents} descents, "
                f"{self.seconds:.0f} s")


def free_bound_for(tree: ScenarioTree, rep: dict[int, RepDays], lattice: Lattice,
                   settings: ProjectSettings, architecture: str) -> FreeBound:
    """Assemble the costless bound from the root node's own year."""
    from ..model.economics import annualised_unit_costs
    from .lower_bound import fuel_minorant
    from .simulator import GeneratorModel

    root = min(tree.nodes)
    days = rep[root]
    day_weight = days.weight[:, None]
    demand_kwh = float((days.demand * day_weight).sum())
    yield_kwh = float((days.specific_yield * day_weight).sum())

    # The catalogue's most efficient marginal litre, not the unit the plan happens to buy:
    # a bound must minorise whichever it picks.
    price = settings.economics.diesel_price_usd_l
    slopes = []
    for spec in settings.generators:
        _, slope = fuel_minorant(GeneratorModel.from_spec(spec, price), spec.rating_kw)
        slopes.append(slope)

    return FreeBound(
        weights=TreeWeights.of(tree),
        unit_costs=annualised_unit_costs(tree.node_data[root].costs, architecture,
                                         settings),
        lattice=lattice,
        demand_kwh=demand_kwh,
        yield_kwh_per_kw=yield_kwh,
        round_trip=(settings.battery.charge_efficiency
                    * settings.battery.discharge_efficiency),
        fuel_usd_kwh=price * min(slopes),
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh,
        hours=float(days.weight.sum()) * 24.0,
    )


def _root_of(plans: dict, tree: ScenarioTree) -> dict[str, float]:
    plan = plans[min(tree.nodes)]
    return {"pv_kw": float(plan.pv_kw), "pv_ac_kw": float(getattr(plan, "pv_ac_kw", 0.0)),
            "battery_kwh": float(plan.battery_kwh),
            "inverter_kw": float(plan.inverter_kw),
            "generator_kw": float(plan.generator_kw)}


def _box_of(root: dict[str, float], lattice: Lattice) -> RootBox:
    """The singleton box holding exactly this plant."""
    unit = lambda value, size: int(round(value / size))          # noqa: E731
    return RootBox(
        n_pv=(unit(root["pv_kw"], lattice.pv_unit_kw),) * 2,
        n_batt=(unit(root["battery_kwh"], lattice.batt_unit_kwh),) * 2,
        n_inv=(unit(root["inverter_kw"], lattice.inv_unit_kw),) * 2,
        n_pv_ac=(unit(root["pv_ac_kw"], lattice.pv_unit_kw),) * 2,
        generator_ratings=(float(root["generator_kw"]),))


def certify_first_stage(
    tree: ScenarioTree,
    rep: dict[int, RepDays],
    cfg: ModelConfig,
    incumbent_plans: dict,
    z_rule: float,
    architecture: str = "dc",
    settings: ProjectSettings | None = None,
    max_programmes: int = 40,
    max_seconds: float = 6 * 3600.0,
    epsilon: float = 1e-6,
    verbose: bool = True,
) -> FirstStageCertificate:
    """Prove the year-0 plant optimal, or return the gap that remains.

    Best-first over boxes of year-0 plants. A box is discarded when a bound on every plan
    rooted in it already exceeds a plan in hand; when it narrows to a single plant, that
    plant is costed exactly by descending over the tree with the root pinned. Popping the
    box of least bound means that once the head of the queue is no better than the incumbent
    nothing left can be, and the search stops with a proof rather than an exhausted budget.

    The costless bound is tried first on every box, because a programme over forty-six nodes
    is the expensive object here and the whole point of the capital floor is to avoid
    solving one. ``max_programmes`` and ``max_seconds`` bound the effort; exhausting either
    returns ``proven=False`` with the gap that was reached, which is a weaker claim honestly
    stated and not a failure.
    """
    from ..model import build_model
    from ..post import extract_solution
    from ..run import _NodeInstance
    from ..solve import solve
    from .tree_certify import certify_tree

    settings = default_settings() if settings is None else settings
    root_node = min(tree.nodes)
    lattice = Lattice.around(_NodeInstance(tree.node_data[root_node], settings), settings,
                             architecture=architecture)
    free = free_bound_for(tree, rep, lattice, settings, architecture)

    best_root = _root_of(incumbent_plans, tree)
    best_value, best_plans = z_rule, incumbent_plans
    started = time.time()
    whole = RootBox.around(lattice)
    queue: list[_Open] = [_Open(free.of(whole), 0, whole)]
    serial = 1
    opened = pruned_free = pruned_programme = programmes = descents = 0
    unresolved: list[tuple[float, dict[str, float]]] = []
    frontier = float("inf")

    if verbose:
        print(f"  first stage: lattice {lattice.size:,} plants, "
              f"incumbent {best_value:,.0f} $, costless bound {free.of(whole):,.0f} $",
              flush=True)

    while queue:
        if programmes >= max_programmes or time.time() - started > max_seconds:
            frontier = min(item.bound for item in queue)
            break
        item = heapq.heappop(queue)
        # Best-first: the head carries the least bound in the queue, so once it is no
        # better than the incumbent, nothing left is either.
        if item.bound >= best_value - epsilon:
            pruned_free += 1 + len(queue)
            queue.clear()
            frontier = item.bound
            break
        opened += 1
        box = item.box

        if box.is_singleton:
            low = box.corner(low=True)
            root = {"pv_kw": low["b_pv"] * lattice.pv_unit_kw,
                    "pv_ac_kw": low["b_pv_ac"] * lattice.pv_unit_kw,
                    "battery_kwh": low["b_batt"] * lattice.batt_unit_kwh,
                    "inverter_kw": low["b_inv"] * lattice.inv_unit_kw,
                    "generator_kw": low["generator_kw"]}
            programme = build_model(tree, rep, cfg, architecture=architecture,
                                    settings=settings, root_box=box)
            solved = solve(programme, settings, solver=cfg.solver)
            programmes += 1
            # The guaranteed bound, not the incumbent the solver happened to reach: a
            # mixed-integer solve stops at a tolerance, and pruning on the value it stopped
            # at can discard the box the optimum was in.
            if solved.bound == float("inf") or solved.bound >= best_value - epsilon:
                pruned_programme += 1
                continue
            plans = extract_solution(programme, cfg)
            certificate = certify_tree(plans, tree, rep, solved.bound,
                                       architecture=architecture, settings=settings,
                                       fixed_nodes=frozenset({root_node}), verbose=False)
            descents += 1
            if certificate.z_rule < best_value:
                best_value, best_root, best_plans = (certificate.z_rule, root,
                                                     certificate.plans)
                if verbose:
                    print(f"    incumbent {best_value:,.0f} $ at {root}", flush=True)
            # A plant that cannot be split further and cannot be discarded is not settled.
            # The descent bounds the best plan rooted here from above, never from below, so
            # a plant whose programme bound sits under the incumbent might still beat it and
            # cannot be dropped: it is carried, and it is what stops this search claiming a
            # proof it has not got. Closing these is closing the descent's own gap.
            if solved.bound < best_value - epsilon:
                unresolved.append((solved.bound, root))
            continue

        # A box worth opening is worth bounding properly: solve the programme over it, and
        # split only what survives.
        programme = build_model(tree, rep, cfg, architecture=architecture,
                                settings=settings, root_box=box)
        solved = solve(programme, settings, solver=cfg.solver)
        programmes += 1
        bound = solved.bound
        if bound == float("inf") or bound >= best_value - epsilon:
            pruned_programme += 1
            continue
        if verbose:
            print(f"    box {box.describe(lattice)}  bound {bound:,.0f} $ "
                  f"({box.n_points:,} plants)", flush=True)
        for child in box.split():
            heapq.heappush(queue, _Open(max(bound, free.of(child)), serial, child))
            serial += 1

    # What is still open: boxes never settled, and single plants the descent could not
    # rule out. The bound reported is the least of them, and only an empty frontier is a
    # proof -- a search that stopped on its budget says so rather than rounding up to one.
    open_bounds = [item.bound for item in queue] + [b for b, _ in unresolved]
    frontier = min(open_bounds) if open_bounds else best_value
    proven = not open_bounds
    if verbose and unresolved:
        print(f"  {len(unresolved)} plants could not be ruled out; the descent bounds each "
              f"only from above", flush=True)
    return FirstStageCertificate(
        root=best_root, z_rule=best_value, lower_bound=min(frontier, best_value),
        proven=proven, boxes_opened=opened, boxes_pruned_free=pruned_free,
        boxes_pruned_programme=pruned_programme, programmes_solved=programmes,
        descents=descents, unresolved=len(unresolved),
        lattice_size=lattice.size, seconds=time.time() - started)
