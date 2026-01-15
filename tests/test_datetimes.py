from polytope_mars.utils.datetimes import from_range_to_list_date


def test_from_range_to_list_date_spans_months():
    date_range = "20220130/to/20220202"
    expected = "20220130/20220131/20220201/20220202"
    assert from_range_to_list_date(date_range) == expected
