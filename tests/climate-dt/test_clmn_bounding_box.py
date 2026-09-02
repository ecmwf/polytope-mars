import copy

import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH


class TestFeatureFactory:
    def setup_method(self):

        self.request = {
            "activity": "scenariomip",
            "class": "d1",
            "dataset": "climate-dt",
            "experiment": "ssp3-7.0",
            "generation": "1",
            "levtype": "sfc",
            "month": "1",
            "year": "2021",
            "model": "ifs-nemo",
            "expver": "0001",
            "param": "167/165",
            "realization": "1",
            "resolution": "high",
            "stream": "clmn",
            "type": "fc",
            "feature": {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
            },
        }

        self.options = {
            "axis_config": [
                {"axis_name": "month", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "year", "transformations": [{"name": "type_change", "type": "int"}]},
                {
                    "axis_name": "values",
                    "transformations": [
                        {
                            "name": "mapper",
                            "type": "healpix_nested",
                            "resolution": 1024,
                            "axes": ["latitude", "longitude"],
                        }
                    ],
                },
                {
                    "axis_name": "latitude",
                    "transformations": [{"name": "reverse", "is_reverse": True}],
                },
                {
                    "axis_name": "longitude",
                    "transformations": [{"name": "cyclic", "range": [0, 360]}],
                },
            ],
            "pre_path": {
                "class": "d1",
                "expver": "0001",
                "levtype": "sfc",
                "stream": "clmn",
                "param": "167",
                "dataset": "climate-dt",
                "activity": "scenariomip",
                "experiment": "ssp3-7.0",
                "month": "1",
                "year": "2021",
            },
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "month",
                "year",
                "param",
            ],
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_boundingbox_three_points(self):
        with pytest.raises(ValueError):
            self.request["feature"]["points"] = [[0, 0], [1, 1], [2, 2]]
            PolytopeMars(self.cf).extract(self.request)

    def test_boundingbox_three_values_per_point(self):
        with pytest.raises(ValueError):
            self.request["feature"]["points"] = [[0, 0, 0], [1, 1, 1]]
            PolytopeMars(self.cf).extract(self.request)

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox_lonlat(self):
        request_copy = copy.deepcopy(self.request)
        self.request["feature"]["points"] = [[0.1, 0.2], [0.2, 0.3]]
        result = PolytopeMars(self.cf).extract(self.request)
        request_copy["feature"]["axes"] = ["longitude", "latitude"]
        request_copy["feature"]["points"] = [[0.2, 0.1], [0.3, 0.2]]
        result2 = PolytopeMars(self.cf).extract(request_copy)
        assert result == result2

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_boundingbox_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["points"] = [[-1], [0], [1]]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_boundingbox_no_points(self):
        with pytest.raises(KeyError):
            del self.request["feature"]["points"]
            PolytopeMars(self.cf).extract(self.request)

    def test_boundingbox_multiple_months(self):
        self.request["month"] = "1/to/3"
        del self.options["pre_path"]["month"]
        self.cf["options"] = self.options
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True
