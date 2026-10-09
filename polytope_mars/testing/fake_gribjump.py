"""In-memory stand-in for ``pygribjump.GribJump``.

It drives the real ``polytope_feature`` ``FDBDatacube`` (and therefore the whole
``PolytopeMars.extract`` pipeline) without an FDB:

* ``axes(partial_request)`` answers from a declared axis table.  The table is
  either one ``{axis: [values]}`` dict or a list of such dicts ("sub-cubes",
  e.g. one per stream/levtype, like the FDB schema branches).  Sub-cubes that
  contradict the partial request are ignored; the remaining ones are narrowed
  to the partial request's values and merged.
* ``extract(requests)`` takes the list of ``(path, ranges, grid_hash)`` tuples
  built by ``FDBDatacube.get`` and returns, per request, an object with
  ``.values`` = one float64 ``np.ndarray`` per ``(start, end)`` range.
  When a path declared missing is part of the call, the default
  (``missing_mode="raise"``) does what the real (remote) gribjump does: the
  whole call raises ``pygribjump.GribJumpException`` with a ``DataNotFound.
  Matched <n> fields but <m> were requested.`` message.  With
  ``missing_mode="empty"`` the missing path's result has ``.values == []``
  instead (the other pygribjump reporting of a MARS path with no GRIB message).

Values are a deterministic function of the path and the absolute grid index
(:func:`expected_values`: ``field_id(path) * 1e5 + 1e-3 * index``), so a value
delivered to the wrong tree node, or in the wrong order, is detectable, and
:func:`decode_value` recovers ``(field_id, index)`` from any emitted value.
Indices can be declared bitmap-missing; those come back as NaN.
"""

from __future__ import annotations

import zlib
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

__all__ = [
    "FakeExtractResult",
    "FakeGribJump",
    "GribJumpException",
    "base_value",
    "decode_value",
    "expected_values",
    "field_id",
]


class _StandInGribJumpException(RuntimeError):
    """Stand-in for ``pygribjump.GribJumpException`` when pygribjump cannot be imported."""


_StandInGribJumpException.__name__ = _StandInGribJumpException.__qualname__ = "GribJumpException"


def _gribjump_exception_class() -> type:
    try:
        import pygribjump

        return pygribjump.GribJumpException
    except Exception:  # pragma: no cover - pygribjump or its C library not installed
        return _StandInGribJumpException


#: ``pygribjump.GribJumpException``, or a stand-in of the same name and base class.
GribJumpException: type = _gribjump_exception_class()

#: Values of ``FakeGribJump(missing_mode=...)``.
MISSING_MODES = ("raise", "empty")

#: Spacing between the value of consecutive grid indices of one field.
INDEX_SCALE = 1e-3
#: Spacing between the base values of two fields; larger than INDEX_SCALE * (largest grid size).
FIELD_SCALE = 1e5


def _path_key(path: Mapping) -> str:
    return ",".join(f"{k}={path[k]}" for k in sorted(path))


def field_id(path: Mapping) -> int:
    """Small integer id of a field, derived from the sorted ``key=value`` items of its MARS path."""
    return zlib.crc32(_path_key(path).encode("utf-8", errors="replace")) % 999983


def base_value(path: Mapping) -> float:
    """Value of grid index 0 of the field ``path``."""
    return field_id(path) * FIELD_SCALE


def expected_values(path: Mapping, indices) -> np.ndarray:
    """Values the default fake returns for ``indices`` (absolute grid indices) of the field ``path``."""
    return base_value(path) + INDEX_SCALE * np.asarray(indices, dtype=np.float64)


