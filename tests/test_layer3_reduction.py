"""Layer 3: time-domain reduction and the design lattice.

Representative days must be real days carrying honest weights, and the lattice must be wide
enough that certifying over it means something. Both are checked here; the certification
itself is exercised separately, being far too slow for a test suite.
"""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.exact.certify import Lattice, _Box, _centre, _split
from microgrid_expansion.exact.simulator import Capacities
from microgrid_expansion.timedomain.kmedoids import kmedoids, pairwise_distances
from microgrid_expansion.timedomain.rep_days import (
    HOURS_PER_DAY,
    daily_features,
    reduce_to_rep_days,
    reduction_error,
)


def synthetic_year(days: int = 120):
    """A year-like instance with two seasons, so clustering has something to find."""
    from microgrid_expansion.battery import self_discharge_fraction, usable_fraction
    from microgrid_expansion.instances import SiteYear

    hours = np.arange(days * HOURS_PER_DAY)
    hour = hours % 24
    day = hours // 24
    season = 1.0 + 0.3 * np.sin(2 * np.pi * day / days)
    demand = season * (0.4 + 0.5 * np.exp(-((hour - 19) / 2.5) ** 2))
    yield_ = np.clip(np.sin(np.pi * (hour - 6) / 12.0), 0.0, None) * (0.8 - 0.2 * season)
    temperature = 28.0 + 5.0 * np.sin(2 * np.pi * (hour - 9) / 24.0)
    return SiteYear(site="test", year=2025, demand_kw=demand, specific_yield=yield_,
                    t_amb_c=temperature, usable_fraction=usable_fraction(temperature),
                    self_discharge=self_discharge_fraction(temperature),
                    trajectory="centrale", maturity_months=12, seed=0)


# ------------------------------------------------------------------ k-medoids
def test_medoids_are_real_observations_not_averages():
    """The point of medoids: a representative day must be a day that happened."""
    rng = np.random.default_rng(0)
    points = np.vstack([rng.normal(centre, 0.3, (25, 2))
                        for centre in ([0, 0], [7, 0], [0, 7])])
    result = kmedoids(points, 3)
    assert result.n_clusters == 3
    for medoid in result.medoids:
        assert 0 <= medoid < len(points)
        assert np.isin(points[medoid], points).all()
    assert result.weights.sum() == len(points)


def test_clustering_recovers_separated_groups():
    rng = np.random.default_rng(1)
    points = np.vstack([rng.normal(centre, 0.2, (20, 2))
                        for centre in ([0, 0], [10, 0], [0, 10])])
    result = kmedoids(points, 3)
    assert sorted(result.weights) == [20, 20, 20]


def test_weights_let_one_observation_stand_for_several():
    points = np.array([[0.0], [0.1], [5.0]])
    heavy = kmedoids(points, 2, weights=np.array([1.0, 1.0, 50.0]))
    assert heavy.weights.sum() == pytest.approx(52.0)


def test_clustering_is_deterministic():
    rng = np.random.default_rng(2)
    points = rng.normal(size=(40, 3))
    first, second = kmedoids(points, 4), kmedoids(points, 4)
    assert np.array_equal(first.medoids, second.medoids)


@pytest.mark.parametrize("k", [0, 99])
def test_impossible_cluster_counts_are_rejected(k):
    with pytest.raises(ValueError):
        kmedoids(np.zeros((10, 2)), k)


def test_distances_are_symmetric_with_a_zero_diagonal():
    points = np.random.default_rng(3).normal(size=(12, 4))
    d = pairwise_distances(points)
    assert np.allclose(d, d.T)
    assert np.allclose(np.diag(d), 0.0, atol=1e-9)


# --------------------------------------------------------- representative days
def test_representative_days_account_for_every_day():
    instance = synthetic_year()
    rep = reduce_to_rep_days(instance, 8)
    assert rep.n_days == 8
    assert rep.weight.sum() == instance.demand_kw.size / HOURS_PER_DAY
    assert rep.demand.shape == (8, HOURS_PER_DAY)


