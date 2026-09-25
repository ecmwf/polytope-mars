import os

from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# Point polytope/gribjump at the local test FDB. These must be set before the
# FDB/gribjump libraries are first imported/used.
os.environ.setdefault("FDB_HOME", "/home/fdbtest")
os.environ.setdefault("FDB5_CONFIG_FILE", "/home/fdbtest/etc/fdb/config.yaml")
os.environ.setdefault("GRIBJUMP_CONFIG_FILE", "/home/fdbtest/etc/gribjump/config.yaml")
os.environ.setdefault("FDB_ENABLE_GRIBJUMP", "1")


# EFAS reforecast (class=ce) uses independent date/hdate/time axes (like
# climate-dt timeseries), rather than a single merged datetime axis.
AXIS_CONFIG = [
    {"axis_name": "date", "transformations": [{"name": "type_change", "type": "date"}]},
    {
        "axis_name": "hdate",
        "transformations": [{"name": "type_change", "type": "date"}],
    },
    {"axis_name": "time", "transformations": [{"name": "type_change", "type": "time"}]},
    {
        "axis_name": "values",
        "transformations": [
            {
                "name": "mapper",
                "type": "local_regular",
                "resolution": [2969, 4529],
                "axes": ["latitude", "longitude"],
                "local": [
                    22.758333333333333,
                    72.24166666666666,
                    -25.241666666666667,
                    50.24166666666667,
                ],
                "axis_reversed": {"latitude": True, "longitude": False},
                "md5_hash": "60e55b0c1f432cca2a77cfa0c3b0717c",
            },
        ],
    },
    {
        "axis_name": "latitude",
        "transformations": [{"name": "reverse", "is_reverse": True}],
    },
    {
        "axis_name": "longitude",
        "transformations": [{"name": "cyclic", "range": [-180, 180]}],
    },
    {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
    {
        "axis_name": "number",
        "transformations": [{"name": "type_change", "type": "int"}],
    },
    {
        "axis_name": "levelist",
        "transformations": [{"name": "type_change", "type": "int"}],
    },
]

COMPRESSED_AXES_CONFIG = [
    "longitude",
    "latitude",
    "levtype",
    "step",
    "date",
    "hdate",
    "time",
    "domain",
    "origin",
    "expver",
    "param",
    "class",
    "stream",
    "type",
    "number",
    "levelist",
]

PRE_PATH = {
    "class": "ce",
    "stream": "efcl",
    "type": "sfo",
    "levtype": "sfc",
    "expver": "8888",
    "date": "20230101",
    "origin": "ecmf",
    "domain": "g",
    "model": "lisflood",
}


class TestEfasSeparateDatetime:
    def setup_method(self):
        self.request = {
            "class": "ce",
            "stream": "efcl",
            "type": "sfo",
            "model": "lisflood",
            "date": "20230101",
            "time": "12/00/18/06",
            "hdate": "20250103/20250101/20250105/20250102/20250104",
            "levtype": "sfc",
            "expver": "8888",
            "domain": "g",
            "param": "240023",
            "step": "6",
            "origin": "ecmf",
            "feature": {
                "type": "timeseries",
                "points": [[50.73746373267438, 7.107723168102066]],
                "time_axis": "hdate",
            },
        }

        options = {
            "axis_config": AXIS_CONFIG,
            "compressed_axes_config": COMPRESSED_AXES_CONFIG,
            "pre_path": PRE_PATH,
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
        self.cf = conf.model_dump()
        self.cf["options"] = options

    def test_timeseries_independent_date_hdate_time(self):
        result = PolytopeMars(self.cf).extract(self.request)

        # One collapsed PointSeries coverage for the single requested point.
        assert result["domainType"] == "PointSeries"
        assert len(result["coverages"]) == 1
        cov = result["coverages"][0]

        # 5 hdates x 4 times = 20 valid-times on the independent axes.
        t_values = cov["domain"]["axes"]["t"]["values"]
        assert len(t_values) == 20
        # Chronologically sorted and unique.
        assert t_values == sorted(t_values)
        assert len(set(t_values)) == 20

        # Parameter values line up with the valid-times.
        (param_name,) = cov["ranges"].keys()
        assert len(cov["ranges"][param_name]["values"]) == 20

        # Decodes cleanly to xarray with a 20-length time dimension.
        ds = Covjsonkit().decode(result).to_xarray()
        assert ds.sizes["t"] == 20
