"""What the planner pays for: the two terms of :class:`polytope_mars.sizing.UnitSizing`.

The shapes below are the measured ones (MEASUREMENTS.md, ``tools/measure_memory.py ranges``), so
these tests state what a deployed worker will do with a given budget, not only that the arithmetic
is self-consistent.
"""

import pytest

from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.sizing import MAX_FIELDS_PER_UNIT, UnitSizing
from polytope_mars.tree_units import GroupSpec, plan_units

GiB = 1024**3
BUDGET_1_5_GiB = 3 * GiB // 2  # the fe pool's budget on LUMI

#: (points, index ranges per field) of one field, from ``tools/measure_memory.py ranges``
SHAPES = {
    "efas_danube": (634_550, 490),  # local_regular, 1295 points per range
    "healpix1024_europe": (479_865, 300_315),  # healpix nested, 1.6 points per range
    "o1280_europe": (222_960, 1_080),  # octahedral, 206 points per range
    "healpix1024_global": (12_583_936, 6_291_968),  # whole world, 2 points per range
}


def sizing(budget, **kwargs) -> UnitSizing:
    """The default limits with one budget: what a deployed worker is configured with."""
    conf = PolytopeMarsConfig.model_validate({"limits": {"memory_budget_bytes": budget}})
    return UnitSizing.from_limits(conf.limits, **kwargs)


def spec(shape, n_fields=1, key=(0,), max_groups=1) -> GroupSpec:
    points, ranges = SHAPES[shape]
    return GroupSpec(
        key=key,
        shape=(points, tuple(str(i) for i in range(n_fields)), ()),
        max_groups=max_groups,
        counts=(points,),
        range_counts=(ranges,),
    )


# --- the two terms ----------------------------------------------------------------------------------


def test_the_gribjump_term_is_values_mask_and_one_vector_pair_per_range():
    s = UnitSizing(bytes_per_range=96, safety_factor=1.0)
    points, ranges = SHAPES["o1280_europe"]
    assert s.field_buffer_bytes(points, ranges) == 8 * points + points // 8 + 96 * ranges
    # 4 fields of one group cost four times that
    assert s.buffer_bytes(4, points, ranges) == 4 * s.field_buffer_bytes(points, ranges)


def test_ranges_dominate_the_gribjump_term_on_healpix_nested_only():
    """Why the range count is read off the tree instead of a per-grid constant."""
    s = UnitSizing(bytes_per_range=96, safety_factor=1.0)
    per_value = {}
    for name in ("efas_danube", "healpix1024_europe", "o1280_europe"):
        points, ranges = SHAPES[name]
        per_value[name] = s.field_buffer_bytes(points, ranges) / points
    assert 8 < per_value["efas_danube"] < 9  # one range per latitude line: the ranges are free
    assert 8 < per_value["o1280_europe"] < 9
    assert per_value["healpix1024_europe"] > 65  # ~0.63 ranges per point: 8x the values themselves


def test_the_python_term_is_one_constant_for_every_grid():
    s = UnitSizing(bytes_per_value=128)
    assert s.python_bytes(1_000) == 128_000
    assert s.estimate_bytes(2, 1_000, 10) == s.buffer_bytes(2, 1_000, 10) + 128 * 2_000


# --- what fits --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape, n_fields, budget, expected_k",
    [
        # the LUMI case: a HEALPix Europe box x 24 hourly fields against a 1.5 GiB budget
        ("healpix1024_europe", 1, BUDGET_1_5_GiB, 14),
        # EFAS Danube x 40 steps against 1 GiB: the Python term binds (81 MB per field)
        ("efas_danube", 1, GiB, 12),
        # an O1280 Europe box is small: the cap on values decides, not the budget
        ("o1280_europe", 1, 10 * GiB, 35),
        # several params per group: a unit holds fewer groups
        ("o1280_europe", 4, 10 * GiB, 8),
    ],
)
def test_groups_per_call_for_the_measured_shapes(shape, n_fields, budget, expected_k):
    points, ranges = SHAPES[shape]
    s = sizing(budget)
    assert s.max_unit_groups(points, n_fields, ranges) == expected_k
    # the estimate of such a unit stays inside the budget, and one group more does not
    assert s.estimate_bytes(expected_k * n_fields, points, ranges) <= budget
    over_budget = s.estimate_bytes((expected_k + 1) * n_fields, points, ranges) > budget
    over_cap = (expected_k + 1) * n_fields * points > (s.max_values_per_unit or 0)
    assert over_budget or over_cap


