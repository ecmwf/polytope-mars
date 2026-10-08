"""Which field groups a request produces, in which order, and their ``t`` / ``mars:metadata``.

The legacy covjsonkit encoders each walked the result tree with their own rules (``from_polytope``,
``from_polytope_reforecast``, ``from_polytope_step``, ``from_polytope_month``, per feature class).  This
module reproduces their *output* rules on top of a structural view of the sliced tree (:class:`TreeInfo`),
so the extraction loop can emit :class:`~polytope_mars.blocks.FieldGroup` objects in legacy coverage order
without fetching any data first.

Terminology:

* a *branch* is a path from the root to a node whose children are spatial; every combination of the
  branch's (compressed) axis values is one field.  A prepared tree holds one array-backed bulk node per
  spatial sub-tree (:mod:`polytope_mars.bulk_tree`), so a branch has as many spatial children as it has
  sub-trees -- usually one -- and nothing below them;
* *group axes* are the axes whose values distinguish field groups (coverages for MultiPoint); the remaining
  axes inside a group are ``param`` and, unless the plan splits levels into groups, ``levelist``;
* a *plan* (one per legacy encoder method) orders the groups and computes their ``t`` and metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any

import pandas as pd
from polytope_feature.datacube.tensor_index_tree import MergedTensorIndexNode

from .legacy_format import (
    normalize_step_value,
    reforecast_stringify,
    stamp_date_plus_step,
    stamp_date_plus_time,
    step_timedelta,
    time_offset,
    tree_metadata,
)

__all__ = ["Branch", "GroupPlan", "TreeInfo", "analyse_tree", "make_plan", "time_axis_role"]

LATITUDE = "latitude"


def is_spatial(node) -> bool:
    """True for a node holding spatial points: a bulk spatial node, a merged lat/lon leaf, a latitude node.

    Both bulk node kinds subclass ``MergedTensorIndexNode``, so :func:`analyse_tree` stops at them and
    never descends into anything spatial.
    """
    return isinstance(node, MergedTensorIndexNode) or node.axis.name == LATITUDE


@dataclass
class Branch:
    #: ((axis, values), ...) from the root's child down to ``node``
    path: tuple
    #: the node whose children are spatial (one bulk node per spatial sub-tree)
    node: Any

    def axes(self) -> dict:
        return {axis: values for axis, values in self.path}


@dataclass
class TreeInfo:
    branches: list
    #: depth-first (axis, values) of every non-spatial node (input of the legacy metadata walkers)
    nodes: list
    #: axis -> distinct values in depth-first order of first appearance
    values: dict
    #: axis -> number of tree nodes on that axis
    node_count: dict
    #: non-spatial axes in depth-first order of first appearance
    axis_order: list

    def rank(self, axis, value) -> int:
        if value is None:
            return -1
        try:
            return self.values[axis].index(value)
        except (KeyError, ValueError):
            return len(self.values.get(axis, ()))

    def multi(self, axis) -> bool:
        return len(self.values.get(axis, ())) > 1


def analyse_tree(tree) -> TreeInfo:
    """Structural view of a (prepared) tree: branches and axis values, without touching any leaf data."""
    branches, nodes, values, node_count, axis_order = [], [], {}, {}, []

    def visit(node, path):
        spatial = False
        for child in node.children:
            if is_spatial(child):
                spatial = True
                continue
            name = child.axis.name
            vals = tuple(child.values)
            nodes.append((name, vals))
            node_count[name] = node_count.get(name, 0) + 1
            if name not in values:
                values[name] = []
                axis_order.append(name)
            seen = values[name]
            for v in vals:
                if v not in seen:
                    seen.append(v)
            if len(child.children) != 0:
                visit(child, path + ((name, vals),))
        if spatial:
            branches.append(Branch(path, node))

    visit(tree, ())
    return TreeInfo(branches, nodes, values, node_count, axis_order)


def spatial_children(branch_node):
    return [c for c in branch_node.children if is_spatial(c)]


def year_month(g) -> str:
    """Legacy ``walk_tree_month`` key ``"YYYY-MM"`` of a group (year and month are int axes)."""
    year, month = g.path.get("year"), g.path.get("month")
    if not isinstance(year, int) or not isinstance(month, int):
        raise ValueError(f"Monthly data needs integer year and month axes, got year={year!r} month={month!r}")
    return f"{year:04d}-{month:02d}"


def time_axis_role(request: dict, feature_type: str) -> str:
    """The legacy ``retrieve_data`` dispatch: which ``from_polytope*`` method encoded this request.

    ``"date"`` = ``from_polytope``, ``"hdate"`` = ``from_polytope_reforecast``, ``"step"`` =
    ``from_polytope_step``, ``"month"`` = ``from_polytope_month``.
    """
    if "dataset" in request:
        if request["dataset"] == "climate-dt":
            if request.get("stream") == "clmn":
                return "month"
            if feature_type in ("timeseries", "polygon"):
                return "step"
        return "date"
    if request["class"] == "ng":
        return "step" if feature_type in ("timeseries", "polygon") else "date"
    if request["class"] == "ce":
        return "hdate"
    return "date"


@dataclass
class GroupPlan:
    """One field group as planned before extraction."""

    #: values of the group axes (raw tree values), in plan.group_axes order (None: axis absent)
    key: tuple
    #: axis -> raw value for every single-valued path axis plus the group axes (first matching branch)
    path: dict
    #: ((axis, value), ...) of the first matching branch in tree order (reforecast metadata)
    path_items: tuple
    #: indexes into TreeInfo.branches, tree order
    branches: list
    #: datacube select dict for this group
    select: dict
    #: raw param values, tree order
    params: list
    #: raw levelist values, tree order ([] when the group has no levelist axis)
    levels: list
    #: filled by the plan
    t: tuple = ()
    mars_metadata: dict = field(default_factory=dict)


def _branch_matches(branch: Branch, select: dict) -> bool:
    axes = branch.axes()
    for axis, value in select.items():
        if axis in axes and value not in axes[axis]:
            return False
    return True


class Plan:
    """Base plan: MultiPoint ``from_polytope`` (one coverage per date, number, step)."""

    domain_type = "MultiPoint"
    time_axis = "date"
    walker = "date"
    #: axes whose order decides the group order (others follow in tree order)
    order_axes: tuple = ("date", "number", "step")
    #: True: levelist is a group axis (one level per group)
    split_levels = False

    def __init__(self, info: TreeInfo, feature_type: str, request: dict):
        self.info = info
        self.feature_type = feature_type
        self.request = request
        self.meta = tree_metadata(info.nodes, self.walker)

    # -- group enumeration -----------------------------------------------------------------------------

    def inner_axes(self) -> set:
        return {"param"} if self.split_levels else {"param", "levelist"}

    def group_axes(self) -> list:
        inner = self.inner_axes()
        return [a for a in self.info.axis_order if a not in inner and self.info.multi(a)]

    def groups(self) -> list:
        axes = self.group_axes()
        groups: dict = {}
        for b_idx, branch in enumerate(self.info.branches):
            bax = branch.axes()
            choices = [bax.get(a, (None,)) for a in axes]
            for key in product(*choices):
                g = groups.get(key)
                if g is None:
                    select = {a: v for a, v in zip(axes, key) if v is not None}
                    path = {a: vals[0] for a, vals in branch.path if len(vals) == 1}
                    path.update(select)
                    items = tuple((a, select.get(a, vals[0])) for a, vals in branch.path)
                    g = groups[key] = GroupPlan(key, path, items, [], select, [], [])
                g.branches.append(b_idx)
                for p in bax.get("param", ()):
                    if p not in g.params:
                        g.params.append(p)
                levels = (g.select["levelist"],) if "levelist" in g.select else bax.get("levelist", ())
                for lev in levels:
                    if lev not in g.levels:
                        g.levels.append(lev)
        out = list(groups.values())
        ranks = {g.key: self.sort_key(g, axes) for g in out}
        out.sort(key=lambda g: ranks[g.key])
        for g in out:
            g.t = self.t(g)
            g.mars_metadata = self.metadata(g)
        return out

    def sort_key(self, g: GroupPlan, axes: list) -> tuple:
        first = [self.info.rank(a, g.path.get(a)) for a in self.order_axes]
        rest = [self.info.rank(a, v) for a, v in zip(axes, g.key) if a not in self.order_axes]
        return tuple(first + rest)

    # -- per-group output values ---------------------------------------------------------------------

    def date_z(self, g) -> str:
        return f"{g.path.get('date')}Z"

    def datetime_z(self, g) -> str:
        """The group's reference datetime: the date node, plus the time node when the axes are separate."""
        time = g.path.get("time")
        if time is None:
            return self.date_z(g)
        return (pd.Timestamp(g.path.get("date")) + time).isoformat() + "Z"

    def t(self, g) -> tuple:
        return (self.datetime_z(g),)

    def number(self, g):
        return g.path.get("number", 0)

    def step(self, g):
        return g.path.get("step", 0)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["step"] = normalize_step_value(self.step(g))
        m["Forecast date"] = self.datetime_z(g)
        return m

    def level_out(self, level):
        """Level as written to the output (composite tuples / levelist axes)."""
        return level

    def header_extra(self) -> dict:
        return {}


