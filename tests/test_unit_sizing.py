"""What the planner pays for: the four terms of :class:`polytope_mars.sizing.UnitSizing`.

The shapes below are the measured ones (MEASUREMENTS.md, ``tools/measure_memory.py ranges
calibrate targets``), so these tests state what a deployed worker will do with a given budget, not
only that the arithmetic is self-consistent.

Ranges per field are the gaps in a spatial sub-tree's sorted grid indexes (one array-backed spatial node
per sub-tree), which keeps the HEALPix counts in the thousands even though a ring's pixels are
scattered over the index space.
"""

import pytest

from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.sizing import DEFAULT_FRAGMENT_BYTES, UnitSizing
from polytope_mars.tree_units import GroupSpec, plan_units

GiB = 1024**3
BUDGET_1_5_GiB = 3 * GiB // 2  # a 3 GiB fe pod, half of it
BUDGET_1_8_GiB = 9 * GiB // 5  # a 3.6 GiB fe pod, half of it

#: (points, index ranges per field) of one field, from ``tools/measure_memory.py ranges targets``
SHAPES = {
    "efas_danube": (634_550, 490),  # local_regular, 1,295 points per range
    "efas_volga": (609_851, 1_131),  # local_regular polygon, 539 points per range
    "efas_switzerland": (18_834, 151),  # local_regular polygon, 125 points per range
    "healpix1024_europe": (479_865, 1_388),  # healpix nested, 346 points per range (300,315 per row)
    "o1280_europe": (222_960, 541),  # octahedral, 412 points per range (1,080 per row)
    "healpix1024_global": (12_582_912, 1),  # the whole world in one contiguous range
    "efas_whole_domain": (13_439_104, 2_968),  # the whole EFAS grid, one range per row
}


def sizing(budget, **kwargs) -> UnitSizing:
    """The default limits with one budget: what a deployed worker is configured with."""
    conf = PolytopeMarsConfig.model_validate({"limits": {"memory_budget_bytes": budget, **kwargs}})
    return UnitSizing.from_limits(conf.limits)


def spec(shape, n_fields=1, key=(0,), max_groups=1) -> GroupSpec:
    points, ranges = SHAPES[shape]
    return GroupSpec(
        key=key,
        shape=(points, tuple(str(i) for i in range(n_fields)), ()),
        max_groups=max_groups,
        counts=(points,),
        range_counts=(ranges,),
    )


# --- the terms ----------------------------------------------------------------------------------


def test_the_gribjump_term_is_values_mask_and_one_vector_pair_per_range():
    s = UnitSizing(bytes_per_range=96, safety_factor=1.0)
    points, ranges = SHAPES["o1280_europe"]
    assert s.field_buffer_bytes(points, ranges) == 8 * points + points // 8 + 96 * ranges
    # 4 fields of one group cost four times that
    assert s.buffer_bytes(4, points, ranges) == 4 * s.field_buffer_bytes(points, ranges)


def test_whole_field_ranges_make_the_range_term_small_on_every_grid():
    """Why the range count is read off the tree, and why it does not decide the unit size.

    A range costs 96 B, so a field cut into nearly one range per point -- what a HEALPix-nested box
    does row by row -- costs 65 B per value, eight times the values themselves.  Ranges derived from
    the whole field's sorted indexes are 8.4 B/value on the same request.
    """
    s = UnitSizing(bytes_per_range=96, safety_factor=1.0)
    per_value = {}
    for name in ("efas_danube", "healpix1024_europe", "o1280_europe", "healpix1024_global"):
        points, ranges = SHAPES[name]
        per_value[name] = s.field_buffer_bytes(points, ranges) / points
    assert all(8 < value < 9 for value in per_value.values()), per_value
    # one range per point of the same HEALPix request (300,315 ranges)
    assert s.field_buffer_bytes(479_865, 300_315) / 479_865 > 65


def test_the_python_side_is_one_groups_values_plus_the_fragments():
    s = UnitSizing(bytes_per_value=32, safety_factor=1.0, fragment_bytes=1_000)
    # four fields of a two-field group: the values of one group, and the fragments
    estimate = s.estimate_bytes(4, 1_000, 10, group_fields=2)
    assert estimate == s.buffer_bytes(4, 1_000, 10) + 32 * 2_000 + 1_000
    # a point feature holds every field of its one call instead (group_fields=None)
    assert s.estimate_bytes(4, 1_000, 10) == estimate + 32 * 2_000


