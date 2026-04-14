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

    def split_request(self):
        """
        Determines if the request should be split based on the feature configuration.
        Only features that set ``field_area`` and ``max_area`` (Polygon, BoundingBox)
        can trigger a split.  All other features return False.
        """
        if hasattr(self, "field_area") and hasattr(self, "max_area"):
            if self.field_area > self.max_area:
                return True
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