class ReforecastPlan(Plan):
    """MultiPoint ``Encoder.from_polytope_reforecast`` (class=ce): one coverage per (hdate|date + time, step, number)."""

    time_axis = "hdate"
    walker = "hdate"
    exclude_meta = ("latitude", "longitude", "hdate", "time", "step", "param", "number", "levelist")

    def ref(self, g) -> pd.Timestamp:
        hdate = g.path.get("hdate", g.path.get("date"))
        return pd.Timestamp(hdate) + time_offset(g.path.get("time"))

    def number(self, g):
        number = g.path.get("number", 0)
        try:
            return int(number)
        except (TypeError, ValueError):
            return number

    def step(self, g):
        return normalize_step_value(g.path.get("step", 0))

    def sort_key(self, g, axes) -> tuple:
        return (self.ref(g), step_timedelta(self.step(g)), self.number(g))

    def t(self, g) -> tuple:
        return ((self.ref(g) + step_timedelta(self.step(g))).isoformat() + "Z",)

    def path_meta(self, g) -> dict:
        return {a: reforecast_stringify(v) for a, v in g.path_items if a not in self.exclude_meta}

    def metadata(self, g) -> dict:
        m = self.path_meta(g)
        m["number"] = self.number(g)
        m["step"] = self.step(g)
        is_ce = g.path.get("class") == "ce"
        if is_ce and g.path.get("stream") == "efas":
            m.pop("date", None)
            m["Forecast date"] = self.ref(g).isoformat() + "Z"
        elif not (is_ce and g.path.get("stream") == "efcl"):
            m["Forecast date"] = self.ref(g).isoformat() + "Z"
        return m

    def level_out(self, level):
        try:
            return int(level)
        except (TypeError, ValueError):
            return level


