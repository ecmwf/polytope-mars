"""Comprehensive tests for polytope_mars.utils.datetimes — all public functions."""

import pytest

from polytope_mars.utils.datetimes import (
    _count_range_steps,
    convert_timestamp,
    count_steps,
    days_between_dates,
    find_step_intervals,
    from_range_to_list_date,
    from_range_to_list_num,
    hours_between_times,
)


# ---------------------------------------------------------------------------
# days_between_dates
# ---------------------------------------------------------------------------
class TestDaysBetweenDates:
    """Number of days between two YYYYMMDD strings."""

    def test_same_day(self):
        assert days_between_dates("20240101", "20240101") == 0

    def test_adjacent_days(self):
        assert days_between_dates("20240101", "20240102") == 1

    def test_cross_month_boundary(self):
        assert days_between_dates("20240131", "20240201") == 1

    def test_cross_year_boundary(self):
        assert days_between_dates("20231231", "20240101") == 1

    def test_full_month(self):
        assert days_between_dates("20240101", "20240131") == 30

    def test_leap_year_february(self):
        # 2024 is a leap year: Feb has 29 days
        assert days_between_dates("20240201", "20240301") == 29

    def test_non_leap_year_february(self):
        # 2023 is not a leap year: Feb has 28 days
        assert days_between_dates("20230201", "20230301") == 28

    def test_reversed_order_still_positive(self):
        """abs() is used inside, so reversed args give same result."""
        assert days_between_dates("20240110", "20240101") == 9

    def test_large_span(self):
        # 1 Jan 2020 → 1 Jan 2024 = 4 years, includes 2020 leap year
        assert days_between_dates("20200101", "20240101") == 1461


# ---------------------------------------------------------------------------
# hours_between_times
# ---------------------------------------------------------------------------
class TestHoursBetweenTimes:
    """Number of hours between two HHMM strings."""

    def test_same_time(self):
        assert hours_between_times("0000", "0000") == 0

    def test_noon(self):
        assert hours_between_times("0000", "1200") == 12

    def test_six_to_eighteen(self):
        assert hours_between_times("0600", "1800") == 12

    def test_one_hour(self):
        assert hours_between_times("0100", "0200") == 1

    def test_half_hour(self):
        assert hours_between_times("0000", "0030") == 0.5

    def test_reversed_is_positive(self):
        assert hours_between_times("1200", "0000") == 12

    def test_full_day(self):
        assert hours_between_times("0000", "2359") == pytest.approx(23 + 59 / 60, abs=0.01)


# ---------------------------------------------------------------------------
# convert_timestamp
# ---------------------------------------------------------------------------
class TestConvertTimestamp:
    """Format a HHMM (possibly short) string to HH:MM:SS."""

    def test_zero(self):
        assert convert_timestamp("0") == "00:00:00"

    def test_integer_zero(self):
        assert convert_timestamp(0) == "00:00:00"

    def test_hundred(self):
        assert convert_timestamp("100") == "01:00:00"

    def test_noon(self):
        assert convert_timestamp("1200") == "12:00:00"

    def test_end_of_day(self):
        assert convert_timestamp("2359") == "23:59:00"

    def test_midnight(self):
        assert convert_timestamp("0000") == "00:00:00"

    def test_integer_input(self):
        assert convert_timestamp(1200) == "12:00:00"

    def test_single_digit(self):
        assert convert_timestamp("5") == "00:05:00"

    def test_two_digits(self):
        assert convert_timestamp("30") == "00:30:00"


# ---------------------------------------------------------------------------
# find_step_intervals
# ---------------------------------------------------------------------------
class TestFindStepIntervals:
    """Generate step intervals from start/end/freq triplet."""

    def test_pure_digits(self):
        result = find_step_intervals("0", "10", "2")
        assert result == [0, 2, 4, 6, 8]  # range(0, 10, 2) — exclusive end

    def test_pure_digits_step_one(self):
        result = find_step_intervals("0", "5", "1")
        assert result == [0, 1, 2, 3, 4]

    def test_hourly(self):
        result = find_step_intervals("1h", "6h", "1h")
        assert len(result) == 6
        assert result[0] == "1h0m"
        assert result[-1] == "6h0m"

    def test_sub_hourly(self):
        result = find_step_intervals("0h", "1h", "30m")
        assert len(result) == 3  # 0h, 30m, 1h

    def test_minute_intervals(self):
        result = find_step_intervals("0h", "1h", "15m")
        assert len(result) == 5  # 0, 15m, 30m, 45m, 1h


