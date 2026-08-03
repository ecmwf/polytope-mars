import pytest

from polytope_mars.config import PolytopeMarsConfig
from polytope_mars.features.boundingbox import BoundingBox
from polytope_mars.utils.areas import normalise_lon


def _client_config():
    return PolytopeMarsConfig()


def _bbox(points, axes=None):
    feature_config = {"type": "boundingbox", "points": [list(p) for p in points]}
    if axes is not None:
        feature_config["axes"] = list(axes)
    return BoundingBox(feature_config, _client_config())


def _boxes(bbox):
    shapes = bbox.get_shapes()
    assert len(shapes) == 1
    union = shapes[0]
    return list(union._shapes), union


def _lon(box, axes):
    i = list(box.axes()).index("longitude")
    return box._lower_corner[i], box._upper_corner[i]


def _legacy_shapes(points, axes):
    """Reproduce the pre-change get_shapes() output exactly, to characterise
    that non-crossing boxes are unchanged (only longitude values may differ)."""
    from polytope_feature import shapes

    if len(points[0]) == 2:
        return [
            shapes.Union(
                ["latitude", "longitude"],
                shapes.Box(
                    ["latitude", "longitude"],
                    lower_corner=[points[0][axes.index("latitude")], points[0][axes.index("longitude")]],
                    upper_corner=[points[1][axes.index("latitude")], points[1][axes.index("longitude")]],
                ),
            )
        ]
    return [
        shapes.Union(
            [axes[0], axes[1], axes[2]],
            shapes.Box(
                [axes[0], axes[1], axes[2]],
                lower_corner=[points[0][0], points[0][1], points[0][2]],
                upper_corner=[points[1][0], points[1][1], points[1][2]],
            ),
        )
    ]


def _assert_box_equal(a, b):
    assert list(a.axes()) == list(b.axes())
    assert list(a._lower_corner) == list(b._lower_corner)
    assert list(a._upper_corner) == list(b._upper_corner)


class TestEquivalenceWithPrevious:
    """The request handed to polytope must be identical to before, except that
    a west>east box is normalised (and, if still crossing, split)."""

    @pytest.mark.parametrize(
        "points, axes",
        [
            ([[0, 10], [1, 20]], ["latitude", "longitude"]),  # ordinary 2D
            ([[-1, 170], [1, 190]], ["latitude", "longitude"]),  # antimeridian in [0,360)
            ([[-1, -0.1], [1, 0.1]], ["latitude", "longitude"]),  # signed prime-meridian, W<E
            ([[0.2, 0.1], [0.3, 0.2]], ["longitude", "latitude"]),  # 2D lonlat axis order
            ([[-1, 170, 1000], [1, 190, 500]], ["latitude", "longitude", "levelist"]),  # 3D
        ],
    )
    def test_non_crossing_identical_to_previous(self, points, axes):
        new = _bbox(points, axes=axes if axes != ["latitude", "longitude"] else None).get_shapes()
        old = _legacy_shapes(points, axes)
        assert len(new) == len(old) == 1
        new_boxes = list(new[0]._shapes)
        old_boxes = list(old[0]._shapes)
        assert len(new_boxes) == len(old_boxes) == 1
        assert list(new[0].axes()) == list(old[0].axes())
        _assert_box_equal(new_boxes[0], old_boxes[0])

    def test_normalised_box_differs_only_in_longitude(self):
        # W=359.9 > E=0.1 : normalised to signed, but everything else identical
        # to the legacy shape built from the *normalised* longitudes.
        new = _bbox([[-1, 359.9], [1, 0.1]]).get_shapes()
        legacy_norm = _legacy_shapes([[-1, -0.1], [1, 0.1]], ["latitude", "longitude"])
        new_box = list(new[0]._shapes)[0]
        old_box = list(legacy_norm[0]._shapes)[0]
        assert list(new_box.axes()) == list(old_box.axes())
        assert new_box._lower_corner == pytest.approx(old_box._lower_corner)
        assert new_box._upper_corner == pytest.approx(old_box._upper_corner)