class StepPlan(Plan):
    """MultiPoint ``Wkt.from_polytope_step`` (climate-dt / ng polygon): one coverage per (time, number, date)."""

    time_axis = "step"
    walker = "step"
    order_axes = ("time", "number", "date")

    def t(self, g) -> tuple:
        time = g.path.get("time", pd.Timedelta(0))
        return (stamp_date_plus_time(self.date_z(g), time),)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        return m


class MonthPlan(Plan):
    """MultiPoint ``from_polytope_month`` (climate-dt clmn): one coverage per (number, year, month)."""

    time_axis = "month"
    walker = "month"
    order_axes = ("number", "year", "month")

    def year_month(self, g) -> str:
        return year_month(g)

    def t(self, g) -> tuple:
        return (f"{self.year_month(g)}-01T00:00:00Z",)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["Forecast date"] = self.t(g)[0]
        return m


# --- point features: one group per time instant; the encoder assembles the series ---------------------


class TimeSeriesDatePlan(Plan):
    """``TimeSeries.from_polytope``: a coverage per (point, date, level, number), t over steps."""

    domain_type = "PointSeries"
    order_axes = ("date", "levelist", "number", "step")
    split_levels = True

    def t(self, g) -> tuple:
        return (stamp_date_plus_step(self.datetime_z(g), self.step(g)),)

    def level(self, g):
        return g.levels[0] if g.levels else 0

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["Forecast date"] = self.datetime_z(g)
        m["levelist"] = self.level(g)
        m.pop("step", None)
        return m


