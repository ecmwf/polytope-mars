"""Comprehensive tests for polytope_mars.utils.areas — all public functions."""

import math

import pytest
from shapely.geometry import Polygon

from polytope_mars.utils.areas import (
    field_area,
    get_boundingbox_area,
    get_circle_area,
    get_circle_area_from_coords,
    get_polygon_area,
    haversine_distance,
    request_cost,
    split_polygon,
)


# ---------------------------------------------------------------------------
# haversine_distance
# ---------------------------------------------------------------------------
class TestHaversineDistance:
    """Great-circle distance between two points (km)."""

    def test_same_point_returns_zero(self):
        assert haversine_distance(0, 0, 0, 0) == 0.0

    def test_same_point_nonzero_coords(self):
        assert haversine_distance(48.8566, 2.3522, 48.8566, 2.3522) == 0.0

    def test_london_to_paris(self):
        # London (51.5074, -0.1278) -> Paris (48.8566, 2.3522) ≈ 344 km
        d = haversine_distance(51.5074, -0.1278, 48.8566, 2.3522)
        assert 340 < d < 350, f"Expected ~344 km, got {d}"

    def test_new_york_to_los_angeles(self):
        # NY (40.7128, -74.0060) -> LA (34.0522, -118.2437) ≈ 3944 km
        d = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3930 < d < 3960, f"Expected ~3944 km, got {d}"

    def test_antipodal_points(self):
        # North pole to south pole ≈ pi * R ≈ 20015 km
        d = haversine_distance(90, 0, -90, 0)
        assert 20010 < d < 20020, f"Expected ~20015 km, got {d}"

    def test_equator_quarter_circumference(self):
        # 0° to 90° longitude along equator ≈ pi/2 * R ≈ 10008 km
        d = haversine_distance(0, 0, 0, 90)
        assert 10005 < d < 10012

    def test_poles_same_longitude(self):
        d = haversine_distance(90, 45, -90, 45)
        assert 20010 < d < 20020

    def test_crossing_dateline(self):
        # From lon=179 to lon=-179 at equator → should be ~222 km (2° apart)
        d = haversine_distance(0, 179, 0, -179)
        assert 220 < d < 225

    def test_symmetry(self):
        d1 = haversine_distance(10, 20, 30, 40)
        d2 = haversine_distance(30, 40, 10, 20)
        assert math.isclose(d1, d2, rel_tol=1e-10)

    def test_positive_result(self):
        d = haversine_distance(-33.87, 151.21, 35.68, 139.69)
        assert d > 0


# ---------------------------------------------------------------------------
# get_circle_area
# ---------------------------------------------------------------------------
class TestGetCircleArea:
    """Area of a flat circle (pi * r^2)."""

    def test_zero_radius(self):
        assert get_circle_area(0) == 0.0

    def test_unit_radius(self):
        assert math.isclose(get_circle_area(1), math.pi)

    def test_radius_100(self):
        expected = math.pi * 100**2  # 31415.926...
        assert math.isclose(get_circle_area(100), expected)

    def test_large_radius(self):
        assert math.isclose(get_circle_area(1000), math.pi * 1e6)


# ---------------------------------------------------------------------------
# get_circle_area_from_coords
# ---------------------------------------------------------------------------
class TestGetCircleAreaFromCoords:
    """Circle area defined by center + perimeter point."""

    def test_same_point_returns_zero(self):
        assert get_circle_area_from_coords(0, 0, 0, 0) == 0.0

    def test_matches_manual_calculation(self):
        """Area from coords should equal pi * haversine_distance^2."""
        lat_c, lon_c = 51.5074, -0.1278  # London
        lat_p, lon_p = 48.8566, 2.3522  # Paris
        r = haversine_distance(lat_c, lon_c, lat_p, lon_p)
        expected = get_circle_area(r)
        actual = get_circle_area_from_coords(lat_c, lon_c, lat_p, lon_p)
        assert math.isclose(actual, expected, rel_tol=1e-10)

    def test_one_degree_offset_at_equator(self):
        # 1° latitude ≈ 111.2 km → area ≈ pi * 111.2^2 ≈ 38 858 km²
        area = get_circle_area_from_coords(0, 0, 1, 0)
        assert 38000 < area < 39500