def test_representative_days_are_days_of_the_year():
    """Each representative profile must be lifted from the instance, not synthesised."""
    instance = synthetic_year()
    rep = reduce_to_rep_days(instance, 6)
    days = instance.demand_kw.reshape(-1, HOURS_PER_DAY)
    for row, source in zip(rep.demand, rep.medoid_days):
        assert np.allclose(row, days[source])


def test_the_reduction_error_falls_as_days_are_added():
    instance = synthetic_year()
    coarse = reduction_error(instance, reduce_to_rep_days(instance, 3))
    fine = reduction_error(instance, reduce_to_rep_days(instance, 16))
    assert abs(fine["energy_error_pct"]) <= abs(coarse["energy_error_pct"]) + 1.0
    assert fine["days_represented"] == coarse["days_represented"]


def test_a_dozen_days_reproduce_the_annual_energy():
    """The acceptance criterion of the layer: within a few per cent."""
    instance = synthetic_year()
    error = reduction_error(instance, reduce_to_rep_days(instance, 12))
    assert abs(error["energy_error_pct"]) < 5.0
    assert abs(error["yield_error_pct"]) < 5.0


def test_features_combine_both_drivers():
    """Clustering on demand alone would merge a cloudy day with a sunny one."""
    instance = synthetic_year(days=10)
    features = daily_features(instance.demand_kw, instance.specific_yield)
    assert features.shape == (10, 2 * HOURS_PER_DAY)
    assert np.isfinite(features).all()


def test_asking_for_more_days_than_the_year_holds_is_rejected():
    with pytest.raises(ValueError, match="representative days"):
        reduce_to_rep_days(synthetic_year(days=5), 10)


# ---------------------------------------------------------------- the lattice
def test_the_lattice_is_sized_around_the_instance():
    instance = synthetic_year()
    lattice = Lattice.around(instance)
    assert lattice.size > 0
    # it must be able to hold a plant covering the demand several times over
    daily = float(instance.demand_kw.sum()) / (instance.demand_kw.size / 24)
    assert lattice.n_batt[1] * lattice.batt_unit_kwh > daily
    assert lattice.n_inv[0] >= 1                     # an inverter is always needed


def test_lattice_points_map_to_physical_capacities():
    lattice = Lattice(1.0, 5.0, 2.0, (5.0, 10.0), (0, 4), (0, 3), (1, 2))
    caps = lattice.capacities(2, 3, 1, 10.0)
    assert caps == Capacities(pv_kw=2.0, battery_kwh=15.0,
                              inverter_kw=2.0, generator_kw=10.0)
    # Not every combination is a plant: an array is limited by what its converter admits,
    # so the lattice counts the buildable pairs rather than the Cartesian product. With one
    # inverter unit of 2 kW only 0 to 2 kW of array can be wired, with two units 0 to 4.
    buildable_pairs = sum(1
                          for n_inv in (1, 2)
                          for n_pv in range(0, 5)
                          if lattice.admits(n_pv, n_inv))
    assert lattice.size == buildable_pairs * 4 * 2
    assert lattice.size < 5 * 4 * 2 * 2          # the product would include unwirable ones


# --------------------------------------------------------------- box splitting
def test_splitting_partitions_a_box_without_loss():
    box = _Box(0.0, (0, 9), (0, 3), (1, 2), (5.0, 10.0))
    children = _split(box)
    assert len(children) == 2
    assert sum(c.n_points for c in children) == box.n_points


def test_splitting_chooses_the_widest_coordinate():
    assert _split(_Box(0.0, (0, 20), (0, 1), (1, 1), (5.0,)))[0].pv != (0, 20)
    assert _split(_Box(0.0, (0, 1), (0, 30), (1, 1), (5.0,)))[0].batt != (0, 30)
    catalogue = _split(_Box(0.0, (0, 1), (0, 1), (1, 1), (5.0, 10.0, 16.0, 30.0)))
    assert all(len(c.gens) < 4 for c in catalogue)


