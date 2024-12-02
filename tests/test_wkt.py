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
                "type": "wkt",
                "shape": "POLYGON ((30 10, 40 40, 20 40, 10 20, 30 10))",
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
    def test_wkt_invalid(self):
        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract("invalid")

        with pytest.raises(TypeError):
            PolytopeMars(self.options, self.config).extract({"hello": "world"})

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
    def test_wkt_valid(self):
        coverage = PolytopeMars(self.config, self.options).extract(self.request)  # noqa: E501
        print(coverage)

    # def test_wkt_multi_valid(self):
    #    self.request['feature']['shape'] = "MULTIPOLYGON (((40 40, 20 45, 45 30, 40 40)),((20 35, 10 30, 10 10, 30 5, 45 20, 20 35),(30 20, 20 15, 20 25, 30 20)))"  # noqa: E501

    #    coverage = PolytopeMars(self.config, self.options).extract(self.request)  # noqa: E501
    #    print(coverage)
