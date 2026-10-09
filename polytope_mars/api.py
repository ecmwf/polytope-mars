import copy
import datetime
import json
import logging
import time
from typing import Iterator, List

import pandas as pd
import pygribjump as gj
from conflator import Conflator
from polytope_feature import shapes

from .blocks import RequestHeader
from .config import PolytopeMarsConfig
from .coverage_plan import TimeSeriesReforecastPlan, plan_class, time_axis_role
from .encoders import get_encoder
from .extract import BlockExtractor, build_parameters
from .features.boundingbox import BoundingBox
from .features.circle import Circle
from .features.frame import Frame
from .features.path import Path
from .features.polygon import Polygons
from .features.position import Position
from .features.shpfile import Shapefile
from .features.timeseries import TimeSeries
from .features.verticalprofile import VerticalProfile
from .legacy_format import referencing_coordinates
from .limits import (
    estimate_points_per_field,
    estimate_tree_branches,
    estimate_tree_bytes,
    format_bytes,
    tree_byte_limit,
)
from .param_db import get_param_ids
from .utils.datetimes import convert_timestamp, find_step_intervals, time_step_to_freq

features = {
    "timeseries": TimeSeries,
    "verticalprofile": VerticalProfile,
    "boundingbox": BoundingBox,
    "frame": Frame,
    "trajectory": Path,
    "shapefile": Shapefile,
    "polygon": Polygons,
    "circle": Circle,
    "position": Position,
}


