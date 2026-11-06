"""Investment-layer constraints: capacity accumulation, and what a converter admits.

Capacity accumulates from the parent node, so a plan is a sequence of additions rather than
a sequence of unrelated sizings, and non-anticipativity is structural: a variable indexed by
node cannot see the branch it does not belong to.

The generator is a single active unit drawn from a catalogue, upgraded rather than
accumulated: two generating sets on one bus is a different plant, not a bigger one.
"""
from __future__ import annotations

import linopy
import numpy as np

from ..config import ModelConfig
from .coords import Coords


def add_investment_constraints(m: linopy.Model, v: dict, c: Coords,
                               cfg: ModelConfig, architecture: str = "dc",
                               root_box: "RootBox | None" = None,
                               settings=None) -> None:
    """Capacity recursions, the generator state, and the array-to-converter ceiling.

    ``root_box`` confines the year-0 plant to a box of module counts. It is what turns this
    programme from a single lower bound into the lower oracle of a branch-and-bound over
    the decision the developer actually takes: restricted to a box, its value minorises the
    rule-based cost of every plan whose root lies in that box, so a box whose value already
    exceeds a known plan can be discarded whole. Only the root is confined; every descendant
    stays free, because what the plan does later is not what is being certified.

    The two admission ratios come from ``settings``. They are fields the interface offers,
    and read from ``config`` instead they were the defaults whatever a developer entered --
    a ceiling the certified optimum sits exactly on, decided by a figure the project had no
    way of changing.
    """
    from ..settings import default_settings

    resolved = default_settings() if settings is None else settings
    coupling = resolved.coupling
    installed = getattr(resolved, "installed", None)
    divided = architecture == "mixed"
    ratio = (coupling.dc_ac_ratio_max if architecture in ("dc", "mixed")
             else coupling.ac_ratio_max)
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)

    m.add_constraints(v["z_ge"].sum("gsize") == 1, name="one_generator")

    # A plant does not sell its generating set back, so a rating below the one on site is
    # not a decision the plan may take -- at any node, not only at the root.
    standing_gen = installed_base(installed)[3]
    if standing_gen > 0.0:
        if not any(float(r) >= standing_gen - 1e-9 for r in ratings):
            raise ValueError(
                f"the standing generating set is {standing_gen:g} kW and the catalogue "
                "holds nothing that large; a plan cannot replace it with a smaller one")
        for k, rating in enumerate(ratings):
            if float(rating) < standing_gen - 1e-9:
                m.add_constraints(v["z_ge"].sel(gsize=k) == 0, name=f"no_gen_below_{k}")

    if root_box is not None:
        root = int(c.node[0])
        for module, (low, high) in root_box.modules.items():
            m.add_constraints(v[module].sel(node=root) >= int(low),
                              name=f"root_{module}_low")
            m.add_constraints(v[module].sel(node=root) <= int(high),
                              name=f"root_{module}_high")
        # A rating the box excludes is excluded at the root only; the plan may still
        # upgrade to it later, which is a different decision and not the one under test.
        allowed = set(root_box.generator_ratings)
        for k, rating in enumerate(ratings):
            if float(rating) not in allowed:
                m.add_constraints(v["z_ge"].sel(node=root, gsize=k) == 0,
                                  name=f"root_no_gen_{k}")

    for n in c.node:
        parent = c.parent[int(n)]
        # The whole plant, not only what the plan adds: a converter has to admit the array
        # already on its trackers as well as the one the plan buys.
        cap_pv, cap_batt, cap_inv, cap_gen, cap_pv_ac = capacity(
            v, c, int(n), cfg, installed)
        if divided:
            # Each part of the array is admitted by its own converter, so the field as a
            # whole may reach the sum of the two ceilings.
            m.add_constraints(cap_pv_ac - coupling.ac_ratio_max * cap_inv <= 0,
                              name=f"array_ratio_ac_{int(n)}")
        else:
            m.add_constraints(v["b_pv_ac"].sel(node=int(n)) == 0,
                              name=f"no_ac_field_{int(n)}")

        # An array is admitted by its converter and by nothing else. Under direct-current
        # coupling the conversion is bought with the hybrid inverter, so this ceiling is
        # the only thing standing between the plan and free photovoltaic capacity.
        m.add_constraints(cap_pv - ratio * cap_inv <= 0, name=f"array_ratio_{int(n)}")

        # The generating set is replaced on upgrade, never shrunk: a plant does not sell
        # its generator back.
        if parent is not None:
            parent_gen = sum(float(r) * v["z_ge"].sel(node=int(parent), gsize=k)
                             for k, r in enumerate(ratings))
            m.add_constraints(cap_gen - parent_gen >= 0, name=f"gen_monotone_{int(n)}")