class PositionDatePlan(TimeSeriesDatePlan):
    """``Position.from_polytope``: like TimeSeries but no ``levelist`` in metadata, levels not split."""

    order_axes = ("date", "number", "step")
    split_levels = False

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["Forecast date"] = self.datetime_z(g)
        m.pop("step", None)
        return m


class VerticalProfileDatePlan(Plan):
    """``VerticalProfile.from_polytope``: a coverage per (point, date, number, step), levels on the levelist axis."""

    domain_type = "VerticalProfile"

    def t(self, g) -> tuple:
        return (stamp_date_plus_step(self.datetime_z(g), self.step(g)),)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["Forecast date"] = self.datetime_z(g)
        m["step"] = normalize_step_value(self.step(g))
        return m


class TrajectoryDatePlan(Plan):
    """``Path.from_polytope``: a coverage per (date, number); ``t`` holds the composite time value (the step)."""

    domain_type = "Trajectory"
    order_axes = ("date", "number", "levelist", "step")

    def __init__(self, info, feature_type, request):
        super().__init__(info, feature_type, request)
        # 3-D/4-D paths put levels on separate branches: then each level is its own group.
        self.split_levels = info.node_count.get("levelist", 0) > 1

    def t(self, g) -> tuple:
        return (normalize_step_value(self.step(g)),)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["Forecast date"] = self.datetime_z(g)
        m.pop("levelist", None)
        return m


class TimeSeriesStepPlan(Plan):
    """``TimeSeries/Position.from_polytope_step``: a coverage per (point, level, number), t over (date, time)."""

    domain_type = "PointSeries"
    time_axis = "step"
    walker = "step"
    order_axes = ("levelist", "number", "date", "time")
    split_levels = True

    def t(self, g) -> tuple:
        return (stamp_date_plus_time(self.date_z(g), g.path.get("time", pd.Timedelta(0))),)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        dates = [v for axis, vals in self.info.nodes if axis == "date" for v in vals]
        m["Forecast date"] = f"{dates[-1]}Z" if dates else "None"
        return m


class TimeSeriesMonthPlan(Plan):
    """``TimeSeries/Position.from_polytope_month``: a coverage per (point, level, number), t over months."""

    domain_type = "PointSeries"
    time_axis = "month"
    walker = "month"
    order_axes = ("levelist", "number", "year", "month")
    split_levels = True

    def t(self, g) -> tuple:
        return (f"{year_month(g)}-01T00:00:00Z",)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["levelist"] = g.levels[0] if g.levels else 0
        return m


class VerticalProfileMonthPlan(MonthPlan):
    """``VerticalProfile.from_polytope_month``: a coverage per (point, year-month, number); "Forecast date" is YYYY-MM."""

    domain_type = "VerticalProfile"
    order_axes = ("year", "month", "number")

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m["Forecast date"] = self.year_month(g)
        return m


class TrajectoryMonthPlan(MonthPlan):
    """``Path.from_polytope_month``: a coverage per (year-month, number), composite time = YYYY-MM."""

    domain_type = "Trajectory"
    order_axes = ("year", "month", "number")

    def t(self, g) -> tuple:
        return (self.year_month(g),)

    def metadata(self, g) -> dict:
        m = dict(self.meta)
        m["number"] = self.number(g)
        m.pop("levelist", None)
        return m


