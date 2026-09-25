import pandas as pd
import pytest

from polytope_mars.utils.datetimes import (
    convert_timestamp,
    count_dates,
    count_times,
    find_step_intervals,
    from_range_to_list_date,
    hours_between_times,
    time_step_to_freq,
)


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


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0", "00:00:00"),
        ("6", "06:00:00"),
        ("06", "06:00:00"),
        ("12", "12:00:00"),
        ("100", "01:00:00"),
        ("0600", "06:00:00"),
        ("1230", "12:30:00"),
        ("06:00", "06:00:00"),
    ],
)
def test_convert_timestamp_hours_and_hhmm(value, expected):
    assert convert_timestamp(value) == expected


@pytest.mark.parametrize(
    "step, expected",
    [("6", "360min"), ("12", "720min"), ("1", "60min"), ("0100", "60min"), ("0030", "30min"), ("0130", "90min")],
)
def test_time_step_to_freq_hours_and_hhmm(step, expected):
    assert time_step_to_freq(step) == expected


@pytest.mark.parametrize(
    "start, end, step",
    [("0", "18", "6"), ("0000", "1800", "0600"), ("00", "18", "06")],
)
def test_time_range_by_step_expands_hourly(start, end, step):
    times = pd.date_range(start=convert_timestamp(start), end=convert_timestamp(end), freq=time_step_to_freq(step))
    assert times.strftime("%H:%M:%S").tolist() == ["00:00:00", "06:00:00", "12:00:00", "18:00:00"]


@pytest.mark.parametrize("start, end", [("0", "12"), ("0000", "1200"), ("00:00", "12:00")])
def test_hours_between_times_accepts_hours_and_hhmm(start, end):
    assert hours_between_times(start, end) == 12


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0000", 1),
        ("0000/1200", 2),
        ("0/to/18/by/6", 4),
        ("0000/to/1800/by/0600", 4),
        ("0000/to/0300", 4),
        ("0/to/12/by/12", 2),
    ],
)
def test_count_times(value, expected):
    assert count_times(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("20250101", 1),
        ("20250101/20250105", 2),
        ("20250101/to/20250103", 3),
        ("20250101/to/20250110/by/3", 4),
        ("20250130/to/20250202", 4),
    ],
)
def test_count_dates(value, expected):
    assert count_dates(value) == expected
