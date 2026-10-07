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
  ``.values`` = one float64 ``np.ndarray`` per ``(start, end)`` range, or
  ``.values == []`` for a path declared missing (that is how gribjump reports a
  MARS path with no GRIB message).

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

__all__ = ["FakeExtractResult", "FakeGribJump", "base_value", "decode_value", "expected_values", "field_id"]

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
    """Mimics ``pygribjump.ExtractionResult``: ``values`` is a list of arrays, one per requested range."""

    __slots__ = ("values",)

    def __init__(self, values: list):
        self.values = values


def _matches(path: Mapping, partial: Mapping) -> bool:
    return all(str(path.get(k)) == str(v) for k, v in partial.items())


class FakeGribJump:
    """Fake ``pygribjump.GribJump``.

    :param axes_table: ``{axis: [str values]}`` or a list of those (sub-cubes).
    :param data: optional ``callable(path: dict, indices: np.ndarray) -> np.ndarray`` overriding
        :func:`expected_values`.
    :param missing: partial MARS paths (dicts); any extracted path matching one of them returns
        ``.values == []`` (field missing).
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
    ):
        cubes = [axes_table] if isinstance(axes_table, Mapping) else list(axes_table)
        self.cubes = [{k: [str(v) for v in vals] for k, vals in cube.items()} for cube in cubes]
        self.data = data or expected_values
        self.missing = [dict(m) for m in (missing or [])]
        if nan_indices is None or callable(nan_indices):
            self._nan = nan_indices
        else:
            self._nan = np.unique(np.asarray(list(nan_indices), dtype=np.int64))
        # Counters, cheap enough to keep on for measurements.
        self.n_axes_calls = 0
        self.n_extract_calls = 0
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
        out = []
        for request in requests:
            path, ranges = request[0], request[1]
            self.n_requests += 1
            self.fields[field_id(path)] = dict(path)
            if any(_matches(path, m) for m in self.missing):
                out.append(FakeExtractResult([]))
                continue
            values = []
            for start, end in ranges:
                idx = np.arange(start, end, dtype=np.int64)
                arr = np.asarray(self.data(path, idx), dtype=np.float64)
                if callable(self._nan):
                    arr[np.asarray(self._nan(path, idx), dtype=bool)] = np.nan
                elif self._nan is not None and self._nan.size:
                    arr[np.isin(idx, self._nan)] = np.nan
                values.append(arr)
                self.n_values += int(end - start)
            out.append(FakeExtractResult(values))
        return out


FakeGribJump.__name__ = "GribJump"


def _as_list(value) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return str(value).split("/")
