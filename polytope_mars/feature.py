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

    def validate(self, request):
        incompatible_keys = self.incompatible_keys()
        for key in incompatible_keys:
            if key in request:
                raise KeyError(
                    f"Request contains a '{key}' keyword which is not compatible with feature {self.name()}"  # noqa: E501
                )
