from polytope_mars.utils.datetimes import find_step_intervals, from_range_to_list_date


def test_from_range_to_list_date_spans_months():
    date_range = "20220130/to/20220202"
    expected = "20220130/20220131/20220201/20220202"
    assert from_range_to_list_date(date_range) == expected


def test_find_step_intervals_inclusive_upper_bound():
    """Step range 6/to/48/by/6 must include 48 (MARS convention: inclusive upper bound)."""
    result = find_step_intervals("6", "48", "6")
    assert result == [6, 12, 18, 24, 30, 36, 42, 48]


def test_find_step_intervals_simple_range():
    """Step range 0/to/10/by/2 must include 10."""
    result = find_step_intervals("0", "10", "2")
    assert result == [0, 2, 4, 6, 8, 10]


def test_find_step_intervals_single_step():
    """Step range 0/to/0/by/1 must return [0]."""
    result = find_step_intervals("0", "0", "1")
    assert result == [0]