def test_the_planner_turns_that_into_units():
    """24 hourly HEALPix groups against 1.5 GiB: 14 fields in the first call, 10 in the second."""
    s = sizing(BUDGET_1_5_GiB)
    points, ranges = SHAPES["healpix1024_europe"]
    k = s.max_unit_groups(points, 1, ranges)
    specs = [spec("healpix1024_europe", key=(hour,), max_groups=k) for hour in range(24)]
    assert [length for _, length in plan_units(specs)] == [14, 10]


def test_without_a_budget_a_unit_is_one_group_but_the_cap_still_holds():
    s = sizing(None)
    points, ranges = SHAPES["efas_danube"]
    assert s.max_unit_groups(points, 1, ranges) == 1
    # a single group over the hard cap does not fit at all: it is fetched in bands
    global_points, global_ranges = SHAPES["healpix1024_global"]
    assert s.max_unit_groups(global_points, 1, global_ranges) == 0
    assert not s.fits_group(global_points, 1, global_ranges)


def test_the_hard_cap_is_independent_of_the_budget_and_the_estimate():
    s = sizing(10**15)  # a budget nothing can exhaust
    points, ranges = SHAPES["o1280_europe"]
    assert s.max_values_per_unit == 8_000_000
    assert s.max_unit_groups(points, 1, ranges) == 8_000_000 // points == 35
    assert sizing(10**15, per_field_consumption=True).max_unit_groups(points, 1, ranges) == 35


def test_a_whole_world_field_is_served_by_bands_at_any_budget():
    """No cap and no budget can refuse a single field: it is cut into latitude bands instead."""
    points, ranges = SHAPES["healpix1024_global"]
    for budget in (None, 100_000_000, BUDGET_1_5_GiB):
        s = sizing(budget)
        assert not s.fits_group(points, 1, ranges)
        band = s.band_points(1, ranges / points)
        assert 1 <= band < points
        if budget is not None:
            # one band of one field fits both terms
            assert s.estimate_bytes(1, band, round(band * ranges / points)) <= budget


def test_bands_are_smaller_on_a_grid_that_needs_more_ranges():
    s = sizing(1_000_000_000)
    healpix = s.band_points(1, SHAPES["healpix1024_europe"][1] / SHAPES["healpix1024_europe"][0])
    octahedral = s.band_points(1, SHAPES["o1280_europe"][1] / SHAPES["o1280_europe"][0])
    assert healpix < octahedral
    # with several fields in the group the Python side (one band per field) binds instead
    assert s.band_points(16, 0.0) < s.band_points(1, 0.0)


# --- per-field consumption ---------------------------------------------------------------------------


def test_per_field_consumption_sizes_the_python_side_by_the_group():
    points, ranges = SHAPES["healpix1024_europe"]
    budget = BUDGET_1_5_GiB
    whole = sizing(budget)
    lazy = sizing(budget, per_field_consumption=True)
    assert lazy.max_unit_groups(points, 1, ranges) > whole.max_unit_groups(points, 1, ranges)
    # ... and never more than one call's worth of fields
    assert sizing(10**15, per_field_consumption=True).max_unit_groups(10, 1, 1) == MAX_FIELDS_PER_UNIT
    assert lazy.estimate_bytes(10, points, ranges, group_fields=1) < whole.estimate_bytes(10, points, ranges)


def test_sizing_reads_the_config():
    conf = PolytopeMarsConfig.model_validate(
        {"limits": {"memory_budget_bytes": 1000, "bytes_per_value": 10, "bytes_per_range": 2, "safety_factor": 2.0}}
    )
    s = UnitSizing.from_limits(conf.limits)
    assert s.budget == 1000 and s.bytes_per_value == 10
    assert s.bytes_per_range == 2 and s.safety_factor == 2.0
    assert not s.per_field_consumption
    assert UnitSizing.from_limits(conf.limits, per_field_consumption=True).per_field_consumption
