import re
from datetime import datetime

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


def convert_timestamp(self, timestamp):
        # Ensure the input is a string
        timestamp = str(timestamp)

        # Pad the timestamp with leading zeros if necessary
        timestamp = timestamp.zfill(4)

        # Insert colons to format as HH:MM:SS
        formatted_timestamp = f"{timestamp[:2]}:{timestamp[2:]}:00"

        return formatted_timestamp

    def find_step_intervals(self, step_start: str, step_end: str, step_freq: str):
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