# ---------------------------------------------------------------------------
# from_range_to_list_num
# ---------------------------------------------------------------------------
class TestFromRangeToListNum:
    """Convert "N/to/M" → list of number strings, or return unchanged."""

    def test_simple_range(self):
        result = from_range_to_list_num("1/to/5")
        assert result == ["1", "2", "3", "4", "5"]

    def test_single_value_range(self):
        result = from_range_to_list_num("3/to/3")
        assert result == ["3"]

    def test_non_range_returned_as_is(self):
        result = from_range_to_list_num("1/2/3")
        assert result == "1/2/3"

    def test_single_value_non_range(self):
        result = from_range_to_list_num("42")
        assert result == "42"

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match="Start of range"):
            from_range_to_list_num("5/to/1")

    def test_large_range(self):
        result = from_range_to_list_num("1/to/100")
        assert len(result) == 100
        assert result[0] == "1"
        assert result[-1] == "100"


# ---------------------------------------------------------------------------
# from_range_to_list_date
# ---------------------------------------------------------------------------
class TestFromRangeToListDate:
    """Convert "YYYYMMDD/to/YYYYMMDD" → "YYYYMMDD/…/YYYYMMDD" string."""

    def test_three_day_range(self):
        result = from_range_to_list_date("20240101/to/20240103")
        assert result == "20240101/20240102/20240103"

    def test_cross_month_boundary(self):
        result = from_range_to_list_date("20220130/to/20220202")
        assert result == "20220130/20220131/20220201/20220202"

    def test_single_date_passthrough(self):
        result = from_range_to_list_date("20240101")
        assert result == "20240101"

    def test_same_start_end_returns_single_string(self):
        """Same start and end → one date (not a joined string)."""
        result = from_range_to_list_date("20240615/to/20240615")
        assert result == "20240615"

    def test_two_day_range(self):
        result = from_range_to_list_date("20240301/to/20240302")
        assert result == "20240301/20240302"

    def test_leap_year_range(self):
        result = from_range_to_list_date("20240228/to/20240301")
        assert result == "20240228/20240229/20240301"

    def test_non_leap_year_range(self):
        result = from_range_to_list_date("20230228/to/20230301")
        assert result == "20230228/20230301"

    def test_slash_separated_non_range(self):
        result = from_range_to_list_date("20240101/20240201")
        assert result == "20240101/20240201"  # returned as-is


# ---------------------------------------------------------------------------
# count_steps — additional coverage beyond test_step_counter.py
# ---------------------------------------------------------------------------
class TestCountStepsExtra:
    """Extras to complement the existing test_step_counter.py suite."""

    def test_single_step_zero(self):
        assert count_steps("0") == 1

    def test_range_no_by_pure_digits(self):
        # "0/to/5" default 1h → treats start/end as hours → 6 steps
        assert count_steps("0/to/5") == 6

    def test_list_of_time_units(self):
        assert count_steps("0h/3h/6h/9h/12h") == 5

    def test_range_by_day(self):
        assert count_steps("0d/to/3d/by/1d") == 4

    def test_single_time_unit(self):
        assert count_steps("6h") == 1

    def test_range_same_start_end(self):
        assert count_steps("5/to/5/by/1") == 1


# ---------------------------------------------------------------------------
# _count_range_steps — direct testing
# ---------------------------------------------------------------------------
class TestCountRangeSteps:
    """Direct tests for the internal range counting helper."""

    def test_pure_digit_inclusive(self):
        # 0..10 by 2 → [0, 2, 4, 6, 8, 10] = 6
        assert _count_range_steps("0", "10", "2") == 6

    def test_pure_digit_step_one(self):
        assert _count_range_steps("0", "5", "1") == 6

    def test_pure_digit_not_exact(self):
        # 0..10 by 3 → [0, 3, 6, 9] = 4 (10 not reached)
        assert _count_range_steps("0", "10", "3") == 4

    def test_hours(self):
        assert _count_range_steps("1h", "6h", "1h") == 6

    def test_minutes(self):
        assert _count_range_steps("0m", "60m", "15m") == 5

    def test_seconds(self):
        assert _count_range_steps("0s", "60s", "10s") == 7

    def test_days(self):
        assert _count_range_steps("1d", "7d", "1d") == 7

    def test_mixed_h_and_m(self):
        # 0h to 2h by 30m → [0, 30m, 1h, 1h30m, 2h] = 5
        assert _count_range_steps("0h", "2h", "30m") == 5

    def test_same_start_end(self):
        assert _count_range_steps("5", "5", "1") == 1
        assert _count_range_steps("1h", "1h", "1h") == 1
