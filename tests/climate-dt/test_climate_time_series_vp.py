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
        self.today = today.strftime("%Y%m%d")
        self.date = yesterday.strftime("%Y%m%d")

        self.request = {
            "activity": "scenariomip",
            "class": "d1",
            "dataset": "climate-dt",
            "experiment": "ssp3-7.0",
            "generation": "1",
            "levtype": "pl",
            "date": "20210101/to/20210102",
            "model": "ifs-nemo",
            "expver": "0001",
            "param": "131/132",
            "realization": "1",
            "resolution": "high",
            "stream": "clte",
            "type": "fc",
            "levelist": "1/100/1000",
            "time": "0000/0100",
            "feature": {
                "type": "timeseries",
                "points": [[38, -9.5], [1, 1]],
                "time_axis": "date",
            },
        }

        self.options = {
            "axis_config": [
                {
                    "axis_name": "date",
                    "transformations": [{"name": "type_change", "type": "date"}],
                },
                {
                    "axis_name": "time",
                    "transformations": [{"name": "type_change", "type": "time"}],
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
            "pre_path": {
                "class": "d1",
                "expver": "0001",
                "levtype": "pl",
                "stream": "clte",
                "dataset": "climate-dt",
                "activity": "scenariomip",
                "experiment": "ssp3-7.0",
            },  # , "date": "20210101/20210102/20210103"},
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

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_timeseries(self):
        result = PolytopeMars(self.cf).extract(self.request)
        decoder = Covjsonkit().decode(result)
        ds = decoder.to_xarray()
        assert len(ds) == 6