# ---------------------------------------------------------------------------
# split_polygon
# ---------------------------------------------------------------------------
class TestSplitPolygon:
    """Split polygon along 90° meridians."""

    def test_polygon_within_single_band(self):
        # Entirely within 0-89° — no split needed
        poly = Polygon([(10, 10), (10, 80), (80, 80), (80, 10)])
        pieces = split_polygon(poly)
        assert len(pieces) == 1

    def test_polygon_crossing_zero_meridian(self):
        # -45 to 45 → crosses 0° meridian → 2 pieces
        poly = Polygon([(-45, -10), (-45, 10), (45, 10), (45, -10)])
        pieces = split_polygon(poly)
        assert len(pieces) == 2

    def test_polygon_crossing_two_meridians(self):
        # -100 to 100 → crosses -90 and 0 and 90 → up to 3 pieces
        poly = Polygon([(-100, -10), (-100, 10), (100, 10), (100, -10)])
        pieces = split_polygon(poly)
        assert len(pieces) >= 3

    def test_narrow_polygon_no_crossing(self):
        # 1 to 2 longitude — entirely within one band
        poly = Polygon([(1, 0), (1, 1), (2, 1), (2, 0)])
        pieces = split_polygon(poly)
        assert len(pieces) == 1

    def test_polygon_exactly_on_boundary(self):
        # 0 to 90 — boundary aligns with split line
        poly = Polygon([(0, 0), (0, 10), (90, 10), (90, 0)])
        pieces = split_polygon(poly)
        # Could be 1 or 2 depending on how shapely handles exact boundary
        assert len(pieces) >= 1

    def test_all_pieces_are_valid_polygons(self):
        poly = Polygon([(-100, -10), (-100, 10), (100, 10), (100, -10)])
        pieces = split_polygon(poly)
        for piece in pieces:
            assert piece.geom_type in ("Polygon", "MultiPolygon")
            assert not piece.is_empty


# ---------------------------------------------------------------------------
# get_polygon_area
# ---------------------------------------------------------------------------
class TestGetPolygonArea:
    """Geodesic polygon area in km²."""

    def test_small_square_at_equator(self):
        # 1°×1° at equator ≈ 111.2 km × 111.2 km ≈ ~12 364 km²
        points = [(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]  # (lat, lon)
        area = get_polygon_area(points)
        assert 12000 < area < 12500, f"Expected ~12300 km², got {area}"

    def test_area_is_positive(self):
        points = [(10, 10), (10, 11), (11, 11), (11, 10), (10, 10)]
        area = get_polygon_area(points)
        assert area > 0

    def test_larger_polygon(self):
        # 10°×10° at equator ≈ 1.2M km²
        points = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]
        area = get_polygon_area(points)
        assert 1_100_000 < area < 1_300_000

    def test_polygon_crossing_meridian(self):
        # Polygon that spans from lon=-1 to lon=1
        points = [(0, -1), (0, 1), (1, 1), (1, -1), (0, -1)]
        area = get_polygon_area(points)
        assert area > 0


