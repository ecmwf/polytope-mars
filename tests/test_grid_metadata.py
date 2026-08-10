"""Tests for PolytopeMars._get_grid_metadata() — extracting grid info from axis_config."""

import sys
from unittest.mock import MagicMock

# Mock pygribjump if not available (C extension, only on server)
if "pygribjump" not in sys.modules:
    sys.modules["pygribjump"] = MagicMock()

from polytope_mars.api import PolytopeMars  # noqa: E402

# ---------------------------------------------------------------------------
# Realistic configs matching actual polytope-server deployments
# ---------------------------------------------------------------------------

# Bologna production: polytope-od datasource (oper/enfo)
OPER_CONFIG = {
    "options": {
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
            "levtype": "sfc",
            "stream": "oper",
            "type": "fc",
        },
    },
    "coverageconfig": {"param_db": "ecmwf"},
}

# EFAS: local_regular grid
EFAS_CONFIG = {
    "options": {
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
                        "type": "local_regular",
                        "resolution": [2969, 4529],
                        "axes": ["latitude", "longitude"],
                        "local": [22.758333333333333, 72.24166666666666, -25.241666666666667, 50.24166666666667],
                        "axis_reversed": {"latitude": True, "longitude": False},
                        "md5_hash": "60e55b0c1f432cca2a77cfa0c3b0717c",
                    }
                ],
            },
            {"axis_name": "latitude", "transformations": [{"name": "reverse", "is_reverse": True}]},
            {"axis_name": "longitude", "transformations": [{"name": "cyclic", "range": [-180, 180]}]},
            {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
            {"axis_name": "number", "transformations": [{"name": "type_change", "type": "int"}]},
            {"axis_name": "levelist", "transformations": [{"name": "type_change", "type": "int"}]},
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
            "number",
        ],
        "pre_path": {
            "class": "ce",
            "expver": "0001",
            "levtype": "sfc",
            "stream": "efcl",
            "type": "fc",
        },
    },
    "coverageconfig": {"param_db": "ecmwf"},
}

# Config with no mapper (e.g. a MARS-passthrough datasource)
NO_MAPPER_CONFIG = {
    "options": {
        "axis_config": [
            {
                "axis_name": "date",
                "transformations": [{"name": "merge", "other_axis": "time", "linkers": ["T", "00"]}],
            },
            {"axis_name": "step", "transformations": [{"name": "type_change", "type": "int"}]},
        ],
        "compressed_axes_config": ["longitude", "latitude", "step", "date"],
        "pre_path": {},
    },
    "coverageconfig": {"param_db": "ecmwf"},
}


class TestGetGridMetadata:
    """Test _get_grid_metadata() extracts correct grid info from axis_config."""

    def test_octahedral_grid(self):
        """Octahedral mapper → reduced_gg with N."""
        pm = PolytopeMars(OPER_CONFIG)
        grid = pm._get_grid_metadata()

        assert grid == {"gridType": "reduced_gg", "N": 1280}

    def test_local_regular_grid(self):
        """Local regular mapper → regular_ll with Nj, Ni, area."""
        pm = PolytopeMars(EFAS_CONFIG)
        grid = pm._get_grid_metadata()

        assert grid["gridType"] == "regular_ll"
        assert grid["Nj"] == 2969
        assert grid["Ni"] == 4529
        assert grid["area"] == [
            22.758333333333333,
            72.24166666666666,
            -25.241666666666667,
            50.24166666666667,
        ]

    def test_no_mapper_returns_empty(self):
        """Config without a mapper transform → empty dict."""
        pm = PolytopeMars(NO_MAPPER_CONFIG)
        grid = pm._get_grid_metadata()

        assert grid == {}

    def test_grid_metadata_types(self):
        """Verify returned values are proper types for GRIB encoding."""
        pm = PolytopeMars(OPER_CONFIG)
        grid = pm._get_grid_metadata()

        assert isinstance(grid["gridType"], str)
        assert isinstance(grid["N"], int)