def test_a_singleton_box_is_recognised():
    assert _Box(0.0, (3, 3), (2, 2), (1, 1), (10.0,)).is_singleton()
    assert not _Box(0.0, (3, 4), (2, 2), (1, 1), (10.0,)).is_singleton()


def test_the_centre_of_a_box_lies_inside_it():
    box = _Box(0.0, (2, 8), (1, 5), (1, 3), (5.0, 10.0, 16.0))
    n_pv, n_bt, n_iv, gen = _centre(box)
    assert box.pv[0] <= n_pv <= box.pv[1]
    assert box.batt[0] <= n_bt <= box.batt[1]
    assert box.inv[0] <= n_iv <= box.inv[1]
    assert gen in box.gens


# ------------------------------------------------------- the certificate itself
def _tiny_instance(days: int = 3):
    """A short instance, so that a relaxation costs a fraction of a second."""
    return synthetic_year(days=days)


def test_certification_accounts_for_every_design():
    """Optimality is proven by exhaustion: each design is pruned or simulated."""
    from microgrid_expansion.exact.certify import Lattice, certify

    instance = _tiny_instance()
    lattice = Lattice(pv_unit_kw=2.0, batt_unit_kwh=10.0, inv_unit_kw=2.0,
                      generator_ratings=(5.0, 10.0),
                      n_pv=(0, 5), n_batt=(0, 3), n_inv=(1, 2))
    result = certify(instance, lattice, coarse_step=2, max_relaxations=60, verbose=False)

    assert result.proven
    assert result.covered_points == result.lattice_size
    assert result.pruned_points + result.enumerated_points == lattice.size


def test_the_certified_optimum_beats_every_design_it_examined():
    """The incumbent must be the best of the lattice, not merely a good one."""
    import itertools

    from microgrid_expansion.exact.certify import (
        Lattice, _evaluate_rule, certify)
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.exact.simulator import (
        BatteryModel, Controller, GeneratorModel)
    from microgrid_expansion.settings import default_settings

    instance = _tiny_instance()
    lattice = Lattice(pv_unit_kw=3.0, batt_unit_kwh=15.0, inv_unit_kw=3.0,
                      generator_ratings=(5.0,), n_pv=(0, 3), n_batt=(0, 2), n_inv=(1, 2))
    result = certify(instance, lattice, coarse_step=2, max_relaxations=40, verbose=False)

    settings = default_settings()
    # The comparison must use the objective the search minimises, conversion equipment
    # included: enumerating a cheaper objective would compare two different problems and
    # the certificate would appear to lose to a design it never had the option of buying.
    economics = Economics(
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh,
        conversion_usd_kw=settings.coupling.cost_usd_kw(lattice.architecture))
    battery = BatteryModel.from_spec(settings.battery)
    generator = GeneratorModel.from_spec(
        max(settings.generators, key=lambda g: g.rating_kw),
        settings.economics.diesel_price_usd_l)
    annualised = economics.annualised()

    # exhaustive check: the lattice is small enough to enumerate here
    best = min(
        _evaluate_rule(instance, lattice.capacities(p, b, i, g), economics, battery,
                       generator, Controller(), annualised)
        for p, b, i, g in itertools.product(
            range(lattice.n_pv[0], lattice.n_pv[1] + 1),
            range(lattice.n_batt[0], lattice.n_batt[1] + 1),
            range(lattice.n_inv[0], lattice.n_inv[1] + 1),
            lattice.generator_ratings))
    assert result.z_rule == pytest.approx(best, rel=1e-9)


def test_the_price_of_the_heuristic_is_non_negative():
    """Proposition 1 forbids the rule-based optimum falling below the cost-optimal one."""
    from microgrid_expansion.exact.certify import Lattice, certify

    instance = _tiny_instance()
    lattice = Lattice(pv_unit_kw=3.0, batt_unit_kwh=15.0, inv_unit_kw=3.0,
                      generator_ratings=(5.0,), n_pv=(0, 3), n_batt=(0, 2), n_inv=(1, 2))
    result = certify(instance, lattice, coarse_step=2, max_relaxations=40, verbose=False)
    assert result.price_abs >= -1e-6
    assert result.z_opt <= result.z_rule + 1e-6