def _accumulated(v: dict, c: Coords, node: int, module: str, unit: float):
    """Installed capacity at a node: the modules added along the path from the root."""
    chain, cursor = [], node
    while cursor is not None:
        chain.append(cursor)
        cursor = c.parent[cursor]
    return unit * sum(v[module].sel(node=int(k)) for k in chain)


def installed_base(installed=None) -> tuple:
    """What already stands, in the order the capacities are counted [kW, kWh, kW, kW, kW].

    All five, the generating set included. Where it enters differs by technology, and that
    asymmetry is real rather than an oversight: the plan *adds* modules of array, storage
    and conversion, so their totals are this base plus what it buys, while it does not add
    generating sets but chooses one rating from a catalogue, so that total is the choice
    itself and this base is a floor on the choice. Every caller states which it is doing.
    Returning zero for the set here instead, as this first did, leaves the second reader to
    rediscover the asymmetry, which is how one figure comes to be read two ways.
    """
    if installed is None:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    return (installed.capacity("pv"), installed.capacity("battery"),
            installed.capacity("inverter"), installed.capacity("generator"),
            installed.capacity("pv_ac"))


def capacity(v: dict, c: Coords, node: int, cfg: ModelConfig, installed=None):
    """The five capacities standing at a node, as linear expressions.

    What the plant *is*, which is what the dispatch may use and what the converter has to
    admit: the plant already on the ground plus whatever the plan has added by this node.
    Use :func:`added_capacity` for what the plan pays for.

    The array comes in two parts, one on each bus. Under a pure arrangement the part on the
    load's bus is pinned to zero and the tuple reads as it did before.
    """
    base = installed_base(installed)
    added = added_capacity(v, c, node, cfg, installed)
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)
    # The chosen rating is the whole set, so the standing one is not added to it: it was a
    # floor on the choice, which ``add_investment_constraints`` imposes.
    chosen = sum(float(r) * v["z_ge"].sel(node=node, gsize=k)
                 for k, r in enumerate(ratings))
    return (base[0] + added[0], base[1] + added[1], base[2] + added[2],
            chosen, base[4] + added[4])


def added_capacity(v: dict, c: Coords, node: int, cfg: ModelConfig, installed=None):
    """The five capacities the plan buys by a node, as linear expressions.

    What the project pays for. A village with a plant pays for the extension, not for the
    plant: the array, the storage and the conversion already standing were bought years
    ago, and the modular variables of this programme count additions, so for those three
    this is simply the accumulation along the path. The generating set is the exception
    again -- the plan picks a rating, so what it buys is the rating it picks less the one
    already on site, which the floor in :func:`add_investment_constraints` keeps positive.
    """
    base = installed_base(installed)
    ratings = np.asarray(cfg.gen_catalog_kw, dtype=float)
    # Written as a credit inside the coefficients rather than as ``chosen - standing``.
    # Exactly one binary is set, so the two are the same number, but the subtraction leaves
    # a constant term in the expression and linopy declines to carry one in an objective.
    # The floor on the choice keeps every coefficient non-negative.
    chosen_added = sum(max(float(r) - base[3], 0.0) * v["z_ge"].sel(node=node, gsize=k)
                       for k, r in enumerate(ratings))
    return (_accumulated(v, c, node, "b_pv", cfg.pv_unit_kw),
            _accumulated(v, c, node, "b_batt", cfg.batt_unit_kwh),
            _accumulated(v, c, node, "b_inv", cfg.inv_unit_kw),
            chosen_added,
            _accumulated(v, c, node, "b_pv_ac", cfg.pv_unit_kw))
