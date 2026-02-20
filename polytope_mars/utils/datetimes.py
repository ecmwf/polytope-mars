import re
from datetime import datetime, timedelta

import pandas as pd


def days_between_dates(date1, date2):
    """
    Calculate the number of days between two dates in the format YYYYMMDD.

    :param date1: The first date in the format YYYYMMDD
    :param date2: The second date in the format YYYYMMDD
    :return: The number of days between the two dates
    """
    date_format = "%Y%m%d"
    d1 = datetime.strptime(date1, date_format)
    d2 = datetime.strptime(date2, date_format)
    delta = d2 - d1
    return abs(delta.days)


def hours_between_times(time1, time2):
    """
    Calculate the number of hours between two times in the format HHMM.

    :param time1: The first time in the format HHMM
    :param time2: The second time in the format HHMM
    :return: The number of hours between the two times
    """
    time_format = "%H%M"
    t1 = datetime.strptime(time1, time_format)
    t2 = datetime.strptime(time2, time_format)
    delta = t2 - t1
    return abs(delta.total_seconds() / 3600)


def convert_timestamp(timestamp):
    # Ensure the input is a string
    timestamp = str(timestamp)

    # Pad the timestamp with leading zeros if necessary
    timestamp = timestamp.zfill(4)

    # Insert colons to format as HH:MM:SS
    formatted_timestamp = f"{timestamp[:2]}:{timestamp[2:]}:00"

    return formatted_timestamp