def test_the_bound_never_exceeds_the_incumbent():
    """A bound above the incumbent would mean the relaxation is not a relaxation."""
    from microgrid_expansion.exact.certify import Lattice, certify

    instance = _tiny_instance()
    lattice = Lattice(pv_unit_kw=2.0, batt_unit_kwh=10.0, inv_unit_kw=2.0,
                      generator_ratings=(5.0, 10.0),
                      n_pv=(0, 4), n_batt=(0, 3), n_inv=(1, 2))
    result = certify(instance, lattice, coarse_step=2, max_relaxations=50, verbose=False)
    assert result.lower_bound <= result.z_rule + 1e-6


# ----------------------------------------------- the plant has to be buildable
def test_the_array_reaches_the_load_only_through_its_conversion():
    """A hybrid inverter caps what the array can deliver, whatever the array's size.

    Under direct-current coupling the array sits on the battery's bus and everything it
    sends the load is converted. An array many times the inverter's rating is therefore
    perfectly buildable — it charges the battery around the inverter — but it cannot serve
    the load beyond that rating, and the plant that ignores the distinction sizes an
    installation nobody can wire.
    """
    import numpy as np

    from microgrid_expansion.exact.simulator import (
        BatteryModel, Capacities, Controller, GeneratorModel, simulate)

    instance = _tiny_instance()
    caps = Capacities(pv_kw=60.0, battery_kwh=15.0,
                      inverter_kw=0.4 * float(instance.demand_kw.max()),
                      generator_kw=0.0, architecture="dc")
    dispatch = simulate(instance.demand_kw, instance.specific_yield, instance.t_amb_c,
                        caps, BatteryModel(), GeneratorModel(), Controller())

    assert dispatch.pv_to_load_kw.max() <= caps.inverter_kw + 1e-9
    assert dispatch.inverter_flow_kw.max() <= caps.inverter_kw + 1e-9
    # and the surplus is not lost: it charges the battery without crossing the inverter
    assert dispatch.charge_kw.max() > caps.inverter_kw


def test_the_two_architectures_are_not_the_same_plant():
    """Coupling changes what the inverter carries, and so changes the trajectory.

    Were the two indistinguishable there would be nothing to arbitrate and the search could
    settle the architecture by price alone. They are not: on the same design the hybrid
    inverter carries the array's output under one and the battery's under the other.
    """
    from microgrid_expansion.exact.simulator import (
        BatteryModel, Capacities, Controller, GeneratorModel, simulate)

    instance = _tiny_instance()
    # An inverter deliberately below the demand peak, so that the constraint has something
    # to bite on: it is the only regime in which the two architectures can differ.
    rating = 0.4 * float(instance.demand_kw.max())
    flows = {}
    for architecture in ("dc", "ac"):
        caps = Capacities(pv_kw=12.0, battery_kwh=15.0, inverter_kw=rating,
                          generator_kw=5.0, architecture=architecture)
        dispatch = simulate(instance.demand_kw, instance.specific_yield, instance.t_amb_c,
                            caps, BatteryModel(), GeneratorModel(), Controller())
        flows[architecture] = dispatch
        assert dispatch.inverter_flow_kw.max() <= caps.inverter_kw + 1e-9

    assert flows["dc"].pv_to_load_kw.max() <= rating + 1e-9
    assert flows["ac"].pv_to_load_kw.max() > rating   # the array bypasses the inverter


