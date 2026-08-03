import logging

from polytope_feature import shapes

from ..feature import Feature
from ..utils.areas import field_area, get_boundingbox_area, normalise_lon


class BoundingBox(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "boundingbox"
        if "points" not in feature_config:
            raise KeyError("Bounding box must have points in feature")
        self.points = feature_config.pop("points", [])
        if "axes" not in feature_config:
            feature_config["axes"] = ["latitude", "longitude"]
        self.axes = feature_config.pop("axes", [])
        self.max_area = client_config.polygonrules.max_area
        self.field_area = 0

        if "axes" in feature_config:
            raise ValueError("Bounding box does not have axes in feature, did you mean axes?")  # noqa: E501

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

        self.area_bb = get_boundingbox_area(self.points)
        logging.info(f"Area of bounding box: {self.area_bb} km\u00b2")

    def get_shapes(self):
        # Bounding box is a Union of one or more axis-aligned Boxes.
        # The longitude axis is cyclic ([0, 360)); a single Box collapses to an
        # axis-aligned interval [min(lon), max(lon)] and loses sweep direction.
        # We therefore normalise/split lazily, only when the west edge is
        # numerically greater than the east edge (see bbox_convention.md):
        #   * W < E            -> pass through untouched, single Box
        #   * W > E, W' < E'   -> normalise to signed lons, single Box
        #   * W > E, W' > E'   -> antimeridian crossing, Union of two Boxes
        # where W'/E' are the signed-normalised longitudes. This is agnostic to
        # the number of axes (2D lat/lon or 3D lat/lon/levelist): the split only
        # touches the longitude component, everything else rides along unchanged.
        # Preserve the exact shape ordering the previous implementation used so
        # that non-crossing boxes are byte-for-byte identical to before:
        #   * 2D: shape axes are always ["latitude", "longitude"], corners
        #         reordered by name.
        #   * 3D: shape axes are self.axes, corners taken positionally.
        # The only new behaviour is the longitude split below.
        if len(self.axes) == 2:
            shape_axes = ["latitude", "longitude"]
            lower = [self.points[0][self.axes.index(a)] for a in shape_axes]
            upper = [self.points[1][self.axes.index(a)] for a in shape_axes]
        else:
            shape_axes = list(self.axes)
            lower = list(self.points[0])
            upper = list(self.points[1])

        lon_idx = shape_axes.index("longitude")
        w = lower[lon_idx]
        e = upper[lon_idx]

        def make_box(lon_lower, lon_upper):
            lc = list(lower)
            uc = list(upper)
            lc[lon_idx] = lon_lower
            uc[lon_idx] = lon_upper
            return shapes.Box(shape_axes, lower_corner=lc, upper_corner=uc)

        if w < e:
            # Already sweeping west -> east; the AABB is the intended region.
            boxes = [make_box(w, e)]
        else:
            w_signed = normalise_lon(w)
            e_signed = normalise_lon(e)
            if w_signed < e_signed:
                # Meridian crossing resolved by signed normalisation.
                boxes = [make_box(w_signed, e_signed)]
            else:
                # Antimeridian crossing: split at +/-180 into two Boxes.
                boxes = [make_box(w_signed, 180), make_box(-180, e_signed)]

        return [shapes.Union(shape_axes, *boxes)]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "MultiPoint"

    def name(self):
        return "Bounding Box"

    def required_keys(self):
        return ["type", "points"]

    def required_axes(self):
        return ["latitude", "longitude"]

    def parse(self, request, feature_config):
        if feature_config["type"] != "boundingbox":
            raise ValueError("Feature type must be boundingbox")
        if "axes" in feature_config:
            if len(feature_config["axes"]) < 2 or len(feature_config["axes"]) > 3:
                raise ValueError(
                    "Bounding Box axes must contain 2 or 3 values, latitude, longitude, and optionally levelist"
                )
            if "step" in feature_config["axes"]:
                raise ValueError(
                    "Bounding box axes must be latitude and longitude, step can be requested in main body of request"
                )
            if "latitude" not in feature_config["axes"] or "longitude" not in feature_config["axes"]:
                raise ValueError("Bounding Box axes must contain both latitude and longitude")
            if len(feature_config["axes"]) > 3:
                raise ValueError(
                    "Bounding Box axes must contain at most 3 values, latitude, longitude, and levelist"
                )  # noqa: E501

        self.field_area = field_area(request, self.area_bb)
        # if self.field_area > self.max_area:
        #    raise ValueError(
        #        f"The total request size is too large, area of request shape {self.area_bb} * total number of fields = {field_area(request, self.area_bb)} km\u00b2, must be below {self.max_area} km\u00b2 for total size request. "  # noqa: E501
        #    )

        if len(feature_config["points"]) != 2:
            raise ValueError("Bounding box must have only two points in points")  # noqa: E501

        # Latitude must be ordered south <= north and within [-90, 90].
        # Longitudes are intentionally not range/order checked here: any value
        # maps onto the cyclic longitude axis, and west > east is a valid
        # meridian/antimeridian crossing handled in get_shapes().
        lat_idx = self.axes.index("latitude")
        s = self.points[0][lat_idx]
        n = self.points[1][lat_idx]
        if not (-90 <= s <= 90) or not (-90 <= n <= 90):
            raise ValueError(f"Bounding box latitudes must be in [-90, 90] (got south={s}, north={n})")  # noqa: E501
        if s > n:
            raise ValueError(f"Bounding box requires south ({s}) <= north ({n})")  # noqa: E501
        if "axis" in feature_config:
            raise ValueError("Bounding box does not have axis in feature, did you mean axes?")  # noqa: E501
        if "axes" not in feature_config:
            for point in feature_config["points"]:
                if len(point) != 2:
                    raise ValueError(
                        "For Bounding Box each point must have only two values unless axes is specified"  # noqa: E501
                    )
        else:
            for point in feature_config["points"]:
                if len(point) != len(feature_config["axes"]):
                    raise ValueError("Bounding Box points must have the same number of values as axes")  # noqa: E501
            if "axes" in feature_config:
                if ("levelist" in feature_config["axes"]) and ("levelist" in request):  # noqa: E501
                    raise ValueError("Bounding Box axes is overspecified in request")  # noqa: E501

        return request