def test_the_points_of_a_call_cost_the_unit_nothing():
    """Measured: the spatial nodes a call reads its points from are resident for the whole request.

    They are built by ``prepare`` and priced by ``limits.max_tree_bytes`` (half the budget), so the
    number of spatial sub-trees a unit touches does not make its units smaller.
    """
    points, ranges = SHAPES["healpix1024_europe"]
    s = sizing(BUDGET_1_5_GiB)
    k = s.max_unit_groups(points, 1, ranges)
    estimate = s.estimate_bytes(k, points, ranges, group_fields=1)
    # gribjump's buffer for the whole call, one group's values, the fragments -- and nothing per point
    assert estimate == s.buffer_bytes(k, points, ranges) + s.python_bytes(points) + s.fragment_bytes
    assert estimate <= BUDGET_1_5_GiB
    # which is why the 24 hourly HEALPix groups of the LUMI case, each its own sub-tree, fit one call
    assert k >= 24


def test_the_fragment_term_is_twice_the_encoders_limit():
    """covjsonkit builds one fragment while the previous one is still referenced (8 MiB each)."""
    assert DEFAULT_FRAGMENT_BYTES == 2 * 8 * 1024 * 1024
    limits = PolytopeMarsConfig().limits
    assert UnitSizing.from_limits(limits).fragment_bytes == DEFAULT_FRAGMENT_BYTES
    assert UnitSizing.from_limits(limits, fragment_bytes=2 * 1_000_000).fragment_bytes == 2_000_000
    # an encoder that does not report a limit, or reports nonsense, falls back to the default
    assert UnitSizing.from_limits(limits, fragment_bytes="no").fragment_bytes == DEFAULT_FRAGMENT_BYTES


# --- what fits --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shape, n_fields, budget, expected_fields",
    [
        # the Volga ensemble (4 params per group) at a 3 GiB and a 3.6 GiB pod
        ("efas_volga", 4, BUDGET_1_5_GiB, 196),
        ("efas_volga", 4, BUDGET_1_8_GiB, 240),
        # the Switzerland ensemble: small fields, so the per-call field cap decides
        ("efas_switzerland", 1, BUDGET_1_5_GiB, 1024),
        # EFAS Danube x 40 steps against 1 GiB
        ("efas_danube", 1, GiB, 132),
    ],
)
def test_fields_per_call_for_the_measured_shapes(shape, n_fields, budget, expected_fields):
    points, ranges = SHAPES[shape]
    s = sizing(budget)
    k = s.max_unit_groups(points, n_fields, ranges)  # one branch: number/step compressed
    assert k * n_fields == expected_fields
    # the estimate of such a unit stays inside the budget, and one group more does not
    assert s.estimate_bytes(k * n_fields, points, ranges, group_fields=n_fields) <= budget
    over_budget = s.estimate_bytes((k + 1) * n_fields, points, ranges, group_fields=n_fields) > budget
    over_cap = (k + 1) * n_fields > s.max_fields_per_call
    assert over_budget or over_cap


def test_holding_one_group_plans_larger_units_than_holding_the_whole_call():
    """What the per-field consumption buys: ``bytes_per_value`` is paid for one group, not for the call."""
    points, ranges = SHAPES["efas_volga"]
    s = sizing(BUDGET_1_5_GiB)
    per_group = s.max_unit_groups(points, 4, ranges)
    # what the same budget would allow if the Python side held every field of the call instead
    room = BUDGET_1_5_GiB - s.fragment_bytes
    whole_call = room // (s.buffer_bytes(4, points, ranges) + s.python_bytes(4 * points))
    assert per_group > whole_call >= 1


def test_the_planner_turns_that_into_units():
    """The LUMI case: 24 hourly HEALPix groups, each its own sub-tree, against 1.5 GiB.

    Whole-field ranges (1,388 of them) leave room for the whole request in one call; one range per
    point (300,315) would be 32.7 MB of gribjump buffer per field and bound the call to 14 fields.
    """
    s = sizing(BUDGET_1_5_GiB)
    points, ranges = SHAPES["healpix1024_europe"]
    k = s.max_unit_groups(points, 1, ranges)
    assert k == 260
    specs = [spec("healpix1024_europe", key=(hour,), max_groups=k) for hour in range(24)]
    assert [length for _, length in plan_units(specs)] == [24]
    assert s.estimate_bytes(24, points, ranges, group_fields=1) <= BUDGET_1_5_GiB