class TimeSeriesReforecastPlan(ReforecastPlan):
    """``TimeSeries.from_polytope_reforecast`` (class=ce).

    efcl: every (hdate, time, step) of a point is one series (per level, number), t sorted by valid time;
    efas: one series per forecast run (date + time), coverages ordered run-major then by point;
    other streams: one series per hdate.
    """

    domain_type = "PointSeries"
    split_levels = True

    def stream(self):
        return self.info.values.get("stream", [None])[0]

    def collapse(self) -> bool:
        return self.info.values.get("class", [None])[0] == "ce" and self.stream() == "efcl"

    def forecast(self) -> bool:
        return self.info.values.get("class", [None])[0] == "ce" and self.stream() == "efas"

    def valid(self, g):
        hdate = g.path.get("hdate", g.path.get("date"))
        return pd.Timestamp(
            stamp_date_plus_step(f"{hdate}Z", g.path.get("step", 0), time_offset(g.path.get("time")))[:-1]
        )

    def level(self, g):
        return self.level_out(g.levels[0]) if g.levels else 0

    def series_key(self, g) -> tuple:
        if self.collapse():
            return ()
        if self.forecast():
            return (self.ref(g),)
        return (self.info.rank("hdate", g.path.get("hdate")),)

    def sort_key(self, g, axes) -> tuple:
        tree_order = tuple(self.info.rank(a, v) for a, v in zip(axes, g.key))
        series = self.series_key(g) + (self.info.rank("levelist", g.path.get("levelist")), self.number(g))
        return series + (self.valid(g),) + tree_order

    def t(self, g) -> tuple:
        return (self.valid(g).isoformat() + "Z",)

    def metadata(self, g) -> dict:
        m = self.path_meta(g)
        m["number"] = self.number(g)
        m["levelist"] = self.level(g)
        if self.forecast():
            m.pop("date", None)
            m["Forecast date"] = self.ref(g).isoformat() + "Z"
        elif not self.collapse():
            m["Forecast date"] = pd.Timestamp(g.path.get("hdate", g.path.get("date"))).isoformat() + "Z"
        return m

    def header_extra(self) -> dict:
        return {"pointseries_order": "series_major"} if self.forecast() else {}


class PositionReforecastPlan(ReforecastPlan):
    """``Position.from_polytope_reforecast``: a series per (hdate|date + time, level, number), t = valid times."""

    domain_type = "PointSeries"
    split_levels = True

    def sort_key(self, g, axes) -> tuple:
        level = self.info.rank("levelist", g.path.get("levelist"))
        return (self.ref(g), level, self.number(g), step_timedelta(self.step(g)))

    def metadata(self, g) -> dict:
        m = self.path_meta(g)
        m["number"] = self.number(g)
        m["Forecast date"] = self.ref(g).isoformat() + "Z"
        return m


class VerticalProfileReforecastPlan(ReforecastPlan):
    """``VerticalProfile.from_polytope_reforecast``: a coverage per (point, number, hdate + time, step)."""

    domain_type = "VerticalProfile"

    def sort_key(self, g, axes) -> tuple:
        return tuple(self.info.rank(a, v) for a, v in zip(axes, g.key))


class TrajectoryReforecastPlan(ReforecastPlan):
    """class=ce trajectories went through the MultiPoint reforecast encoder with the Path domain (no t axis)."""

    domain_type = "Trajectory"


_PLANS = {
    ("MultiPoint", "date"): Plan,
    ("MultiPoint", "hdate"): ReforecastPlan,
    ("MultiPoint", "step"): StepPlan,
    ("MultiPoint", "month"): MonthPlan,
    ("timeseries", "date"): TimeSeriesDatePlan,
    ("timeseries", "step"): TimeSeriesStepPlan,
    ("timeseries", "month"): TimeSeriesMonthPlan,
    ("timeseries", "hdate"): TimeSeriesReforecastPlan,
    ("position", "date"): PositionDatePlan,
    ("position", "step"): TimeSeriesStepPlan,
    ("position", "month"): TimeSeriesMonthPlan,
    ("position", "hdate"): PositionReforecastPlan,
    ("verticalprofile", "date"): VerticalProfileDatePlan,
    ("verticalprofile", "step"): VerticalProfileDatePlan,
    ("verticalprofile", "month"): VerticalProfileMonthPlan,
    ("verticalprofile", "hdate"): VerticalProfileReforecastPlan,
    ("trajectory", "date"): TrajectoryDatePlan,
    ("trajectory", "step"): TrajectoryDatePlan,
    ("trajectory", "month"): TrajectoryMonthPlan,
    ("trajectory", "hdate"): TrajectoryReforecastPlan,
}


def plan_class(feature_type: str, domain_type: str, role: str):
    key = ("MultiPoint" if domain_type == "MultiPoint" else feature_type, role)
    try:
        return _PLANS[key]
    except KeyError:
        raise NotImplementedError(f"No coverage layout for feature {feature_type!r} with time axis {role!r}") from None


def make_plan(info: TreeInfo, feature_type: str, domain_type: str, role: str, request: dict) -> Plan:
    return plan_class(feature_type, domain_type, role)(info, feature_type, request)
