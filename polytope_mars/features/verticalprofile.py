from ..feature import Feature
from ..utils.labels import tagged_point_union, validate_labels


class VerticalProfile(Feature):
    def __init__(self, feature_config, client_config):
        assert feature_config.pop("type") == "verticalprofile"
        # self.start_step = config.pop("start", None)
        # self.end_step = config.pop("end", None)
        if "axes" in feature_config:
            self.axes = feature_config.pop("axes", [])

            if not isinstance(self.axes, list):
                self.axes = ["latitude", "longitude"]
            if self.axes == ["step"] or self.axes == ["date"]:
                self.axes = ["latitude", "longitude"]
        else:
            self.axes = ["latitude", "longitude"]

        self.points = feature_config.pop("points", [])
        self.labels = feature_config.pop("labels", None)

        if "range" in feature_config:
            feature_config.pop("range")

        assert len(feature_config) == 0, f"Unexpected keys in config: {feature_config.keys()}"

    def get_shapes(self):
        return [tagged_point_union([self.axes[0], self.axes[1]], self.points, self.labels)]

    def incompatible_keys(self):
        return []

    def coverage_type(self):
        return "VerticalProfile"

    def name(self):
        return "Vertical Profile"

    def uncompressed_axes(self):
        # Workaround until polytope keeps tags per value: a compressed longitude node can hold the
        # cells of several requested points with one combined tag set, so labels can't be assigned
        # per cell. With longitude uncompressed each cell has its own node and tags.
        return ["longitude"]

    def required_keys(self):
        return ["type", "points"]

    def required_axes(self):
        return []

    def parse(self, request, feature_config):
        if "axes" not in feature_config:
            feature_config["axes"] = "levelist"

        if isinstance(feature_config["axes"], list):
            if "levelist" in feature_config["axes"]:
                level_axis = "levelist"
                feature_config["axes"].remove("levelist")
            else:
                level_axis = "levelist"
        else:
            level_axis = feature_config["axes"]
        # if "axes" in feature_config and feature_config["axes"] != "levelist":
        #    raise ValueError("Vertical profile axes must be levelist")
        if len(feature_config["points"][0]) != 2:
            raise ValueError("Vertical Profile must have only two values in points")  # noqa: E501
        validate_labels(self.labels, len(feature_config["points"]), "Vertical profile", "points")
        if "axes" in feature_config:
            if level_axis in request and "range" in feature_config:
                raise ValueError("Vertical profile axes is overspecified in request")  # noqa: E501
            if level_axis not in request and "range" not in feature_config:  # noqa: E501
                raise ValueError("Vertical profile axes is underspecified in request")  # noqa: E501
        if "range" in feature_config:
            if isinstance(feature_config["range"], dict):
                level_range = f"{feature_config['range']['start']}/to/{feature_config['range']['end']}"
                request[level_axis] = level_range  # noqa: E501
                if "interval" in feature_config["range"]:
                    request[level_axis] += f"/by/{feature_config['range']['interval']}"

        return request
