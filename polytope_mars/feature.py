from abc import ABC, abstractmethod
from typing import List

from polytope_feature import shapes


class Feature(ABC):
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def get_shapes(self) -> List[shapes.Shape]:
        pass

    @abstractmethod
    def incompatible_keys(self) -> List[str]:
        pass

    @abstractmethod
    def coverage_type(self):
        pass

    @abstractmethod
    def parse(self, request, feature_config):
        pass

    @abstractmethod
    def required_keys(self):
        pass

    @abstractmethod
    def required_axes(self):
        pass

    def _pop_grid_option(self, feature_config, axes):
        """Pop and validate an optional "grid" keyword from a feature config, eg.:
            {"type": "octahedral", "resolution": 1280, "method": "linear"}
        Stores it on `self.grid` (None if absent) for `interpolation_options()` to
        pick up. Only supported for 2D (latitude/longitude) shapes.
        """
        grid = feature_config.pop("grid", None)
        if grid is not None:
            if list(axes) != ["latitude", "longitude"]:
                raise ValueError("Grid interpolation is only supported for 2D (latitude/longitude) shapes")
            if "type" not in grid or "resolution" not in grid:
                raise ValueError(
                    "'grid' must specify a 'type' and 'resolution', "
                    "eg. {'type': 'octahedral', 'resolution': 1280}"
                )
        self.grid = grid
        return grid

    def interpolation_options(self):
        """Return a dict suitable for polytope_feature's "interpolation" option
        (`{"method": ..., "out_grid": {...}, "in_grid": {...}}`), or `None` if this
        request doesn't use grid interpolation. Driven by `self.grid`, as set by
        `_pop_grid_option()` - features that support a "grid" keyword call that
        from their `__init__`; others keep the default `None` here.
        """
        grid = getattr(self, "grid", None)
        if grid is None:
            return None
        return {
            "method": grid.get("method", "linear"),
            "out_grid": {"type": grid["type"], "resolution": grid["resolution"]},
        }

    def split_request(self):
        """
        Determines if the request should be split based on the feature configuration.
        This method can be overridden by subclasses to implement specific splitting logic.
        """
        if self.name() == "Polygon" or self.name() == "BoundingBox":
            if self.field_area > self.max_area:
                # If the area of the request exceeds the maximum allowed area, we split the request.
                return True
        # Otherwise, we do not split the request.
        return False

    def validate(self, request, feature_config):
        incompatible_keys = self.incompatible_keys()
        for key in incompatible_keys:
            if key in request:
                raise KeyError(
                    f"Request contains a '{key}' keyword which is not compatible with feature {self.name()}"  # noqa: E501
                )
        required_keys = self.required_keys()
        for key in required_keys:
            if key not in request and key not in feature_config:
                raise KeyError(f"Missing required key {key} not in request")

        required_axes = self.required_axes()
        for key in required_axes:
            if "axes" in feature_config:
                if key not in feature_config["axes"]:
                    raise KeyError(f"Missing required axis {key} not in request")