def test_no_charge_controller_is_sized_outside_the_hybrid_inverter():
    """Direct-current coupling buys no conversion beyond the inverter itself.

    A hybrid inverter arrives with its own trackers and expects to be the sole authority
    over the pack; a second regulator on the same lithium bank means two controllers
    negotiating one charge current, which is only safe when both answer to the same
    battery-management conversation. The model therefore never sizes external controllers,
    and what limits the array under this architecture is the inverter's own admission
    ratio, not a separate device.
    """
    from microgrid_expansion.settings import default_settings

    coupling = default_settings().coupling
    assert coupling.cost_usd_kw("dc") == 0.0        # nothing bought beyond the inverter
    assert coupling.cost_usd_kw("ac") > 0.0         # string inverters are a real purchase
    assert coupling.dc_ac_ratio_max > coupling.ac_ratio_max


def test_an_array_is_enlarged_only_by_enlarging_its_converter():
    """Array and converter are one decision. The lattice must not offer them apart."""
    from microgrid_expansion.exact.certify import Lattice

    lattice = Lattice(pv_unit_kw=1.0, batt_unit_kwh=5.0, inv_unit_kw=2.0,
                      generator_ratings=(5.0,), n_pv=(0, 8), n_batt=(0, 1),
                      n_inv=(1, 2), architecture="dc")
    ratio = lattice.ratio_max
    for n_inv in (1, 2):
        admitted = [n for n in range(0, 9) if lattice.admits(n, n_inv)]
        assert max(admitted) * lattice.pv_unit_kw <= ratio * n_inv * lattice.inv_unit_kw
        # one more unit of array than the converter admits must be refused
        assert not lattice.admits(max(admitted) + 1, n_inv)
    # and a larger inverter admits a strictly larger array
    assert (max(n for n in range(0, 9) if lattice.admits(n, 2))
            > max(n for n in range(0, 9) if lattice.admits(n, 1)))


def test_the_cost_optimal_design_is_buildable():
    """Rounding the continuous optimum must land on a plant, not merely on a lattice point.

    The relaxation returns continuous capacities; rounding them independently can carry the
    point across the array-to-inverter ceiling — array rounded up, converter down — and the
    pinned relaxation then has no feasible dispatch at all. The symptom was an infinite
    cost-optimal value and a negative price of the heuristic, which Proposition 1 forbids.
    """
    from microgrid_expansion.exact.certify import Lattice, certify

    instance = _tiny_instance()
    lattice = Lattice(pv_unit_kw=3.0, batt_unit_kwh=15.0, inv_unit_kw=3.0,
                      generator_ratings=(5.0,), n_pv=(0, 3), n_batt=(0, 2), n_inv=(1, 2))
    result = certify(instance, lattice, coarse_step=2, max_relaxations=40, verbose=False)

    assert result.design_opt is not None
    assert lattice.admits(round(result.design_opt.pv_kw / lattice.pv_unit_kw),
                          round(result.design_opt.inverter_kw / lattice.inv_unit_kw))
    assert np.isfinite(result.z_opt)
    assert result.price_abs >= -1e-6            # Proposition 1


