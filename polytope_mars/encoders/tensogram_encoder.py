"""
Tensogram encoder for polytope-mars.

Walks the polytope TensorIndexTree (same structure as covjsonkit) and produces
tensogram binary messages — one message per coverage — with columnar data
objects (coordinates + parameter values) and MARS metadata.

tensogram is an optional dependency; it is imported lazily when encode() is
first called.  If the package is not installed, a clear ImportError is raised.
"""

import logging
from datetime import datetime, timedelta

import numpy as np
from covjsonkit.param_db import get_param_ids

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain-type mapping (feature type -> CovJSON domain type)
# ---------------------------------------------------------------------------
_DOMAIN_TYPES = {
    "timeseries": "PointSeries",
    "verticalprofile": "VerticalProfile",
    "boundingbox": "MultiPoint",
    "polygon": "MultiPoint",
    "circle": "MultiPoint",
    "frame": "MultiPoint",
    "trajectory": "Trajectory",
    "position": "PointSeries",
    "shapefile": "MultiPoint",
}

# Feature types whose coverage grouping is MultiPoint
_MULTIPOINT_FEATURES = {"boundingbox", "polygon", "circle", "frame", "shapefile"}


# ===================================================================
# TensogramResult — lightweight wrapper returned to the caller
# ===================================================================
class TensogramResult:
    """Wrapper for a collection of tensogram-encoded messages.

    Attributes
    ----------
    messages : list[bytes]
        Individual tensogram messages (one per coverage).
    """

    def __init__(self):
        self._messages: list = []

    # -- public API ---------------------------------------------------------

    @property
    def messages(self) -> list:
        """Return a copy of the message list."""
        return list(self._messages)

    def add_message(self, message: bytes):
        """Append a single tensogram message."""
        self._messages.append(message)

    def to_bytes(self) -> bytes:
        """Concatenate all messages into one multi-message buffer."""
        return b"".join(self._messages)

    def to_file(self, path: str):
        """Write all messages to a ``.tgm`` file."""
        with open(path, "wb") as fh:
            for msg in self._messages:
                fh.write(msg)

    def merge(self, other: "TensogramResult"):
        """Merge *other* into this result (appends all messages)."""
        self._messages.extend(other._messages)

    # -- dunder helpers -----------------------------------------------------

    def __len__(self):
        return len(self._messages)

    def __iter__(self):
        return iter(self._messages)

    def __repr__(self):
        return f"TensogramResult({len(self._messages)} messages)"


