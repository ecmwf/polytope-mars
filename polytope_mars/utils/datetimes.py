from datetime import datetime


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