class PolytopeMars:
    def __init__(self, config=None, log_context=None, datacube_factory=None):
        """
        :param config: PolytopeMarsConfig (or dict); default locations are searched when None.
        :param log_context: dict with at least an ``id`` key, forwarded to polytope/gribjump.
        :param datacube_factory: zero-argument callable returning the gribjump handle given to
            polytope. Defaults to ``pygribjump.GribJump()`` (looked up at call time, so
            monkeypatching ``polytope_mars.api.gj.GribJump`` keeps working).
        """
        # Initialise polytope-mars configuration
        self.log_context = log_context
        self.id = log_context["id"] if log_context else "-1"

        # If no config check default locations
        if config is None:
            self.conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()  # noqa: E501
            logging.debug(f"{self.id}: Config loaded from file: {self.conf}")  # noqa: E501
        # else initialise with provided config
        else:
            self.conf = PolytopeMarsConfig.model_validate(config)
            logging.debug(f"{self.id}: Config loaded from dictionary: {self.conf}")  # noqa: E501

        self.datacube_factory = datacube_factory
        #: MIME type / file extension of the last extract_stream's encoder
        self.content_type = None
        self.file_extension = None
        # Per-extract phase timings (ms) and counts, filled by retrieve_data.
        self.timings = {}

    def _has_subhourly_step_transform(self) -> bool:
        """Check if the step axis has a subhourly_step type_change transform configured."""
        for axis_config in self.conf.options.axis_config:
            if axis_config.axis_name == "step":
                for transform in axis_config.transformations:
                    # Check if it's a type_change transform with type subhourly_step
                    if hasattr(transform, "name") and transform.name == "type_change":
                        if hasattr(transform, "type") and transform.type == "subhourly_step":
                            return True
        return False

    def _format_step_as_subhourly(self, step_value) -> str:
        """
        Convert a step value to subhourly format (e.g., "0h0m").

        :param step_value: Step value as int, str, or pd.Timedelta
        :return: Step formatted as string like "0h0m", "1h30m", etc.
        """
        # Convert to timedelta first
        if isinstance(step_value, int):
            td = pd.Timedelta(hours=step_value)
        elif isinstance(step_value, str) and step_value.isdigit():
            td = pd.Timedelta(hours=int(step_value))
        elif isinstance(step_value, pd.Timedelta):
            td = step_value
        else:
            # Already in subhourly format or other string format
            return step_value

        # Format as "Xh Ym"
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h{minutes}m"

    def extract(self, request):
        """Extract ``request`` and return the full output document as a dict (CovJSON).

        Buffered compatibility API over :meth:`extract_stream`:
        ``json.dumps(extract(r)).encode() == b"".join(extract_stream(r))``.
        """
        return json.loads(b"".join(self.extract_stream(request)))

    def extract_stream(self, request) -> Iterator[bytes]:
        """Extract ``request`` and yield the encoded output document in pieces.

        The request is parsed and validated before the first piece is produced (errors raise
        immediately); the encoder's opening bytes are yielded before the datacube is touched.
        The top-level ``format`` key selects the encoder (default ``covjson``, see
        :func:`polytope_mars.encoders.get_encoder`).  ``self.timings`` is reset and filled.
        """
        t_start = time.perf_counter()
        self.timings = {}
        extractor = self._prepare_extraction(request)
        self.content_type = extractor.encoder.content_type
        self.file_extension = extractor.encoder.file_extension
        return extractor.stream(t_start)

    def _prepare_extraction(self, request) -> BlockExtractor:
        # request expected in JSON or dict
        if not isinstance(request, dict):
            try:
                request = json.loads(request)
            except ValueError:
                raise ValueError("Request not in JSON format or python dictionary")  # noqa: E501
        else:
            request = copy.deepcopy(request)

        # expect a "feature" key in the request
        try:
            feature_config = request.pop("feature")
            feature_config_copy = feature_config.copy()
        except KeyError:
            raise KeyError("Request does not contain a 'feature' keyword")

        output_format = request.pop("format", "covjson")

        # get feature type
        try:
            feature_type = feature_config["type"]
        except KeyError:
            raise KeyError("The 'feature' does not contain a 'type' keyword")

        if feature_type == "timeseries":
            try:
                if "time_axis" in feature_config:
                    timeseries_type = feature_config["time_axis"]
                if "axes" in feature_config:
                    if feature_config["axes"] == "step":
                        timeseries_type = "step"
                        del feature_config["axes"]
                        del feature_config_copy["axes"]
                        feature_config["time_axis"] = "step"
                        feature_config_copy["time_axis"] = "step"
                    elif "step" in feature_config["axes"]:
                        raise ValueError(
                            "Step axis not supported in 'axes' keyword, must be in 'time_axis'"
                        )  # noqa: E501
                    elif "date" in feature_config["axes"]:
                        raise ValueError(
                            "Date axis not supported in 'axes' keyword, must be in 'time_axis'"
                        )  # noqa: E501
                    elif "month" in feature_config["axes"]:
                        raise ValueError(
                            "Month axis not supported in 'axes' keyword, must be in 'time_axis'"
                        )  # noqa: E501

            except KeyError:
                raise KeyError("The timeseries feature requires a 'time_axis' keyword")  # noqa: E501
        else:
            timeseries_type = None  # noqa: F841

        feature = self._feature_factory(feature_type, feature_config, self.conf)  # noqa: E501

        feature.validate(request, feature_config_copy)

        logging.debug("Unparsed request: %s", request)
        logging.debug("Feature dictionary: %s", feature_config_copy)

        request = feature.parse(request, feature_config_copy)

        role = time_axis_role(request, feature_type)
        header = self._build_header(request, feature_type, feature, role)
        encoder = get_encoder(output_format, self.conf)
        self._check_points_per_field(request, feature)
        self._check_tree_bytes(request, feature)
        return BlockExtractor(self, request, feature_type, feature, role, header, encoder)

    def _build_header(self, request, feature_type, feature, role) -> RequestHeader:
        """RequestHeader from the parsed request alone (no datacube access)."""
        param_db = self.conf.encoders.covjson.param_db
        ids = []
        for p in str(request.get("param", "")).split("/"):
            if not p:
                continue
            try:
                int(p)
            except ValueError:
                p = get_param_ids(param_db)[p]
            if str(p) not in ids:
                ids.append(str(p))
        # Legacy emitted parameters in the tree's param order: FDB axis values sorted as strings.
        ids.sort()
        domain_type = feature.coverage_type()
        if domain_type == "shapefile":
            domain_type = "MultiPoint"
        mars_metadata = {k: str(v) for k, v in request.items() if "/" not in str(v)}
        probe = plan_class(feature_type, domain_type, role)
        extra = {}
        if probe is TimeSeriesReforecastPlan and request.get("stream") == "efas":
            extra["pointseries_order"] = "series_major"
        return RequestHeader(
            feature_type=feature_type,
            domain_type=domain_type,
            time_axis=role,
            parameters=build_parameters(ids, param_db),
            mars_metadata=mars_metadata,
            referencing_coordinates=referencing_coordinates(domain_type, feature_type, role),
            extra=extra,
        )

    def _check_points_per_field(self, request, feature):
        limit = self.conf.limits.max_points_per_field
        if limit is None:
            return
        estimate = estimate_points_per_field(feature, self.conf.options)
        if estimate is not None and estimate > limit:
            raise ValueError(
                f"The requested {feature.name()} covers about {int(estimate)} grid points per field, more than the "
                f"limit of {limit}; request a smaller area"
            )

    def _check_tree_bytes(self, request, feature):
        """Refuse a request whose tree alone would exhaust the pod, before anything is sliced.

        polytope-feature gives every value of a branching axis its own node, spatial sub-tree and
        slice, so the tree grows with the product of those axes' value counts: "Europe hourly for a
        month" on a merged date/time axis is 720 sub-trees of ~480k points, an 8 GB tree built before
        the first gribjump call.  :func:`polytope_mars.limits.estimate_tree_bytes` prices that from
        the request alone; the exact size is checked again after ``prepare``
        (:meth:`polytope_mars.extract.BlockExtractor._prepare`).
        """
        limit = tree_byte_limit(self.conf.limits)
        if limit is None:
            return
        estimate = estimate_tree_bytes(request, feature, self.conf.options, self.conf.limits.bytes_per_point_tree)
        if estimate is None or estimate <= limit:
            return
        branches = estimate_tree_branches(request, self.conf.options)
        points = int(estimate_points_per_field(feature, self.conf.options) or 0)
        shape = (
            f"{branches} separate branches (dates, times or other uncompressed axis values) of about "
            f"{points} grid points each"
            if branches > 1
            else f"about {points} grid points"
        )
        advice = "request fewer dates and times per request" if branches > 1 else "request a smaller area"
        raise ValueError(
            f"The request tree alone would need about {format_bytes(estimate)} ({shape}), "
            f"more than the limit of {format_bytes(limit)}; {advice}"
        )

    @staticmethod
    def _default_gribjump():
        return gj.GribJump()

    def _create_base_shapes(self, request: dict, feature_type) -> List[shapes.Shape]:
        base_shapes = []

        # climate-dt / class=ng: date and time are independent axes for every feature type.
        # The deployment un-merges them in the datacube's axis_config (the fe-worker's
        # unmerge_date_time_options), so the request has to address them as separate axes here.
        if ("dataset" in request and request["dataset"] == "climate-dt") or request["class"] == "ng":
            for k, v in request.items():
                split = str(v).split("/")

                if k == "param":
                    try:
                        int(split[0])
                    except:  # noqa: E722
                        new_split = []
                        for s in split:
                            new_split.append(get_param_ids(self.conf.encoders.covjson.param_db)[s])  # noqa: E501
                        split = new_split

                # ALL -> All
                if len(split) == 1 and split[0] == "ALL":
                    base_shapes.append(shapes.All(k))

                # month / year axes: values are always passed as integers
                elif k in ("month", "year"):
                    # Single integer value -> Select
                    if len(split) == 1:
                        base_shapes.append(shapes.Select(k, [int(split[0])]))

                    # Range a/to/b -> Span with integer bounds
                    elif len(split) == 3 and split[1] == "to":
                        base_shapes.append(shapes.Span(k, lower=int(split[0]), upper=int(split[2])))

                    # Range a/to/b/by/step -> Select of integers
                    elif "by" in split:
                        step = int(split[-1])
                        expansion = list(range(int(split[0]), int(split[2]) + 1, step))
                        base_shapes.append(shapes.Select(k, expansion))

                    # List of individual integer values -> Select
                    else:
                        base_shapes.append(shapes.Select(k, [int(s) for s in split]))

                # Single value -> Select
                elif len(split) == 1:
                    if k == "date":
                        split[0] = pd.Timestamp(split[0])
                    if k == "time":
                        split[0] = convert_timestamp(split[0])
                    if k == "step" and self._has_subhourly_step_transform():
                        split = [self._format_step_as_subhourly(split[0])]
                    base_shapes.append(shapes.Select(k, split))

                # Range a/to/b, "by" not supported -> Span
                elif len(split) == 3 and split[1] == "to":
                    # if date then only get time of dates in span not
                    # all in times within date
                    if k == "date":
                        start = pd.Timestamp(split[0])
                        end = pd.Timestamp(split[2])
                        base_shapes.append(shapes.Span(k, lower=start, upper=end))
                    elif k == "time":
                        start = convert_timestamp(split[0])
                        end = convert_timestamp(split[2])
                        base_shapes.append(shapes.Span(k, lower=start, upper=end))
                    elif k == "step" and self._has_subhourly_step_transform():
                        # Convert step range bounds to subhourly format
                        lower = self._format_step_as_subhourly(split[0])
                        upper = self._format_step_as_subhourly(split[2])
                        base_shapes.append(shapes.Span(k, lower=lower, upper=upper))
                    else:
                        base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))  # noqa: E501

                elif "by" in split:
                    if split[-1] == "1":
                        if k == "date":
                            start = pd.Timestamp(split[0])
                            end = pd.Timestamp(split[2])
                            base_shapes.append(shapes.Span(k, lower=start, upper=end))
                        elif k == "time":
                            start = convert_timestamp(split[0])
                            end = convert_timestamp(split[2])
                            base_shapes.append(shapes.Span(k, lower=start, upper=end))
                        elif k == "step" and self._has_subhourly_step_transform():
                            # Convert step range bounds to subhourly format
                            lower = self._format_step_as_subhourly(split[0])
                            upper = self._format_step_as_subhourly(split[2])
                            base_shapes.append(shapes.Span(k, lower=lower, upper=upper))
                        else:
                            base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))  # noqa: E501
                    else:
                        if k == "date":
                            start = pd.Timestamp(split[0])
                            end = pd.Timestamp(split[2])
                            timestamps = pd.date_range(start=start, end=end, freq=f"{split[-1]}D")
                            base_shapes.append(shapes.Select(k, timestamps.tolist()))
                        elif k == "time":
                            start = convert_timestamp(split[0])
                            end = convert_timestamp(split[2])
                            times = pd.date_range(start=start, end=end, freq=time_step_to_freq(split[-1]))
                            base_shapes.append(shapes.Select(k, times.strftime("%H:%M:%S").tolist()))
                            # base_shapes.append(shapes.Span(k, lower=start, upper=end))
                            # base_shapes.append(shapes.Span(k, lower=start, upper=end))
                        # raise ValueError("Ranges with step-size specified with 'by' keyword is not supported")  # noqa: E501

                # List of individual values -> Union of Selects
                else:
                    if k == "date":
                        dates = []
                        for s in split:
                            dates.append(pd.Timestamp(s))
                        split = dates
                    if k == "time":
                        times = []
                        for s in split:
                            times.append(convert_timestamp(s))
                        split = times
                    if k == "step" and self._has_subhourly_step_transform():
                        split = [self._format_step_as_subhourly(s) for s in split]
                    base_shapes.append(shapes.Select(k, split))
        else:
            # TODO: when has_hdate, "date" stays a plain string (not cast to pd.Timestamp).
            # Need to check if polytope can handle that or if we need a type_change config for date.
            has_hdate = "hdate" in request

            # All class=ce (EFAS) data keeps "date", "hdate" and "time" as
            # independent axes for every feature type (date/hdate ranges become
            # Spans, times become their own Select), mirroring the climate-dt
            # date/time handling: the datacube axes are separate, so the shapes
            # select them separately.
            separate_datetime = request.get("class") == "ce"

            # When the time axis is month or year, there is no "date" key in
            # the request – "time" may also be absent.  Only pop "time" when it
            # is actually present so we don't break month/year requests.  For
            # separate-datetime (class=ce), leave "time" in the request so it is
            # processed as its own independent axis below.
            time = []
            if "time" in request and not separate_datetime:
                time = request.pop("time").replace(":", "")
                time = time.split("/")
                if "to" in time:
                    start = convert_timestamp(time[0])
                    end = convert_timestamp(time[2])
                    if "by" in time:
                        times = pd.date_range(start=start, end=end, freq=time_step_to_freq(time[-1]))
                    else:
                        times = pd.date_range(start=start, end=end, freq="1h")
                    time = times.strftime("%H:%M:%S").tolist()

            for k, v in request.items():
                split = str(v).split("/")

                if k == "param":
                    try:
                        int(split[0])
                    except:  # noqa: E722
                        new_split = []
                        for s in split:
                            new_split.append(get_param_ids(self.conf.encoders.covjson.param_db)[s])  # noqa: E501
                        split = new_split

                # class=ce: keep date/hdate/time as independent axes
                # (date/hdate ranges -> Span, time -> its own Select), mirroring
                # the climate-dt date/time handling above.
                if separate_datetime and k in ("date", "hdate", "time"):
                    if len(split) == 1 and split[0] == "ALL":
                        base_shapes.append(shapes.All(k))
                    elif len(split) == 1:
                        if k in ("date", "hdate"):
                            base_shapes.append(shapes.Select(k, [pd.Timestamp(split[0])]))
                        else:
                            base_shapes.append(shapes.Select(k, [convert_timestamp(split[0])]))
                    elif len(split) == 3 and split[1] == "to":
                        if k in ("date", "hdate"):
                            base_shapes.append(
                                shapes.Span(
                                    k,
                                    lower=pd.Timestamp(split[0]),
                                    upper=pd.Timestamp(split[2]),
                                )
                            )
                        else:
                            base_shapes.append(
                                shapes.Span(
                                    k,
                                    lower=convert_timestamp(split[0]),
                                    upper=convert_timestamp(split[2]),
                                )
                            )
                    elif "by" in split:
                        if split[-1] == "1":
                            if k in ("date", "hdate"):
                                base_shapes.append(
                                    shapes.Span(
                                        k,
                                        lower=pd.Timestamp(split[0]),
                                        upper=pd.Timestamp(split[2]),
                                    )
                                )
                            else:
                                base_shapes.append(
                                    shapes.Span(
                                        k,
                                        lower=convert_timestamp(split[0]),
                                        upper=convert_timestamp(split[2]),
                                    )
                                )
                        else:
                            if k in ("date", "hdate"):
                                timestamps = pd.date_range(
                                    start=pd.Timestamp(split[0]),
                                    end=pd.Timestamp(split[2]),
                                    freq=f"{split[-1]}D",
                                )
                                base_shapes.append(shapes.Select(k, timestamps.tolist()))
                            else:
                                times = pd.date_range(
                                    start=convert_timestamp(split[0]),
                                    end=convert_timestamp(split[2]),
                                    freq=time_step_to_freq(split[-1]),
                                )
                                base_shapes.append(shapes.Select(k, times.strftime("%H:%M:%S").tolist()))
                    else:
                        if k in ("date", "hdate"):
                            base_shapes.append(shapes.Select(k, [pd.Timestamp(s) for s in split]))
                        else:
                            base_shapes.append(shapes.Select(k, [convert_timestamp(s) for s in split]))
                    continue

                # ALL -> All
                if len(split) == 1 and split[0] == "ALL":
                    base_shapes.append(shapes.All(k))

                # month / year axes: values are always passed as integers
                elif k in ("month", "year"):
                    # Single integer value -> Select
                    if len(split) == 1:
                        base_shapes.append(shapes.Select(k, [int(split[0])]))

                    # Range a/to/b -> Span with integer bounds
                    elif len(split) == 3 and split[1] == "to":
                        base_shapes.append(shapes.Span(k, lower=int(split[0]), upper=int(split[2])))

                    # Range a/to/b/by/step -> Select of integers
                    elif "by" in split:
                        step = int(split[-1])
                        expansion = list(range(int(split[0]), int(split[2]) + 1, step))
                        base_shapes.append(shapes.Select(k, expansion))

                    # List of individual integer values -> Select
                    else:
                        base_shapes.append(shapes.Select(k, [int(s) for s in split]))

                # Single value -> Select
                elif len(split) == 1:
                    if k == "hdate" or (k == "date" and not has_hdate):
                        if int(split[0]) < 0:
                            split[0] = str(
                                (
                                    datetime.datetime.now() + datetime.timedelta(days=int(split[0]))
                                ).strftime(  # noqa: E501
                                    "%Y%m%d"
                                )  # noqa: E501
                            )
                        new_split = []
                        for t in time:
                            new_split.append(pd.Timestamp(split[0] + "T" + t))
                        split = new_split
                    elif k == "step" and self._has_subhourly_step_transform():
                        # Convert step to subhourly format if transform is configured
                        split = [self._format_step_as_subhourly(split[0])]
                    base_shapes.append(shapes.Select(k, split))

                # Range a/to/b, "by" not supported -> Span
                elif len(split) == 3 and split[1] == "to":
                    # if date then only get time of dates in span not
                    # all in times within date
                    if k == "hdate" or (k == "date" and not has_hdate):
                        start = pd.Timestamp(split[0] + "T" + time[0])
                        end = pd.Timestamp(split[2] + "T" + time[-1])
                        dates = []
                        for s in pd.date_range(start, end):
                            for t in time:
                                dates.append(pd.Timestamp(s.strftime("%Y%m%d") + "T" + t))
                        base_shapes.append(shapes.Select(k, dates))
                    elif k == "step" and self._has_subhourly_step_transform():
                        # Convert step range bounds to subhourly format
                        lower = self._format_step_as_subhourly(split[0])
                        upper = self._format_step_as_subhourly(split[2])
                        base_shapes.append(shapes.Span(k, lower=lower, upper=upper))
                    else:
                        base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))  # noqa: E501

                elif "by" in split:
                    if split[-1] == "1":
                        if k == "hdate" or (k == "date" and not has_hdate):
                            start = pd.Timestamp(split[0] + "T" + time[0])
                            end = pd.Timestamp(split[2] + "T" + time[-1])
                            dates = []
                            for s in pd.date_range(start, end):
                                for t in time:
                                    dates.append(pd.Timestamp(s.strftime("%Y%m%d") + "T" + t))
                            base_shapes.append(shapes.Select(k, dates))
                        elif k == "step" and self._has_subhourly_step_transform():
                            # Convert step range bounds to subhourly format
                            lower = self._format_step_as_subhourly(split[0])
                            upper = self._format_step_as_subhourly(split[2])
                            base_shapes.append(shapes.Span(k, lower=lower, upper=upper))
                        else:
                            base_shapes.append(shapes.Span(k, lower=split[0], upper=split[2]))
                    else:
                        if k == "hdate" or (k == "date" and not has_hdate):
                            start = pd.Timestamp(split[0] + "T" + time[0])
                            end = pd.Timestamp(split[2] + "T" + time[-1])
                            dates = []
                            for s in pd.date_range(start, end, freq=f"{split[-1]}D"):
                                for t in time:
                                    dates.append(pd.Timestamp(s.strftime("%Y%m%d") + "T" + t))
                            base_shapes.append(shapes.Select(k, dates))
                        elif k == "step":
                            steps = find_step_intervals(split[0], split[2], split[-1])
                            # If subhourly_step transform is configured, ensure all steps are in subhourly format
                            if self._has_subhourly_step_transform():
                                steps = [self._format_step_as_subhourly(s) for s in steps]
                            base_shapes.append(shapes.Select(k, steps))
                        else:
                            expansion = list(range(int(split[0]), int(split[2]) + 1, int(split[-1])))
                            base_shapes.append(shapes.Select(k, expansion))

                # List of individual values -> Union of Selects
                else:
                    if k == "hdate" or (k == "date" and not has_hdate):
                        dates = []
                        for s in split:
                            for t in time:
                                dates.append(pd.Timestamp(s + "T" + t))
                        split = dates
                    elif k == "step" and self._has_subhourly_step_transform():
                        # Convert each step value to subhourly format if transform is configured
                        split = [self._format_step_as_subhourly(s) for s in split]
                    base_shapes.append(shapes.Select(k, split))

        return base_shapes

    def _feature_factory(self, feature_name, feature_config, config=None):
        feature_class = features.get(feature_name)
        if feature_class:
            return feature_class(feature_config, config)
        else:
            raise NotImplementedError(f"Feature '{feature_name}' not found")

    def _add_timing(self, key, seconds):
        # Accumulates, so split requests (several retrieve_data calls) report totals.
        self.timings[key] = self.timings.get(key, 0.0) + round(seconds * 1000, 3)
