import pytest
from conflator import Conflator
from covjsonkit.api import Covjsonkit

from polytope_mars.api import PolytopeMars
from polytope_mars.config import PolytopeMarsConfig

# os.environ['DYLD_LIBRARY_PATH'] = <path gribjump library
# os.environ['GRIBJUMP_CONFIG_FILE']= <path to gribjump config file>


class TestBoundingBox:
    def setup_method(self):
        self.options = {
            "axis_config": [
                {
                    "axis_name": "date",
                    "transformations": [
                        {
                            "name": "merge",
                            "other_axis": "time",
                            "linkers": ["T", "00"],
                        }  # noqa: E501
                    ],
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
                {
                    "axis_name": "latitude",
                    "transformations": [{"name": "reverse", "is_reverse": True}],  # noqa: E501
                },
                {
                    "axis_name": "longitude",
                    "transformations": [{"name": "cyclic", "range": [0, 360]}],
                },
                {
                    "axis_name": "step",
                    "transformations": [{"name": "type_change", "type": "int"}],  # noqa: E501
                },
                {
                    "axis_name": "number",
                    "transformations": [{"name": "type_change", "type": "int"}],  # noqa: E501
                },
            ],
            "compressed_axes_config": [
                "longitude",
                "latitude",
                "levtype",
                "step",
                "date",
                "domain",
                "expver",
                "param",
                "class",
                "stream",
                "type",
            ],
            "pre_path": {
                "class": "od",
                "expver": "0079",
                "levtype": "sfc",
                "stream": "oper",
                "type": "fc",
            },
        }

        self.request = {
            "class": "od",
            "stream": "oper",
            "type": "fc",
            "date": "20240915",
            "time": "1200",
            "levtype": "sfc",
            "expver": "0079",
            "domain": "g",
            "param": "167/169",
            "step": "0",
            "feature": {
                "type": "boundingbox",
                "points": [[38, -9.5], [39, -8.5]],
            },
        }

        conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()  # noqa: E501
        self.cf = conf.model_dump()
        self.cf["options"] = self.options

    @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_basic_boundingbox(self):
        polytope_mars = PolytopeMars(self.cf)
        result = polytope_mars.extract(self.request)
        assert result is not None

        decoder = Covjsonkit().decode(result)
        ds = decoder.to_xarray()
        assert ds is not None
        assert len(ds["datetimes"]) == 1
