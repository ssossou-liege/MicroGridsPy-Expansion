"""What the fixed cost of an extension campaign would have to be to change the plan.

The study this holds does not add a fixed cost to the model. It prices the one extreme that
can be priced exactly -- a park built once and never extended -- and reads the threshold off
the difference. Three things in that chain are easy to get wrong without any symptom.

The count of extensions is not the count of nodes that extend. A node at year twenty is met
by few paths and discounted hard; charging a campaign at every such node as if it were
certain would make the threshold look small and the conclusion look fragile.

The equipment cost of an extension is read at the node's own prices, the cost trajectory
having already moved them, and the array on the load's bus buys the string inverters that
put it there. Reading it at base-year prices understates a late extension.

And the park built once has to be exactly that. The programme's variables are modules
*added* at a node, so the policy is every addition after the root held at zero and the
generator held at the root's rating -- for every module and every node, with none missed.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from microgrid_expansion.exact.build_once import (FIXED_COSTS_USD, _equipment_usd, _grown,
                                                  after_the_fact, extensions,
                                                  hold_the_park)


@dataclass
class _Plan:
    pv_kw: float = 0.0
    pv_ac_kw: float = 0.0
    battery_kwh: float = 0.0
    inverter_kw: float = 0.0
    generator_kw: float = 0.0


@dataclass
class _Data:
    costs: dict


class _Tree:
    """Three nodes: a root, a likely near branch and an unlikely far one."""

    def __init__(self, prices: dict) -> None:
        self.nodes = [0, 1, 2]
        self.parent = {0: None, 1: 0, 2: 1}
        self.stage = {0: 0, 1: 1, 2: 2}
        self.prob = {0: 1.0, 1: 1.0, 2: 0.25}
        self.disc = {0: 1.0, 1: 0.68, 2: 0.46}
        self.node_data = {n: _Data(costs=dict(prices)) for n in self.nodes}
        self.leaves = [2]


PRICES = {"capex_pv": 150.0, "capex_batt": 110.0, "capex_inv": 120.0,
          "capex_ge": 145.0, "capex_conv_ac": 80.0}


def test_only_what_a_node_adds_to_its_parent_counts_as_an_extension() -> None:
    parent = _Plan(pv_kw=20.0, battery_kwh=100.0, inverter_kw=15.0, generator_kw=8.0)
    same = _Plan(pv_kw=20.0, battery_kwh=100.0, inverter_kw=15.0, generator_kw=8.0)
    assert _grown(same, parent) == {}

    grown = _Plan(pv_kw=23.5, pv_ac_kw=2.0, battery_kwh=100.0, inverter_kw=17.5,
                  generator_kw=8.0)
    assert _grown(grown, parent) == {"pv_kw": 3.5, "pv_ac_kw": 2.0, "inverter_kw": 2.5}


def test_a_bigger_generating_set_is_bought_whole_and_not_as_a_difference() -> None:
    """Two machines on one bus is a different plant, so an upgrade buys the new rating."""
    parent = _Plan(generator_kw=8.0)
    upgraded = _Plan(generator_kw=12.0)
    assert _grown(upgraded, parent) == {"generator_kw": 12.0}
    assert _equipment_usd({"generator_kw": 12.0}, PRICES, "mixed") == pytest.approx(
        12.0 * 145.0)


def test_the_array_on_the_load_bus_buys_the_string_inverters_that_put_it_there() -> None:
    plain = _equipment_usd({"pv_kw": 10.0}, PRICES, "mixed")
    divided = _equipment_usd({"pv_ac_kw": 10.0}, PRICES, "mixed")

    assert plain == pytest.approx(10.0 * 150.0)
    assert divided == pytest.approx(10.0 * (150.0 + 80.0))
    # Under a pure arrangement there is no second converter to buy.
    assert _equipment_usd({"pv_ac_kw": 10.0}, PRICES, "dc") == pytest.approx(10.0 * 150.0)


def test_an_extension_is_counted_as_a_path_meets_it_and_as_the_objective_pays_it() -> None:
    """The two counts the threshold needs, and they are not the same number."""
    tree = _Tree(PRICES)
    plans = {0: _Plan(pv_kw=20.0, battery_kwh=100.0, inverter_kw=15.0, generator_kw=8.0),
             1: _Plan(pv_kw=24.0, battery_kwh=120.0, inverter_kw=17.5, generator_kw=8.0),
             2: _Plan(pv_kw=24.0, battery_kwh=120.0, inverter_kw=17.5, generator_kw=8.0)}

    found = extensions(plans, tree, "mixed")
    assert found["nodes_after_the_root"] == 2
    assert found["nodes_that_extend"] == 1               # node 2 adds nothing
    assert found["n"] == pytest.approx(1.0)              # node 1 is certain
    assert found["n_discounted"] == pytest.approx(0.68)  # and discounted to 0.68

    # 4 kW of array, 20 kWh of storage and 2.5 kW of conversion, at the node's prices.
    spend = 4.0 * 150.0 + 20.0 * 110.0 + 2.5 * 120.0
    assert found["where"][0]["equipment_usd"] == pytest.approx(spend, abs=0.1)
    assert found["equipment_usd"]["median"] == pytest.approx(spend, abs=0.1)


def test_an_unlikely_late_extension_counts_for_less_than_a_certain_early_one() -> None:
    tree = _Tree(PRICES)
    early = {0: _Plan(pv_kw=20.0), 1: _Plan(pv_kw=24.0), 2: _Plan(pv_kw=24.0)}
    late = {0: _Plan(pv_kw=20.0), 1: _Plan(pv_kw=20.0), 2: _Plan(pv_kw=24.0)}

    assert extensions(early, tree, "mixed")["n_discounted"] == pytest.approx(0.68)
    # Node 2 is met by a quarter of the paths and discounted to 0.46.
    assert extensions(late, tree, "mixed")["n_discounted"] == pytest.approx(0.25 * 0.46)


def test_the_threshold_is_where_building_once_stops_being_the_dearer_policy() -> None:
    table = after_the_fact(flexible=100_000.0, built_once=112_000.0, n_discounted=1.5)

    assert table["V_usd"] == pytest.approx(12_000.0)
    assert table["F_star_usd"] == pytest.approx(8_000.0)
    # At the threshold the two policies cost the same, by construction.
    assert 100_000.0 + table["F_star_usd"] * 1.5 == pytest.approx(112_000.0)

    rows = {row["fixed_cost_usd"]: row["cheaper"] for row in table["table"]}
    assert rows[5_000.0] == "flexible"
    assert rows[10_000.0] == "built once"
    assert set(rows) == set(FIXED_COSTS_USD)


def test_a_park_that_is_never_extended_is_every_addition_after_the_root_held_at_zero() -> None:
    """The constraints the policy is expressed as, for every module and every node.

    Checked on a recorder rather than on a solved programme: what can go wrong here is a
    node or a module left out of the enumeration, which no value of the objective would
    reveal and a recorder shows directly.
    """
    class _Variable:
        def __init__(self, name: str) -> None:
            self.name = name

        def sel(self, **where):
            return _Term(self.name, where)

    class _Term:
        def __init__(self, name: str, where: dict) -> None:
            self.name, self.where = name, where

        def __eq__(self, other):
            return ("fixed", self.name, self.where, other)

        def __sub__(self, other):
            return _Term(f"{self.name}-{other.name}", {**self.where, "minus": other.where})

        __hash__ = None

    class _Model:
        def __init__(self) -> None:
            self.added: list[tuple] = []

        def add_constraints(self, expression, name: str = "") -> None:
            self.added.append((name, expression))

    class _Coords:
        node = [0, 1, 2]

    class _Programme:
        def __init__(self) -> None:
            self.model = _Model()
            self.coords = _Coords()
            self.variables = {n: _Variable(n) for n in
                              ("b_pv", "b_batt", "b_inv", "b_pv_ac", "z_ge")}

    programme = _Programme()
    hold_the_park(programme, _Tree(PRICES))
    names = [name for name, _ in programme.model.added]

    for module in ("b_pv", "b_batt", "b_inv", "b_pv_ac"):
        for node in (1, 2):
            assert f"built_once_{module}_{node}" in names
        assert f"built_once_{module}_0" not in names, "the root must stay free"
    for node in (1, 2):
        assert f"built_once_gen_{node}" in names
    assert len(names) == 4 * 2 + 2
