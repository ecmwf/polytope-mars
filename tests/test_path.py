import json

import pytest

from polytope_mars.api import PolytopeMars

# If using a local FDB need to set FDB_HOME and ECCODES_DEFINITIO_PATH


class TestFeatureFactory:
    def setup_method(self):
        self.request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": "20231205",
            "time": "00:00:00",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "165/166",
            "number": "1",
            "step": "0",
            "feature": {
                "type": "path",
                "points": [[0, 0], [1, 1], [2, 2]],
                "radius": 1,
            },
        }

        self.options = {
            "values": {
                "mapper": {
                    "type": "octahedral",
                    "resolution": 1280,
                    "axes": ["latitude", "longitude"],
                }
            },
            "date": {"merge": {"with": "time", "linkers": ["T", "00"]}},
            "step": {"type_change": "int"},
        }

        self.config = {
            "class": "od",
            "expver": "0001",
            "levtype": "sfc",
            "type": "pf",
        }  # noqa: E501

    @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox_invalid(self):
        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract("invalid")

        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract({"hello": "world"})  # noqa: E501

        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract(json.dumps({"hello": "world"}))

        # 'step' is invalid in the request
        self.request["step"] = "0"
        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract(self.request)

        self.request["levellist"] = "0"
        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract(self.request)

    @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox_valid(self):
        coverage = PolytopeMars(self.config, self.options).extract(self.request)  # noqa: E501
        print(coverage)
