import copy
from datetime import datetime, timedelta

import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH


class TestFeatureFactory:
    def setup_method(self, method):

        today = datetime.today()
        yesterday = today - timedelta(days=1)
        self.date = yesterday.strftime("%Y%m%d")

        self.request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": self.date,
            "time": "0000",
            "levtype": "pl",
            "expver": "0001",
            "domain": "g",
            "param": "203/133",
            "number": "1",
            "step": "0",
            "levelist": "0/to/1000",
            "feature": {
                "type": "verticalprofile",
                "points": [[38.9, -9.1]],
                "axes": "levelist",
            },
        }

        self.options = {
            "axis_config": [
                {
                    "axis_name": "date",
                    "transformations": [{"name": "merge", "other_axis": "time", "linkers": ["T", "00"]}],
                },
                {
                    "axis_name": "values",
                    "transformations": [
                        {
                            "name": "mapper",
                            "type": "octahedral",
                            "resolution": 1280,
                            "axes": ["latitude", "longitude"],
                        }
                    ],
                },
                {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
                {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [0, 360]}]},
                {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "number", "transformations": [{"name": "type_change", "type": "int"}]},
                {"axis_name": "levelist", "transformations": [{"name": "type_change", "type": "int"}]},
            ],
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "levtype",
                "levelist",
                "step",
                "date",
                "domain",
                "expver",
                "param",
                "class",
                "stream",
                "type",
                "number",
            ],
            "pre_path": {
                "class": "od",
                "expver": "0001",
                "levtype": "pl",
                "stream": "enfo",
                "type": "pf",
                "domain": "g",
                "date": self.date,
                "time": "0000",
            },
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_verticalprofile(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_verticalprofile_no_axes(self):
        del self.request["feature"]["axes"]
        PolytopeMars(self.cf).extract(self.request)
        assert True

    def test_verticalprofile_latlon_axes(self):
        self.request["feature"]["axes"] = ["latitude", "longitude"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_verticalprofile_lonlat_axes(self):
        request_copy = copy.deepcopy(self.request)
        self.request["feature"]["axes"] = ["latitude", "longitude"]
        result = PolytopeMars(self.cf).extract(self.request)
        request_copy["feature"]["axes"] = ["longitude", "latitude"]
        request_copy["feature"]["points"] = [[-9.1, 38.9]]
        result1 = PolytopeMars(self.cf).extract(request_copy)
        assert result == result1

    def test_verticalprofile_latlonlevel_axes(self):
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_verticalprofile_latlon_no_level_axes(self):
        del self.request["levelist"]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_verticalprofile_wrong_range(self):
        self.request["feature"]["range"] = {"start": 0, "end": 1000}
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist"]
        with pytest.raises(ValueError):
            PolytopeMars(self.cf).extract(self.request)

    def test_verticalprofile_range(self):
        self.request["feature"]["range"] = {"start": 0, "end": 1000}
        del self.request["levelist"]
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True