def decode_value(value: float) -> tuple[int, int]:
    """Inverse of :func:`expected_values`: ``(field_id, grid index)``. ``value`` must be finite."""
    fid = int(value // FIELD_SCALE)
    return fid, int(round((value - fid * FIELD_SCALE) / INDEX_SCALE))


class FakeExtractResult:
    """Mimics ``pygribjump.ExtractionResult`` (0.12.0.26).

    ``values_flat`` is one contiguous float64 buffer for the whole field and ``values`` is a list of
    *views* into it, one per requested range -- the layout pygribjump exposes, and the reason a
    consumer reading ``values_flat``
    (``polytope_feature.datacube.backends.fdb.field_values_flat``) pays nothing per range while one
    reading ``values`` pays a numpy object per range.  A field gribjump has no message for has an
    empty buffer and no views.

    Built from the buffer and the length of each range, never from one array per range: a HEALPix
    field of a Europe box has ~300k ranges, and synthesising an array for each of them cost the
    measurements more than everything they were measuring (MEASUREMENTS.md).
    """

    __slots__ = ("_lengths", "_views", "values_flat")

    def __init__(self, values_flat, lengths=None):
        self._views = None
        self.values_flat = np.asarray(values_flat, dtype=np.float64)
        if lengths is None:
            lengths = [self.values_flat.size] if self.values_flat.size else []
        self._lengths = list(lengths)

    @property
    def values(self) -> list:
        """The per-range views, built on first access (pygribjump builds them on access too)."""
        if self._views is None:
            views, at = [], 0
            for n in self._lengths:
                views.append(self.values_flat[at : at + n])  # noqa: E203
                at += n
            self._views = views
        return self._views


def _range_indices(ranges) -> tuple:
    """``(grid indices of every requested range, one length per range)``, in request order.

    Vectorised over the ranges: a HEALPix field of a Europe box is ~300k ranges of ~1.6 points, and
    an array per range would cost more than the field itself.  Index ``i`` of the flat buffer
    belongs to the range whose values start at ``start`` and whose first element sits at ``offset``,
    so its grid index is ``start - offset + i``.
    """
    bounds = np.asarray(ranges, dtype=np.int64).reshape(-1, 2)
    starts, lengths = bounds[:, 0], bounds[:, 1] - bounds[:, 0]
    total = int(lengths.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64), lengths.tolist()
    offsets = np.concatenate(([0], np.cumsum(lengths)[:-1]))
    indices = np.repeat(starts - offsets, lengths) + np.arange(total, dtype=np.int64)
    return indices, lengths.tolist()


def _matches(path: Mapping, partial: Mapping) -> bool:
    return all(str(path.get(k)) == str(v) for k, v in partial.items())


class FakeGribJump:
    """Fake ``pygribjump.GribJump``.

    :param axes_table: ``{axis: [str values]}`` or a list of those (sub-cubes).
    :param data: optional ``callable(path: dict, indices: np.ndarray) -> np.ndarray`` overriding
        :func:`expected_values`.
    :param missing: partial MARS paths (dicts); any extracted path matching one of them is a
        missing field (no GRIB message).
    :param missing_mode: ``"raise"`` (default, like the remote gribjump): an ``extract`` call
        that includes a missing field raises :class:`GribJumpException` (``DataNotFound``) and
        returns nothing; ``"empty"``: the missing field's result has ``.values == []``.
    :param nan_indices: absolute grid indices that are bitmap-missing (NaN) in every field, or a
        callable ``(path: dict, indices: np.ndarray) -> bool mask`` for per-field bitmaps.

    ``polytope_feature.Datacube.create`` dispatches on ``type(datacube).__name__ == "GribJump"``,
    so the class ``__name__`` is ``"GribJump"`` (its ``__qualname__`` stays ``FakeGribJump``).
    """

    def __init__(
        self,
        axes_table,
        data: Callable | None = None,
        missing: Iterable[Mapping] | None = None,
        nan_indices: Iterable[int] | Callable | None = None,
        missing_mode: str = "raise",
    ):
        if missing_mode not in MISSING_MODES:
            raise ValueError(f"missing_mode must be one of {MISSING_MODES}, got {missing_mode!r}")
        cubes = [axes_table] if isinstance(axes_table, Mapping) else list(axes_table)
        self.cubes = [{k: [str(v) for v in vals] for k, vals in cube.items()} for cube in cubes]
        self.data = data or expected_values
        self.missing = [dict(m) for m in (missing or [])]
        self.missing_mode = missing_mode
        if nan_indices is None or callable(nan_indices):
            self._nan = nan_indices
        else:
            self._nan = np.unique(np.asarray(list(nan_indices), dtype=np.int64))
        # Counters, cheap enough to keep on for measurements.
        self.n_axes_calls = 0
        self.n_extract_calls = 0
        #: extract calls that raised DataNotFound (missing_mode="raise")
        self.n_data_not_found = 0
        self.n_requests = 0
        self.n_values = 0
        #: field_id -> MARS path of every field extracted (missing ones included).
        self.fields: dict[int, dict] = {}

    # -- pygribjump API --------------------------------------------------------------------------

    def axes(self, partial_request: Mapping, level: int = 3, ctx=None) -> dict[str, list[str]]:
        """Axes of the sub-cubes compatible with ``partial_request``, narrowed to its values.

        Keys come back sorted: gribjump builds the answer from a ``std::map``, and the key order
        decides the axis order of polytope's request tree (and thus the leaf value layout).
        Values are deduplicated but not sorted (gribjump uses an ``unordered_set``; polytope sorts).
        """
        self.n_axes_calls += 1
        out: dict[str, list[str]] = {}
        for cube in self.cubes:
            narrowed = {}
            for axis, values in cube.items():
                if axis in partial_request:
                    wanted = [str(v) for v in _as_list(partial_request[axis])]
                    values = [v for v in values if v in wanted]
                    if not values:
                        break
                narrowed[axis] = values
            else:
                for axis, values in narrowed.items():
                    merged = out.setdefault(axis, [])
                    merged.extend(v for v in values if v not in merged)
        return {axis: out[axis] for axis in sorted(out)}

    def extract(self, requests: Sequence, ctx=None) -> list[FakeExtractResult]:
        self.n_extract_calls += 1
        requests = list(requests)
        if self.missing_mode == "raise":
            self._raise_if_missing(requests)
        out = []
        for request in requests:
            path, ranges = request[0], request[1]
            self.n_requests += 1
            self.fields[field_id(path)] = dict(path)
            if self._is_missing(path):
                out.append(FakeExtractResult(np.empty(0)))
                continue
            idx, lengths = _range_indices(ranges)
            arr = np.asarray(self.data(path, idx), dtype=np.float64)
            if callable(self._nan):
                arr[np.asarray(self._nan(path, idx), dtype=bool)] = np.nan
            elif self._nan is not None and self._nan.size:
                arr[np.isin(idx, self._nan)] = np.nan
            self.n_values += int(idx.size)
            out.append(FakeExtractResult(arr, lengths))
        return out

    # -- missing fields -------------------------------------------------------------------------------

    def _is_missing(self, path: Mapping) -> bool:
        return any(_matches(path, m) for m in self.missing)

    def _raise_if_missing(self, requests: list) -> None:
        """Raise like gribjump's ``gribjump_extract`` when the union of ``requests`` lacks fields.

        The server takes the union of all requested paths, matches it against its index and raises
        when it finds fewer fields than requested; nothing of the call is returned.
        """
        requested, matched = set(), set()
        for request in requests:
            path = request[0]
            key = _path_key(path)
            requested.add(key)
            self.fields[field_id(path)] = dict(path)
            if not self._is_missing(path):
                matched.add(key)
        if len(matched) == len(requested):
            return
        self.n_requests += len(requests)
        self.n_data_not_found += 1
        raise GribJumpException(
            "Error in function 'gribjump_extract': GribJumpException: DataNotFound. "
            f"Matched {len(matched)} fields but {len(requested)} were requested.\n"
            f"Union request: {union_request([r[0] for r in requests])}"
        )


def union_request(paths: Iterable[Mapping]) -> str:
    """``retrieve,key=v1/v2,...`` of the union of ``paths`` (keys sorted, values in first-seen order)."""
    union: dict[str, list[str]] = {}
    for path in paths:
        for k, v in path.items():
            vals = union.setdefault(str(k), [])
            if str(v) not in vals:
                vals.append(str(v))
    return ",".join(["retrieve"] + [f"{k}={'/'.join(union[k])}" for k in sorted(union)])


FakeGribJump.__name__ = "GribJump"


def _as_list(value) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return str(value).split("/")