def test_without_a_budget_a_unit_is_one_group():
    """Nothing bounds a larger call without a budget, so every call is one coverage."""
    s = sizing(None)
    points, ranges = SHAPES["efas_danube"]
    assert s.max_unit_groups(points, 1, ranges) == 1
    # ... and a single group is never refused: 12.6M points fit the raised cap
    global_points, global_ranges = SHAPES["healpix1024_global"]
    assert s.max_unit_groups(global_points, 1, global_ranges) == 1


def test_the_hard_caps_are_independent_of_the_budget_and_the_estimate():
    s = sizing(10**15)  # a budget nothing can exhaust
    points, ranges = SHAPES["o1280_europe"]
    assert s.max_values_per_unit == 256_000_000 and s.max_fields_per_call == 1024
    # 256M values is ~2 GB of gribjump buffer at 8 B/value: a backstop the budget reaches first
    assert s.max_unit_groups(points, 1, ranges) == 1024
    assert s.max_unit_groups(points, 4, ranges) == 1024 // 4
    assert sizing(10**15, max_fields_per_call=8).max_unit_groups(points, 1, ranges) == 8
    assert sizing(10**15, max_values_per_unit=10 * points).max_unit_groups(points, 1, ranges) == 10


@pytest.mark.parametrize("shape", ["healpix1024_global", "efas_whole_domain"])
def test_the_largest_single_fields_fit_one_call_at_the_deployed_budget(shape):
    """A field is fetched whole, so the two largest requests of the corpus have to fit 1.5 GiB."""
    points, ranges = SHAPES[shape]
    s = sizing(BUDGET_1_5_GiB)
    assert s.fits_field(points, 1, ranges) and s.max_unit_groups(points, 1, ranges) >= 1
    assert s.field_bytes(points, ranges) <= BUDGET_1_5_GiB
    assert s.estimate_bytes(1, points, ranges, group_fields=1) <= BUDGET_1_5_GiB


def test_a_group_that_does_not_fit_is_fetched_one_field_per_call():
    """One (param, level) per call costs one field's gribjump buffer and the group's values."""
    points, ranges = SHAPES["healpix1024_europe"]
    s = sizing(90_000_000)  # fits one field of a 4-param group, not all four
    assert s.max_unit_groups(points, 4, ranges) == 0
    assert s.fits_field(points, 4, ranges)
    assert s.field_bytes(points, ranges, 4) <= 90_000_000
    # one field of the group costs its buffer once, not four times
    assert s.field_bytes(points, ranges, 4) < s.estimate_bytes(4, points, ranges, group_fields=4)


@pytest.mark.parametrize("shape", ["healpix1024_global", "efas_whole_domain"])
def test_a_field_that_does_not_fit_is_refused(shape):
    """A field is never split, so a field larger than the budget cannot be served at all."""
    points, ranges = SHAPES[shape]
    s = sizing(500_000_000)
    assert s.max_unit_groups(points, 1, ranges) == 0
    assert not s.fits_field(points, 1, ranges)
    assert s.field_bytes(points, ranges) > 500_000_000
    # ... and so is a multi-param group of such a field, whose params are all held at once
    assert not sizing(BUDGET_1_5_GiB).fits_field(points, 4, ranges)


def test_sizing_reads_the_config():
    conf = PolytopeMarsConfig.model_validate(
        {
            "limits": {
                "memory_budget_bytes": 1000,
                "bytes_per_value": 10,
                "bytes_per_range": 2,
                "safety_factor": 2.0,
                "max_fields_per_call": 7,
            }
        }
    )
    s = UnitSizing.from_limits(conf.limits)
    assert s.budget == 1000 and s.bytes_per_value == 10
    assert s.bytes_per_range == 2 and s.safety_factor == 2.0 and s.max_fields_per_call == 7
    # the deprecated flags are accepted and change nothing
    accepted = PolytopeMarsConfig.model_validate(
        {"limits": {"per_field_consumption": False, "bytes_per_point_call": 128}}
    )
    assert UnitSizing.from_limits(accepted.limits) == UnitSizing.from_limits(PolytopeMarsConfig().limits)
