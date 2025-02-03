import copy
from datetime import datetime, timedelta

import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# If using a local FDB need to set GRIBJUMP_CONFIG_FILE and DYLD_LIBRARY_PATH


class TestFeatureFactory:
    def setup_method(self):

        today = datetime.today()
        yesterday = today - timedelta(days=1)
        self.date = yesterday.strftime("%Y%m%d")

        self.request = {
            "activity": "scenariomip",
            "class": "d1",
            "dataset": "climate-dt",
            "experiment": "ssp3-7.0",
            "generation": "1",
            "levtype": "sfc",
            "date": "20210101",
            "model": "ifs-nemo",
            "expver": "0001",
            "param": "167/165",
            "realization": "1",
            "resolution": "high",
            "stream": "clte",
            "type": "fc",
            "time": "0000",
            "feature": {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
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
                "stream": "clte",
                "param": "167",
                "date": "20210101",
            },
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "date",
                "time",
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

    def test_polygon_multiple_dates(self):
        self.request["date"] = "20210101/20210102/20210103"
        del self.options["pre_path"]["date"]
        self.cf["options"] = self.options
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        da = decoder.to_xarray()
        assert da.datetimes.size == 3
