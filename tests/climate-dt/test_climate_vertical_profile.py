import copy
from datetime import datetime, timedelta

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
            "levtype": "pl",
            "date": "20210101",
            "model": "ifs-nemo",
            "expver": "0001",
            "param": "60",
            "realization": "1",
            "resolution": "high",
            "stream": "clte",
            "type": "fc",
            "time": "0000",
            "levelist": "1/to/1000",
            "feature": {
                "type": "verticalprofile",
                "points": [[38.9, -9.1]],
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
                {
                    "axis_name": "levelist",
                    "transformations": [{"name": "type_change", "type": "int"}],
                },
                {
                    "axis_name": "step",
                    "transformations": [{"name": "type_change", "type": "int"}],
                },
            ],
            "pre_path": {"class": "d1", "expver": "0001", "levtype": "pl", "stream": "clte", "date": "20210101"},
            "compressed_axes_config": [
                "date",
                "time",
                "longitude",
                "latitude",
                "param",
                "levelist",
                "step",
                "levelist",
            ],
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

    def test_verticalprofile_range(self):
        self.request["feature"]["range"] = {"start": 0, "end": 1000}
        del self.request["levelist"]
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True