def find_step_intervals(step_start: str, step_end: str, step_freq: str):
    def format_subhourly_step_to_mars(step: pd.Timedelta):
        total_hours = int(step.total_seconds() // 3600)
        minutes = int((step.total_seconds() % 3600) // 60)
        return f"{total_hours}h{minutes}m"

    def format_step_str_to_pd(step: str):
        return re.sub(r"m$", "min", step)

    # if we have normal digit steps only, treat like before
    if step_start.isdigit() and step_end.isdigit() and step_freq.isdigit():
        return list(range(int(step_start), int(step_end), int(step_freq)))

    step_start_pd_format = format_step_str_to_pd(step_start)
    step_end_pd_format = format_step_str_to_pd(step_end)
    step_freq_pd_format = format_step_str_to_pd(step_freq)

    step_values = pd.timedelta_range(start=step_start_pd_format, end=step_end_pd_format, freq=step_freq_pd_format)
    return [format_subhourly_step_to_mars(val) for val in step_values]


def from_range_to_list_num(num_range):
    """
    Convert a range in the format integer/to/integer to a list of numbers seperated by /.

    :param range: A string representing the range in the format integer/to/integer
    :return: A list of dates in the format integer/integer/integer
    """
    if "/to/" in num_range:
        start, end = num_range.split("/to/")
        start = int(start)
        end = int(end)
        if start > end:
            raise ValueError("Start of range must be less than or equal to end of range.")
        return [str(i) for i in range(start, end + 1)]
    else:
        return num_range


def from_range_to_list_date(date_range):
    """
    Convert a date range in the format YYYYMMDD/to/YYYYMMDD to a list of dates.

    :param date_range: A string representing the date range in the format YYYYMMDD/to/YYYYMMDD
    :return: A list of dates in the format YYYYMMDD/YYYYMMDD
    """
    if "/to/" in date_range:
        start_date, end_date = date_range.split("/to/")
        start_date = datetime.strptime(start_date, "%Y%m%d")
        end_date = datetime.strptime(end_date, "%Y%m%d")
        date_list = []
        current_date = start_date
        while current_date <= end_date:
            date_list.append(current_date.strftime("%Y%m%d"))
            current_date += timedelta(days=1)
        if not date_list:
            raise ValueError("The date range does not include any valid dates.")
        if len(date_list) == 1:
            return date_list[0]
        date_list = "/".join(date_list)
    else:
        date_list = date_range
    return date_list


def count_steps(step_string: str) -> int:
    """
    Count the number of steps in a MARS step string.

    Supports:
    - List format: "0/1/2" -> 3 steps
    - List format with time units: "1h/6h" -> 2 steps
    - Range format: "0/to/10/by/2" -> 6 steps (0, 2, 4, 6, 8, 10)
    - Sub-hourly range: "1h/to/6h/by/30m" -> 11 steps
    - Seconds: "1h/to/1h30m/by/20s" -> 91 steps
    - Days: "1d/to/3d" -> 3 steps (1d, 2d, 3d)
    - Default increment is 1h for ranges without 'by'

    Args:
        step_string: String in MARS step format

    Returns:
        Number of steps contained in the string

    Examples:
        >>> count_steps("0/1/2")
        3
        >>> count_steps("0/to/10/by/2")
        6
        >>> count_steps("1h/6h")
        2
        >>> count_steps("1h/to/6h/by/30m")
        11
        >>> count_steps("1h/to/1h30m/by/20s")
        91
        >>> count_steps("1d/to/3d")
        3
    """
    parts = step_string.split("/")

    # Check if this is a range (contains 'to')
    if "to" in parts:
        to_index = parts.index("to")
        start_step = parts[to_index - 1]
        end_step = parts[to_index + 1]

        # Check if 'by' is specified
        if "by" in parts:
            by_index = parts.index("by")
            by_step = parts[by_index + 1]
        else:
            # Default to 1h
            by_step = "1h"

        return _count_range_steps(start_step, end_step, by_step)
    else:
        # List format - just count the elements
        return len(parts)


def _count_range_steps(start_step: str, end_step: str, by_step: str = "1h") -> int:
    """
    Count steps in a range from start_step to end_step with increment by_step.

    Args:
        start_step: Start value (e.g., "0", "1h", "30m", "1d")
        end_step: End value (e.g., "10", "6h", "2h", "3d")
        by_step: Increment value (default: "1h")

    Returns:
        Number of steps in the range (inclusive)
    """

    def _parse_step_to_timedelta(step: str) -> pd.Timedelta:
        """Convert step string to pandas Timedelta.

        Supports formats:
        - Pure numbers: "5" -> 5 hours
        - Hours: "1h", "24h"
        - Minutes: "30m", "90m"
        - Seconds: "45s", "3600s"
        - Days: "1d", "7d"
        - Combined: "1h30m", "1d12h"
        """
        # Check if it's a pure number (treat as hours)
        if step.isdigit():
            return pd.Timedelta(hours=int(step))

        # Parse format with time units
        # Replace single-letter suffixes with pandas-compatible ones:
        # 'd' -> 'D' (days)
        # 'h' -> 'h' (hours - already compatible)
        # 'm' -> 'min' (minutes - 'm' means months in pandas)
        # 's' -> 's' (seconds - already compatible)

        step_pd = step
        # Replace 'm' with 'min' but only when it's a time unit (not part of 'min')
        step_pd = re.sub(r"(\d+)m(?!in)", r"\1min", step_pd)
        # Replace 'd' with 'D' for days
        step_pd = re.sub(r"(\d+)d", r"\1D", step_pd)

        return pd.Timedelta(step_pd)

    # If all are pure digits, handle as simple numeric range
    if start_step.isdigit() and end_step.isdigit() and by_step.isdigit():
        start = int(start_step)
        end = int(end_step)
        by = int(by_step)
        # Use range logic: range(start, end+1, by) to get inclusive count
        return len(range(start, end + 1, by))

    # Handle sub-hourly/mixed format
    start_td = _parse_step_to_timedelta(start_step)
    end_td = _parse_step_to_timedelta(end_step)
    by_td = _parse_step_to_timedelta(by_step)

    # Generate the range and count
    step_range = pd.timedelta_range(start=start_td, end=end_td, freq=by_td)
    return len(step_range)