class TestNormaliseLon:
    @pytest.mark.parametrize(
        "raw, expected",
        [(0, 0), (180, -180), (-180, -180), (359.9, -0.1), (360, 0), (190, -170), (10, 10)],
    )
    def test_normalise(self, raw, expected):
        assert normalise_lon(raw) == pytest.approx(expected)


class TestBoundingBoxMeridian:
    def test_ordinary_box_untouched(self):
        # W < E -> single box, values passed through unchanged
        boxes, _ = _boxes(_bbox([[0, 10], [1, 20]]))
        assert len(boxes) == 1
        assert _lon(boxes[0], ["latitude", "longitude"]) == (10, 20)

    def test_antimeridian_in_0_360_untouched(self):
        # 170 -> 190 stays within [0, 360) and W < E, so it is a single box
        boxes, _ = _boxes(_bbox([[-1, 170], [1, 190]]))
        assert len(boxes) == 1
        assert _lon(boxes[0], ["latitude", "longitude"]) == (170, 190)

    def test_prime_meridian_wrapped_normalised(self):
        # W=359.9 > E=0.1 -> normalise to signed, single box straddling 0
        boxes, _ = _boxes(_bbox([[-1, 359.9], [1, 0.1]]))
        assert len(boxes) == 1
        w, e = _lon(boxes[0], ["latitude", "longitude"])
        assert w == pytest.approx(-0.1)
        assert e == pytest.approx(0.1)

    def test_prime_meridian_signed_single_box(self):
        # Already signed and W < E -> untouched single box
        boxes, _ = _boxes(_bbox([[-1, -0.1], [1, 0.1]]))
        assert len(boxes) == 1
        assert _lon(boxes[0], ["latitude", "longitude"]) == (-0.1, 0.1)

    def test_antimeridian_splits_into_two_boxes(self):
        # W=179.9 > E=-179.9 and stays W' > E' after normalising -> split
        boxes, _ = _boxes(_bbox([[-1, 179.9], [1, -179.9]]))
        assert len(boxes) == 2
        lons = sorted(_lon(b, ["latitude", "longitude"]) for b in boxes)
        assert lons[0][0] == pytest.approx(-180)
        assert lons[0][1] == pytest.approx(-179.9)
        assert lons[1][0] == pytest.approx(179.9)
        assert lons[1][1] == pytest.approx(180)

    def test_split_preserves_latitude(self):
        boxes, _ = _boxes(_bbox([[-2, 179.9], [3, -179.9]]))
        assert len(boxes) == 2
        for b in boxes:
            lat_i = list(b.axes()).index("latitude")
            assert b._lower_corner[lat_i] == -2
            assert b._upper_corner[lat_i] == 3

    def test_split_preserves_levelist_3d(self):
        # 3-axis crossing box: levelist bound must be preserved on both boxes
        boxes, _ = _boxes(_bbox([[-1, 179.9, 1000], [1, -179.9, 500]], axes=["latitude", "longitude", "levelist"]))
        assert len(boxes) == 2
        for b in boxes:
            lev_i = list(b.axes()).index("levelist")
            assert b._lower_corner[lev_i] == 1000
            assert b._upper_corner[lev_i] == 500


class TestBoundingBoxValidation:
    def test_south_greater_than_north_raises(self):
        bbox = _bbox([[1, 10], [-1, 20]])
        with pytest.raises(ValueError):
            bbox.parse({"param": "164"}, {"type": "boundingbox", "points": [[1, 10], [-1, 20]]})

    def test_latitude_out_of_range_raises(self):
        bbox = _bbox([[-91, 10], [1, 20]])
        with pytest.raises(ValueError):
            bbox.parse({"param": "164"}, {"type": "boundingbox", "points": [[-91, 10], [1, 20]]})