# ===================================================================
# TensogramEncoder — walks the polytope tree, builds messages
# ===================================================================
class TensogramEncoder:
    """Encode a polytope result tree into tensogram messages.

    Parameters
    ----------
    coverageconfig : CovjsonKitConfig (or dict)
        Coverage configuration — used to access the parameter database
        for resolving param IDs to shortnames / units / descriptions.
    feature_type : str
        The feature type string (e.g. ``"timeseries"``, ``"boundingbox"``).
    """

    def __init__(self, coverageconfig, feature_type: str):
        if hasattr(coverageconfig, "model_dump"):
            self._covconf = coverageconfig.model_dump()
        elif isinstance(coverageconfig, dict):
            self._covconf = coverageconfig
        else:
            self._covconf = {"param_db": "ecmwf"}

        self.feature_type = feature_type
        self.domain_type = _DOMAIN_TYPES.get(feature_type, "Unknown")
        self._tensogram = None  # lazy-loaded
        self._param_id_map = None  # lazy-loaded

    # ------------------------------------------------------------------
    # Lazy import of tensogram
    # ------------------------------------------------------------------
    def _import_tensogram(self):
        if self._tensogram is not None:
            return self._tensogram
        try:
            import tensogram
        except ImportError:
            raise ImportError(
                "The 'tensogram' package is required for format='tensogram' but is not installed. "
                "Install it with:  pip install tensogram"
            )
        self._tensogram = tensogram
        return tensogram

    # ------------------------------------------------------------------
    # Parameter database helpers
    # ------------------------------------------------------------------
    def _get_param_id_map(self) -> dict:
        """Return ``{shortname: numeric_id_str, ...}`` dict from covjsonkit."""
        if self._param_id_map is None:
            # get_param_ids expects an object with a .param_db attribute,
            # not a plain dict.  Wrap if necessary.
            conf = self._covconf
            if isinstance(conf, dict):
                conf = _DictAttrWrapper(conf)
            self._param_id_map = get_param_ids(conf)
        return self._param_id_map

    def _resolve_param(self, param_id) -> dict:
        """Resolve a numeric param id to ``{shortname, units, description}``."""
        param_id_str = str(int(param_id)) if not isinstance(param_id, str) else param_id

        # Build reverse map: numeric_id_str -> shortname
        id_map = self._get_param_id_map()
        reverse = {v: k for k, v in id_map.items()}

        shortname = reverse.get(param_id_str, param_id_str)

        # Try to get units and description from covjsonkit
        units = ""
        description = ""
        try:
            from covjsonkit.param_db import get_param_descriptions, get_param_units

            conf = self._covconf
            if isinstance(conf, dict):
                conf = _DictAttrWrapper(conf)
            units_db = get_param_units(conf)
            desc_db = get_param_descriptions(conf)
            units = units_db.get(shortname, units_db.get(param_id_str, ""))
            description = desc_db.get(shortname, desc_db.get(param_id_str, ""))
        except (ImportError, Exception):
            pass

        return {
            "shortname": shortname,
            "id": param_id_str,
            "units": units,
            "description": description,
        }

    # ==================================================================
    # Public entry points — one per tree-walker variant
    # ==================================================================

    def from_polytope(self, result) -> TensogramResult:
        """Walk a standard (date+step) polytope result tree."""
        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        self.walk_tree(result, fields, coords, mars_metadata, range_dict)
        return self._build_messages(
            fields, coords, mars_metadata, range_dict, walker="standard"
        )

    def from_polytope_step(self, result) -> TensogramResult:
        """Walk a climate-dt polytope result tree (step-as-time)."""
        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
            "times": [],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        self.walk_tree_step(result, fields, coords, mars_metadata, range_dict)
        return self._build_messages(
            fields, coords, mars_metadata, range_dict, walker="step"
        )

    def from_polytope_month(self, result) -> TensogramResult:
        """Walk a monthly-mean polytope result tree."""
        fields = {
            "lat": 0,
            "param": [],
            "number": [0],
            "step": [0],
            "dates": [],
            "levels": [0],
        }
        coords = {}
        mars_metadata = {}
        range_dict = {}

        self.walk_tree_month(result, fields, coords, mars_metadata, range_dict)
        return self._build_messages(
            fields, coords, mars_metadata, range_dict, walker="month"
        )

    # ==================================================================
    # Tree walkers (adapted from covjsonkit encoder.py)
    # ==================================================================

    def walk_tree(self, tree, fields, coords, mars_metadata, range_dict):
        """Standard date+step tree walker.

        ``range_dict`` keys are 5-tuples: ``(date, level, number, param, step)``.
        """
        if len(tree.children) != 0:
            for child in tree.children:
                axis_name = child.axis.name
                # Capture MARS metadata from non-coordinate axes
                if axis_name not in ("latitude", "longitude", "param", "date"):
                    mars_metadata[axis_name] = child.values[0]

                if axis_name == "latitude":
                    fields["lat"] = child.values[0]
                elif axis_name == "levelist":
                    fields["levels"] = list(child.values)
                elif axis_name == "param":
                    fields["param"] = list(child.values)
                elif axis_name in ("date", "time"):
                    dates = [f"{d}Z" for d in child.values]
                    mars_metadata["Forecast date"] = str(child.values[0])
                    for d in dates:
                        coords[d] = {"composite": [], "t": [d]}
                    fields["dates"].extend(dates)
                elif axis_name == "number":
                    fields["number"] = list(child.values)
                elif axis_name == "step":
                    fields["step"] = list(child.values)

                self.walk_tree(child, fields, coords, mars_metadata, range_dict)
        else:
            # Leaf node — extract data values
            tree.values = [float(v) for v in tree.values]

            if all(v is None for v in tree.result):
                return

            tree.result = [float(v) if v is not None else np.nan for v in tree.result]

            n_levels = max(len(fields["levels"]), 1)
            n_numbers = max(len(fields["number"]), 1)
            n_params = max(len(fields["param"]), 1)
            n_steps = max(len(fields["step"]), 1)

            total = len(tree.result)
            level_len = total / n_levels
            num_len = level_len / n_numbers
            para_len = num_len / n_params
            step_len = para_len / n_steps

            # Append composite coordinates for this leaf
            current_date = fields["dates"][-1] if fields["dates"] else "unknown"
            for lon_val in tree.values:
                if current_date in coords:
                    coords[current_date]["composite"].append([fields["lat"], lon_val])

            # Deinterleave and populate range_dict
            for li, level in enumerate(fields["levels"]):
                for ni, num in enumerate(fields["number"]):
                    for pi, para in enumerate(fields["param"]):
                        for si, step in enumerate(fields["step"]):
                            start = int(
                                li * level_len
                                + ni * num_len
                                + pi * para_len
                                + si * step_len
                            )
                            end = int(start + step_len)
                            key = (current_date, level, num, para, step)
                            if key not in range_dict:
                                range_dict[key] = []
                            range_dict[key].extend(tree.result[start:end])

    def walk_tree_step(self, tree, fields, coords, mars_metadata, range_dict):
        """Climate-DT tree walker (step offsets as time axis).

        ``range_dict`` keys are 4-tuples: ``(date, level, number, param)``.
        Values are lists-of-lists (one sub-list per leaf visit).
        """
        if len(tree.children) != 0:
            for child in tree.children:
                axis_name = child.axis.name
                if axis_name not in ("latitude", "longitude", "param", "date"):
                    mars_metadata[axis_name] = child.values[0]

                if axis_name == "latitude":
                    fields["lat"] = child.values[0]
                elif axis_name == "levelist":
                    fields["levels"] = list(child.values)
                elif axis_name == "param":
                    fields["param"] = list(child.values)
                elif axis_name in ("date", "time"):
                    dates = [f"{d}Z" for d in child.values]
                    mars_metadata["Forecast date"] = str(child.values[0])
                    for d in dates:
                        coords[d] = {"composite": [], "t": [d]}
                    fields["dates"].extend(dates)
                elif axis_name == "number":
                    fields["number"] = list(child.values)
                elif axis_name == "step":
                    fields["step"] = list(child.values)
                    fields["times"] = list(child.values)

                self.walk_tree_step(child, fields, coords, mars_metadata, range_dict)
        else:
            tree.values = [float(v) for v in tree.values]
            if all(v is None for v in tree.result):
                return

            tree.result = [float(v) if v is not None else np.nan for v in tree.result]

            n_levels = max(len(fields["levels"]), 1)
            n_numbers = max(len(fields["number"]), 1)
            n_params = max(len(fields["param"]), 1)

            total = len(tree.result)
            level_len = total / n_levels
            num_len = level_len / n_numbers
            para_len = num_len / n_params

            current_date = fields["dates"][-1] if fields["dates"] else "unknown"
            for lon_val in tree.values:
                if current_date in coords:
                    coords[current_date]["composite"].append([fields["lat"], lon_val])

            for li, level in enumerate(fields["levels"]):
                for ni, num in enumerate(fields["number"]):
                    for pi, para in enumerate(fields["param"]):
                        start = int(li * level_len + ni * num_len + pi * para_len)
                        end = int(start + para_len)
                        key = (current_date, level, num, para)
                        if key not in range_dict:
                            range_dict[key] = []
                        range_dict[key].append(tree.result[start:end])

    def walk_tree_month(self, tree, fields, coords, mars_metadata, range_dict):
        """Monthly-mean tree walker.

        ``range_dict`` keys are 4-tuples: ``(date, level, number, param)``
        where *date* is ``"YYYY-MM"``.
        """
        if len(tree.children) != 0:
            for child in tree.children:
                axis_name = child.axis.name

                if axis_name not in (
                    "latitude",
                    "longitude",
                    "param",
                    "date",
                    "month",
                    "year",
                ):
                    mars_metadata[axis_name] = child.values[0]

                if axis_name == "latitude":
                    fields["lat"] = child.values[0]
                elif axis_name == "levelist":
                    fields["levels"] = list(child.values)
                elif axis_name == "param":
                    fields["param"] = list(child.values)
                elif axis_name == "year":
                    fields["year"] = list(child.values)
                elif axis_name == "month":
                    fields["month"] = list(child.values)
                    # Synthesize date strings as "YYYY-MM"
                    if "year" in fields:
                        for y in fields["year"]:
                            for m in child.values:
                                date_str = f"{int(y)}-{int(m):02d}"
                                coords[date_str] = {"composite": [], "t": [date_str]}
                                fields["dates"].append(date_str)
                elif axis_name in ("date", "time"):
                    dates = [f"{d}Z" for d in child.values]
                    for d in dates:
                        coords[d] = {"composite": [], "t": [d]}
                    fields["dates"].extend(dates)
                elif axis_name == "number":
                    fields["number"] = list(child.values)
                elif axis_name == "step":
                    fields["step"] = list(child.values)

                self.walk_tree_month(child, fields, coords, mars_metadata, range_dict)
        else:
            tree.values = [float(v) for v in tree.values]
            if all(v is None for v in tree.result):
                return

            tree.result = [float(v) if v is not None else np.nan for v in tree.result]

            n_levels = max(len(fields["levels"]), 1)
            n_numbers = max(len(fields["number"]), 1)
            n_params = max(len(fields["param"]), 1)

            total = len(tree.result)
            level_len = total / n_levels
            num_len = level_len / n_numbers
            para_len = num_len / n_params

            current_date = fields["dates"][-1] if fields["dates"] else "unknown"
            for lon_val in tree.values:
                if current_date in coords:
                    coords[current_date]["composite"].append([fields["lat"], lon_val])

            for li, level in enumerate(fields["levels"]):
                for ni, num in enumerate(fields["number"]):
                    for pi, para in enumerate(fields["param"]):
                        start = int(li * level_len + ni * num_len + pi * para_len)
                        end = int(start + para_len)
                        key = (current_date, level, num, para)
                        if key not in range_dict:
                            range_dict[key] = []
                        range_dict[key].append(tree.result[start:end])

    # ==================================================================
    # Message building — dispatches per domain type
    # ==================================================================

    def _build_messages(
        self, fields, coords, mars_metadata, range_dict, walker="standard"
    ):
        """Dispatch to the appropriate builder based on feature type."""
        result = TensogramResult()

        if self.feature_type in ("timeseries", "position"):
            self._build_messages_pointseries(
                result, fields, coords, mars_metadata, range_dict, walker
            )
        elif self.feature_type == "verticalprofile":
            self._build_messages_verticalprofile(
                result, fields, coords, mars_metadata, range_dict, walker
            )
        elif self.feature_type == "trajectory":
            self._build_messages_trajectory(
                result, fields, coords, mars_metadata, range_dict, walker
            )
        elif self.feature_type in _MULTIPOINT_FEATURES:
            self._build_messages_multipoint(
                result, fields, coords, mars_metadata, range_dict, walker
            )
        else:
            # Fallback: treat as multipoint
            logger.warning(
                "Unknown feature type '%s', falling back to multipoint encoding",
                self.feature_type,
            )
            self._build_messages_multipoint(
                result, fields, coords, mars_metadata, range_dict, walker
            )

        return result

    # ------------------------------------------------------------------
    # PointSeries (TimeSeries, Position)
    # ------------------------------------------------------------------
    def _build_messages_pointseries(
        self, result, fields, coords, mars_metadata, range_dict, walker
    ):
        """One message per (spatial-point, date, level, number)."""
        for date in fields["dates"]:
            if date not in coords:
                continue
            composite = coords[date].get("composite", [])
            n_points = len(composite)

            for point_i in range(n_points):
                lat, lon = composite[point_i]

                for level in fields["levels"]:
                    for num in fields["number"]:
                        # Collect values for each param across all steps
                        param_data = {}
                        step_values = []

                        if walker == "standard":
                            for para in fields["param"]:
                                vals = []
                                for step in fields["step"]:
                                    key = (date, level, num, para, step)
                                    data = range_dict.get(key, [])
                                    if point_i < len(data):
                                        vals.append(data[point_i])
                                param_data[para] = vals
                            step_values = [float(s) for s in fields["step"]]
                        else:
                            # step/month walkers: range_dict values are lists-of-lists
                            for para in fields["param"]:
                                key = (date, level, num, para)
                                data = range_dict.get(key, [])
                                if point_i < len(data):
                                    vals = (
                                        data[point_i]
                                        if isinstance(data[point_i], list)
                                        else [data[point_i]]
                                    )
                                else:
                                    vals = []
                                param_data[para] = vals
                            step_values = [
                                float(s)
                                for s in fields.get("times", fields.get("step", []))
                            ]

                        # Skip empty coverages
                        if all(len(v) == 0 for v in param_data.values()):
                            continue

                        # Build time_values for metadata
                        time_values = self._compute_time_strings(
                            date, step_values, walker
                        )

                        # Build MARS metadata for this coverage
                        coverage_mars = dict(mars_metadata)
                        coverage_mars["number"] = num
                        coverage_mars["Forecast date"] = date
                        coverage_mars["levelist"] = level
                        coverage_mars.pop("step", None)

                        msg = self._encode_message(
                            mars_meta=coverage_mars,
                            coord_arrays=[
                                ("latitude", np.array([lat], dtype=np.float64)),
                                ("longitude", np.array([lon], dtype=np.float64)),
                                ("step", np.array(step_values, dtype=np.float64)),
                            ],
                            param_arrays=param_data,
                            time_values=time_values,
                        )
                        result.add_message(msg)

    # ------------------------------------------------------------------
    # MultiPoint (BoundingBox, Polygon, Circle, Frame, Shapefile)
    # ------------------------------------------------------------------
    def _build_messages_multipoint(
        self, result, fields, coords, mars_metadata, range_dict, walker
    ):
        """One message per (date, number, step)."""
        for date in fields["dates"]:
            if date not in coords:
                continue
            composite = coords[date].get("composite", [])
            if not composite:
                continue

            lats = np.array([c[0] for c in composite], dtype=np.float64)
            lons = np.array([c[1] for c in composite], dtype=np.float64)
            levels_arr = np.array(
                [c[2] if len(c) > 2 else 0 for c in composite], dtype=np.float64
            )

            for num in fields["number"]:
                if walker == "standard":
                    for step in fields["step"]:
                        param_data = {}
                        for para in fields["param"]:
                            # Try matching with actual level values
                            vals = []
                            for level in fields["levels"]:
                                k = (date, level, num, para, step)
                                vals.extend(range_dict.get(k, []))
                            param_data[para] = vals

                        if all(len(v) == 0 for v in param_data.values()):
                            continue

                        time_values = self._compute_time_strings(
                            date, [float(step)], walker
                        )

                        coverage_mars = dict(mars_metadata)
                        coverage_mars["number"] = num
                        coverage_mars["step"] = step
                        coverage_mars["Forecast date"] = date

                        coord_arrays = [
                            ("latitude", lats),
                            ("longitude", lons),
                            ("levelist", levels_arr),
                        ]

                        msg = self._encode_message(
                            mars_meta=coverage_mars,
                            coord_arrays=coord_arrays,
                            param_arrays=param_data,
                            time_values=time_values,
                        )
                        result.add_message(msg)
                else:
                    # step/month walker — no step dimension in key
                    param_data = {}
                    for para in fields["param"]:
                        vals = []
                        for level in fields["levels"]:
                            k = (date, level, num, para)
                            data = range_dict.get(k, [])
                            # Flatten lists-of-lists
                            for item in data:
                                if isinstance(item, list):
                                    vals.extend(item)
                                else:
                                    vals.append(item)
                        param_data[para] = vals

                    if all(len(v) == 0 for v in param_data.values()):
                        continue

                    time_values = [date]

                    coverage_mars = dict(mars_metadata)
                    coverage_mars["number"] = num
                    coverage_mars["Forecast date"] = date

                    coord_arrays = [
                        ("latitude", lats),
                        ("longitude", lons),
                        ("levelist", levels_arr),
                    ]

                    msg = self._encode_message(
                        mars_meta=coverage_mars,
                        coord_arrays=coord_arrays,
                        param_arrays=param_data,
                        time_values=time_values,
                    )
                    result.add_message(msg)

    # ------------------------------------------------------------------
    # VerticalProfile
    # ------------------------------------------------------------------
    def _build_messages_verticalprofile(
        self, result, fields, coords, mars_metadata, range_dict, walker
    ):
        """One message per (spatial-point, date, number, step)."""
        for date in fields["dates"]:
            if date not in coords:
                continue
            composite = coords[date].get("composite", [])
            n_points = len(composite)

            for point_i in range(n_points):
                lat, lon = composite[point_i]

                for num in fields["number"]:
                    for step in fields["step"]:
                        param_data = {}
                        for para in fields["param"]:
                            vals = []
                            for level in fields["levels"]:
                                if walker == "standard":
                                    key = (date, level, num, para, step)
                                else:
                                    key = (date, level, num, para)
                                data = range_dict.get(key, [])
                                if point_i < len(data):
                                    vals.append(data[point_i])
                            param_data[para] = vals

                        if all(len(v) == 0 for v in param_data.values()):
                            continue

                        time_values = self._compute_time_strings(
                            date, [float(step)], walker
                        )

                        coverage_mars = dict(mars_metadata)
                        coverage_mars["number"] = num
                        coverage_mars["step"] = step
                        coverage_mars["Forecast date"] = date

                        levels_arr = np.array(
                            [float(lv) for lv in fields["levels"]], dtype=np.float64
                        )

                        msg = self._encode_message(
                            mars_meta=coverage_mars,
                            coord_arrays=[
                                ("latitude", np.array([lat], dtype=np.float64)),
                                ("longitude", np.array([lon], dtype=np.float64)),
                                ("levelist", levels_arr),
                            ],
                            param_arrays=param_data,
                            time_values=time_values,
                        )
                        result.add_message(msg)

    # ------------------------------------------------------------------
    # Trajectory
    # ------------------------------------------------------------------
    def _build_messages_trajectory(
        self, result, fields, coords, mars_metadata, range_dict, walker
    ):
        """One message per (date, number)."""
        for date in fields["dates"]:
            if date not in coords:
                continue
            composite = coords[date].get("composite", [])
            if not composite:
                continue

            lats = np.array([c[0] for c in composite], dtype=np.float64)
            lons = np.array([c[1] for c in composite], dtype=np.float64)

            for num in fields["number"]:
                param_data = {}
                all_steps = []

                if walker == "standard":
                    for para in fields["param"]:
                        vals = []
                        for step in fields["step"]:
                            for level in fields["levels"]:
                                k = (date, level, num, para, step)
                                vals.extend(range_dict.get(k, []))
                        param_data[para] = vals
                    all_steps = [float(s) for s in fields["step"]]
                else:
                    for para in fields["param"]:
                        vals = []
                        for level in fields["levels"]:
                            k = (date, level, num, para)
                            data = range_dict.get(k, [])
                            for item in data:
                                if isinstance(item, list):
                                    vals.extend(item)
                                else:
                                    vals.append(item)
                        param_data[para] = vals

                if all(len(v) == 0 for v in param_data.values()):
                    continue

                time_values = self._compute_time_strings(date, all_steps, walker)

                coverage_mars = dict(mars_metadata)
                coverage_mars["number"] = num
                coverage_mars["Forecast date"] = date

                coord_arrays = [
                    ("latitude", lats),
                    ("longitude", lons),
                ]
                # Add step as a per-point coordinate for trajectory
                if all_steps:
                    coord_arrays.append(("step", np.array(all_steps, dtype=np.float64)))

                msg = self._encode_message(
                    mars_meta=coverage_mars,
                    coord_arrays=coord_arrays,
                    param_arrays=param_data,
                    time_values=time_values,
                )
                result.add_message(msg)

    # ==================================================================
    # Message encoding helpers
    # ==================================================================

    def _compute_time_strings(self, date_str, step_values, walker):
        """Compute ISO 8601 time strings from a base date and steps."""
        if walker == "month":
            return [date_str]

        # Try to parse the base date
        base_date_str = date_str.rstrip("Z")
        try:
            if "T" in base_date_str:
                base_dt = datetime.strptime(base_date_str, "%Y%m%dT%H%M%S")
            else:
                base_dt = datetime.strptime(base_date_str, "%Y%m%d")
        except (ValueError, TypeError):
            # Can't parse — return the raw date string
            return [date_str]

        time_strings = []
        for step in step_values:
            try:
                dt = base_dt + timedelta(hours=float(step))
                time_strings.append(dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
            except (ValueError, TypeError):
                time_strings.append(date_str)

        return time_strings if time_strings else [date_str]

    def _encode_message(self, mars_meta, coord_arrays, param_arrays, time_values):
        """Build and encode one tensogram message.

        Parameters
        ----------
        mars_meta : dict
            MARS metadata for this coverage.
        coord_arrays : list of (name, np.ndarray)
            Coordinate data objects.
        param_arrays : dict of {param_id: list[float]}
            Parameter data arrays, keyed by numeric param ID.
        time_values : list[str]
            ISO 8601 time strings for ``_extra_["time_values"]``.

        Returns
        -------
        bytes
            Encoded tensogram message.
        """
        tg = self._import_tensogram()

        # Build base entries and descriptor/data pairs
        base = []
        descriptors_and_data = []

        # 1. Coordinate objects
        for name, arr in coord_arrays:
            if arr.size == 0:
                continue
            base.append(
                {
                    "name": name,
                    "role": "coordinate",
                    "units": _COORD_UNITS.get(name, ""),
                }
            )
            desc = {
                "type": "ntensor",
                "shape": list(arr.shape),
                "dtype": _numpy_dtype_to_tensogram(arr.dtype),
            }
            descriptors_and_data.append((desc, arr))

        # 2. Parameter data objects
        for para_id, values in param_arrays.items():
            if not values:
                continue
            info = self._resolve_param(para_id)
            arr = np.array(values, dtype=np.float64)

            base_entry = {
                "name": info["shortname"],
                "role": "data",
                "mars": {"param": info["id"]},
            }
            if info["units"]:
                base_entry["units"] = info["units"]
            if info["description"]:
                base_entry["description"] = info["description"]
            base.append(base_entry)

            desc = {
                "type": "ntensor",
                "shape": list(arr.shape),
                "dtype": "float64",
            }
            descriptors_and_data.append((desc, arr))

        # 3. Build metadata
        metadata = {
            "version": 2,
            "_extra_": {
                "source": "polytope-mars",
                "feature_type": self.feature_type,
                "domain_type": self.domain_type,
                "mars": mars_meta,
                "time_values": time_values,
            },
            "base": base,
        }

        # 4. Encode
        msg = bytes(tg.encode(metadata, descriptors_and_data))
        logger.debug(
            "Encoded tensogram message: %d bytes, %d objects",
            len(msg),
            len(descriptors_and_data),
        )
        return msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DictAttrWrapper:
    """Wrap a dict so attributes are accessible as ``obj.key``."""

    def __init__(self, d: dict):
        self.__dict__.update(d)


_COORD_UNITS = {
    "latitude": "degrees_north",
    "longitude": "degrees_east",
    "levelist": "hPa",
    "step": "hours",
}


def _numpy_dtype_to_tensogram(dtype) -> str:
    """Map a numpy dtype to a tensogram dtype string."""
    mapping = {
        np.float16: "float16",
        np.float32: "float32",
        np.float64: "float64",
        np.int8: "int8",
        np.int16: "int16",
        np.int32: "int32",
        np.int64: "int64",
        np.uint8: "uint8",
        np.uint16: "uint16",
        np.uint32: "uint32",
        np.uint64: "uint64",
    }
    return mapping.get(dtype.type, "float64")