# ---------------------------------------------------------------------------
# get_boundingbox_area
# ---------------------------------------------------------------------------
class TestGetBoundingboxArea:
    """Bounding box area from two corner points."""

    def test_unit_box_at_equator(self):
        # points format: [[lon1, lat1], [lon2, lat2]]  (min, max)
        points = [[0.1, 0], [1, 1]]  # offset min_lon to avoid 0+0 edge
        area = get_boundingbox_area(points)
        assert area > 0

    def test_known_box(self):
        # 1°×1° box at equator
        points = [[0.1, 0], [1, 1]]
        area = get_boundingbox_area(points)
        assert 10000 < area < 13000, f"Expected ~12300 km², got {area}"

    def test_symmetric_lon_triggers_offset(self):
        # min_lon + max_lon == 0 triggers the 0.1 offset in the code
        points = [[-1, 0], [1, 1]]
        area = get_boundingbox_area(points)
        assert area > 0

    def test_large_box(self):
        points = [[0.1, 0], [10, 10]]
        area = get_boundingbox_area(points)
        assert area > 100_000


# ---------------------------------------------------------------------------
# field_area
# ---------------------------------------------------------------------------
class TestFieldArea:
    """Multiply shape area by the number of fields in a request."""

    def _base_request(self, **overrides):
        req = {"param": "167"}
        req.update(overrides)
        return req

    # --- basic multipliers ------------------------------------------------

    def test_single_param_single_step(self):
        """1 param, no step/number → area * 1."""
        result = field_area(self._base_request(), area=100)
        assert result == 100

    def test_multiple_params(self):
        """Two params → area * 2."""
        result = field_area(self._base_request(param="167/165"), area=100)
        assert result == 200

    def test_three_params(self):
        result = field_area(self._base_request(param="167/165/166"), area=50)
        assert result == 150

    # --- step -------------------------------------------------------------

    def test_step_list(self):
        result = field_area(self._base_request(step="0/1/2"), area=10)
        assert result == 30  # 3 steps * 10

    def test_step_range(self):
        # "0/to/10/by/2" → 6 steps (0,2,4,6,8,10)
        result = field_area(self._base_request(step="0/to/10/by/2"), area=10)
        assert result == 60

    def test_step_range_default_increment(self):
        # "0/to/3" with default 1h increment → 4 steps
        result = field_area(self._base_request(step="0/to/3"), area=10)
        assert result == 40

    # --- number -----------------------------------------------------------

    def test_number_list(self):
        result = field_area(self._base_request(number="1/2/3"), area=10)
        assert result == 30

    def test_number_range(self):
        # "1/to/5" → 5 numbers
        result = field_area(self._base_request(number="1/to/5"), area=10)
        assert result == 50

    # --- levelist ---------------------------------------------------------

    def test_levelist_list(self):
        result = field_area(self._base_request(levelist="500/700/850"), area=10)
        assert result == 30

    def test_levelist_range(self):
        # "1/to/3" → 3 levels
        result = field_area(self._base_request(levelist="1/to/3"), area=10)
        assert result == 30

    # --- date -------------------------------------------------------------

    def test_single_date(self):
        result = field_area(self._base_request(date="20240101"), area=10)
        assert result == 10  # single date → date_len = 1

    def test_date_list(self):
        result = field_area(self._base_request(date="20240101/20240102"), area=10)
        assert result == 20

    def test_date_range(self):
        # "20240101/to/20240103" → 2 days apart
        result = field_area(self._base_request(date="20240101/to/20240103"), area=10)
        assert result == 20  # days_between_dates returns 2

    def test_date_range_same_day(self):
        # Same day → days_between = 0 → clamped to 1
        result = field_area(self._base_request(date="20240101/to/20240101"), area=10)
        assert result == 10

    # --- time -------------------------------------------------------------

    def test_single_time(self):
        result = field_area(self._base_request(time="0000"), area=10)
        assert result == 10

    def test_time_list(self):
        result = field_area(self._base_request(time="0000/0600/1200"), area=10)
        assert result == 30

    def test_time_range(self):
        # "0000/to/1200" → 12 hours
        result = field_area(self._base_request(time="0000/to/1200"), area=10)
        assert result == 120

    # --- month ------------------------------------------------------------

    def test_month_list(self):
        result = field_area(self._base_request(month="1/2/3"), area=10)
        assert result == 30

    def test_month_range(self):
        # "1/to/6" → 6 months
        result = field_area(self._base_request(month="1/to/6"), area=10)
        assert result == 60

    # --- year -------------------------------------------------------------

    def test_year_list(self):
        result = field_area(self._base_request(year="2020/2021"), area=10)
        assert result == 20

    def test_year_range(self):
        # "2020/to/2024" → 5 years
        result = field_area(self._base_request(year="2020/to/2024"), area=10)
        assert result == 50

    # --- feature range ----------------------------------------------------

    def test_feature_range_start_end(self):
        req = self._base_request(feature={"range": {"start": 0, "end": 10}})
        # step_len = 10 - 0 + 1 = 11
        result = field_area(req, area=10)
        assert result == 110

    def test_feature_range_start_only(self):
        req = self._base_request(feature={"range": {"start": 5}})
        result = field_area(req, area=10)
        assert result == 10  # step_len = 1

    def test_feature_range_end_only(self):
        req = self._base_request(feature={"range": {"end": 5}})
        result = field_area(req, area=10)
        assert result == 10  # step_len = 1

    def test_step_overrides_feature_range(self):
        """When 'step' is present it overrides the feature range."""
        req = self._base_request(
            feature={"range": {"start": 0, "end": 10}},
            step="0/1/2",
        )
        result = field_area(req, area=10)
        assert result == 30  # step list = 3

    # --- missing param → ValueError ---------------------------------------

    def test_missing_param_raises(self):
        with pytest.raises(ValueError, match="param"):
            field_area({}, area=10)

    # --- compound multipliers ---------------------------------------------

    def test_all_multipliers_combined(self):
        req = self._base_request(
            param="167/165",  # 2
            step="0/1/2",  # 3
            number="1/2",  # 2
            date="20240101/20240102",  # 2
            time="0000/1200",  # 2
            month="1/2",  # 2
            year="2020/2021",  # 2
            levelist="500/700",  # 2
        )
        result = field_area(req, area=10)
        expected = 2 * 3 * 2 * 2 * 2 * 2 * 2 * 2 * 10
        assert result == expected


