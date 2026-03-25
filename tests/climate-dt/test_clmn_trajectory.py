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
                "type": "trajectory",
                "points": [[-1, -1], [0, 0], [1, 1]],
                "axes": ["latitude", "longitude"],
                "inflate": "round",
                "inflation": 0.1,
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
    def test_trajectory(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_lonlat(self):
        self.request["feature"]["axes"] = ["longitude", "latitude"]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_trajectory_inflation_list(self):
        self.request["feature"]["inflation"] = [0.1, 0.2]
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        decoder.to_xarray()
        assert True

    def test_trajectory_incorrect_inflation_list(self):
        with pytest.raises(ValueError):
            self.request["feature"]["inflation"] = [0.1, 0.2, 0.3]
            PolytopeMars(self.cf).extract(self.request)

    def test_trajectory_1_axes(self):
        self.request["feature"]["axes"] = ["latitude"]
        self.request["feature"]["points"] = [[-1], [0], [1]]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)

    def test_trajectory_no_inflation(self):
        del self.request["feature"]["inflation"]
        with pytest.raises(KeyError):
            PolytopeMars(self.cf).extract(self.request)
