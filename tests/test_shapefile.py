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
                "type": "shapefile",
                "file": "tests/data/NUTS_RG_01M_2021_4326.shp",
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
    def test_shapefile_invalid(self):
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
    def test_shapefile_valid(self):
        coverage = PolytopeMars(self.config, self.options).extract(self.request)  # noqa: E501
        print(coverage)

    @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_geojson_valid(self):
        self.request["feature"]["file"] = "tests/data/NUTS_RG_01M_2021_4326.geojson"  # noqa: E501

        coverage = PolytopeMars(self.config, self.options).extract(self.request)  # noqa: E501
        print(coverage)
