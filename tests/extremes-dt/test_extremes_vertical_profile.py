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
        yesterday = today - timedelta(days=5)
        self.today = today.strftime("%Y%m%d")
        self.date = yesterday.strftime("%Y%m%d")
        self.date2 = (today - timedelta(days=6)).strftime("%Y%m%d")

        self.request = {
            "dataset": "extremes-dt",
            "class": "d1",
            "stream": "oper",
            "type": "fc",
            "date": self.date,
            "time": "0000",
            "levtype": "pl",
            "expver": "0001",
            "param": "130",
            "step": "0",
            "feature": {
                "type": "verticalprofile",
                "points": [[38.9, -9.1]],
                "range": {
                    "start": "0",
                    "end": "1000",
                },
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
                            "resolution": 2560,
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
            "pre_path": {
                "class": "d1",
                "expver": "0001",
                "dataset": "extremes-dt",
                "levtype": "pl",
                "stream": "oper",
                "type": "fc",
                "param": "130",
            },
            "compressed_axes_config": [
                "date",
                "time",
                "longitude",
                "latitude",
                "param",
                "levelist",
                "step",
            ],
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = self.options
        self.change_hash(self.request, self.cf)
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
        self.request["feature"]["axes"] = ["latitude", "longitude", "levelist"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def change_config_grid_hash(self, config, hash):
        for mappings in config["options"]["axis_config"]:
            for sub_mapping in mappings["transformations"]:
                if sub_mapping["name"] == "mapper":
                    sub_mapping["md5_hash"] = hash
        return config

    def change_hash(self, request, config):

        # This only holds for climate dt data
        if request.get("dataset", None) == "extremes-dt":
            # all resolution=standard have h128
            if request["levtype"] == "pl":
                hash = "1c409f6b78e87eeaeeb4a7294c28add7"
                return self.change_config_grid_hash(config, hash)

        if request.get("dataset", None) is None:
            if request["levtype"] == "ml":
                hash = "9fed647cd1c77c03f66d8c74a4e0ad34"
                return self.change_config_grid_hash(config, hash)

        return config