def test_narrowing_by_bound_cannot_discard_the_optimum():
    """The pre-sizing must be a bound, never a judgement.

    Trimming a generous lattice by eye is how a certificate quietly becomes an assertion:
    the excluded region is exactly where nobody looked. Here the trimming is done by the
    relaxation, so every discarded design carries a proof that it costs at least a bound
    already exceeded by a sizing in hand. The optimum therefore survives it, and the
    certificate still accounts for the lattice it was asked to search.
    """
    import itertools

    from microgrid_expansion.exact.certify import (
        Lattice, _evaluate_rule, narrow_to_incumbent)
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.exact.simulator import (
        BatteryModel, Controller, GeneratorModel)
    from microgrid_expansion.settings import default_settings

    instance = _tiny_instance()
    lattice = Lattice(pv_unit_kw=1.5, batt_unit_kwh=10.0, inv_unit_kw=2.0,
                      generator_ratings=(5.0,), n_pv=(0, 8), n_batt=(0, 5), n_inv=(1, 6))
    settings = default_settings()
    economics = Economics(
        voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh,
        conversion_usd_kw=settings.coupling.cost_usd_kw(lattice.architecture))
    battery = BatteryModel.from_spec(settings.battery)
    generator = GeneratorModel.from_spec(
        max(settings.generators, key=lambda g: g.rating_kw),
        settings.economics.diesel_price_usd_l)
    annualised = economics.annualised()

    grid = [(p, b, i, g)
            for p, b, i, g in itertools.product(
                range(lattice.n_pv[0], lattice.n_pv[1] + 1),
                range(lattice.n_batt[0], lattice.n_batt[1] + 1),
                range(lattice.n_inv[0], lattice.n_inv[1] + 1),
                lattice.generator_ratings)
            if lattice.admits(p, i)]
    costs = {point: _evaluate_rule(instance, lattice.capacities(*point), economics,
                                   battery, generator, Controller(), annualised)
             for point in grid}
    best_point = min(costs, key=costs.get)
    incumbent = costs[best_point]

    narrowed, removed, calls = narrow_to_incumbent(
        instance, lattice, incumbent, economics, battery, generator, verbose=False)

    assert narrowed.n_pv[0] <= best_point[0] <= narrowed.n_pv[1]
    assert narrowed.n_batt[0] <= best_point[1] <= narrowed.n_batt[1]
    assert narrowed.n_inv[0] <= best_point[2] <= narrowed.n_inv[1]
    assert removed == lattice.size - narrowed.size
    assert calls > 0

    # every design the trimming discarded is genuinely no better than the incumbent
    for point, cost in costs.items():
        inside = (narrowed.n_pv[0] <= point[0] <= narrowed.n_pv[1]
                  and narrowed.n_batt[0] <= point[1] <= narrowed.n_batt[1]
                  and narrowed.n_inv[0] <= point[2] <= narrowed.n_inv[1])
        if not inside:
            assert cost >= incumbent - 1e-6


def test_an_unwirable_design_costs_infinity():
    """No path of the search may adopt a plant that cannot be built.

    The guard was written at three call sites and omitted at the fourth — the centre of a
    box, which may straddle the array-to-inverter ceiling even when the box does not lie
    wholly beyond it. The search accordingly adopted an incumbent of sixty kilowatts of
    array behind a twenty-two kilowatt inverter, and every bound was then compared against
    a cost no real plant achieves. Under direct-current coupling the conversion is bought
    with the inverter, so that ceiling is the only thing standing between the search and
    free photovoltaic capacity.
    """
    from microgrid_expansion import config
    from microgrid_expansion.exact.certify import Lattice, _evaluate_rule
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.exact.simulator import (
        BatteryModel, Capacities, Controller, GeneratorModel)
    from microgrid_expansion.settings import default_settings

    instance = _tiny_instance()
    settings = default_settings()
    economics = Economics(voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh)
    battery = BatteryModel.from_spec(settings.battery)
    generator = GeneratorModel.from_spec(
        max(settings.generators, key=lambda g: g.rating_kw),
        settings.economics.diesel_price_usd_l)
    annualised = economics.annualised()

    inverter = 3.0
    admissible = Capacities(config.DC_AC_RATIO_MAX * inverter, 15.0, inverter, 5.0,
                            architecture="dc")
    beyond = Capacities(admissible.pv_kw * 1.5, 15.0, inverter, 5.0, architecture="dc")

    finite = _evaluate_rule(instance, admissible, economics, battery, generator,
                            Controller(), annualised)
    infinite = _evaluate_rule(instance, beyond, economics, battery, generator,
                              Controller(), annualised)
    assert np.isfinite(finite)
    assert infinite == float("inf")

    # and the search cannot return one either
    lattice = Lattice(pv_unit_kw=3.0, batt_unit_kwh=15.0, inv_unit_kw=1.0,
                      generator_ratings=(5.0,), n_pv=(0, 4), n_batt=(0, 2), n_inv=(1, 4))
    from microgrid_expansion.exact.certify import certify
    result = certify(instance, lattice, coarse_step=2, max_relaxations=60, verbose=False)
    assert result.design.admissible(lattice.ratio_max)