# ---------------------------------------------------------------------------
# request_cost
# ---------------------------------------------------------------------------
class TestRequestCost:
    """End-to-end cost estimation for different feature types."""

    def test_boundingbox_request(self):
        req = {
            "param": "167",
            "feature": {
                "type": "boundingbox",
                "points": [[0.1, 0], [1, 1]],
            },
        }
        cost = request_cost(req)
        assert cost > 0

    def test_polygon_request(self):
        req = {
            "param": "167",
            "feature": {
                "type": "polygon",
                "shape": [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]],
            },
        }
        cost = request_cost(req)
        assert cost > 0

    def test_timeseries_uses_len_points(self):
        req = {
            "param": "167",
            "feature": {
                "type": "timeseries",
                "points": [[10, 20], [30, 40]],
            },
        }
        cost = request_cost(req)
        # area = len(points) = 2, param=1, everything else =1 → 2
        assert cost == 2

    def test_dataset_key_doubles_cost(self):
        req = {
            "param": "167",
            "feature": {
                "type": "timeseries",
                "points": [[10, 20]],
            },
        }
        base = request_cost(req)
        req["dataset"] = "reanalysis"
        doubled = request_cost(req)
        assert doubled == base * 2

    def test_cost_scales_with_params(self):
        req = {
            "param": "167",
            "feature": {
                "type": "timeseries",
                "points": [[10, 20]],
            },
        }
        cost1 = request_cost(req)
        req["param"] = "167/165"
        cost2 = request_cost(req)
        assert cost2 == cost1 * 2

    def test_cost_scales_with_steps(self):
        req = {
            "param": "167",
            "step": "0/1/2",
            "feature": {
                "type": "timeseries",
                "points": [[10, 20]],
            },
        }
        cost = request_cost(req)
        # area=1, param=1, step=3 → 3
        assert cost == 3
