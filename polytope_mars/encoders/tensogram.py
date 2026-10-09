"""Tensogram encoder for the polytope-mars block stream (``format: tensogram``).

Tensogram (https://github.com/ecmwf/tensogram, package ``tensogram``) is a binary N-tensor message
format with CBOR metadata attached to each tensor and its own per-tensor compression.  A ``.tgm``
stream is a concatenation of self-describing messages, which is what makes it usable here: the
extraction loop hands this encoder one block at a time and every message can be written and released
before the next block arrives.

This module is a thin adapter: it reads the block IR structurally (:mod:`polytope_mars.blocks`) and
calls ``tensogram.encode`` once per message.  Nothing in tensogram is changed or subclassed.

Format definition
=================

One request is one message stream.  Messages are emitted in this order:

1. a **header message** with no data objects, carrying the request-level metadata;
2. per coverage (one field group), one or more **coverage messages** carrying the coverage's
   coordinates and values as data objects;
3. a **trailer message** with no data objects, carrying the coverage and message counts.

Reading it back::

    for meta, objects in tensogram.iter_messages(open("result.tgm", "rb").read()):
        ...                       # or tensogram.TensogramFile.open("result.tgm")

Message-level metadata (``_extra_``, i.e. ``tensogram.decode(msg).metadata.extra``) is flat, as in
ecmwf/polytope-mars#100, which first described a tensogram layout for feature extraction:

=========================== ===============================================================
``source``                  always ``"polytope-mars"``
``schema``                  always ``"polytope-feature-extraction"``
``schema_version``          this definition's version, currently 1
``feature_type``            the request's feature type ("boundingbox", "timeseries", ...)
``domain_type``             "MultiPoint" | "PointSeries" | "VerticalProfile" | "Trajectory"
``time_axis``               the request key the ``time_values`` come from: date/hdate/step/month
``missing_value``           always ``"nan"``: a missing value is NaN in the values tensor
=========================== ===============================================================

The header message adds ``parameters``, a list of ``{id, shortname, name, unit, description}`` in
emission order (every requested parameter, including ones no coverage has data for), and ``mars``, the
request keys common to every coverage.  The trailer message adds ``end_of_stream: true``,
``n_coverages`` and ``n_messages`` (the whole stream, header and trailer included).

A coverage message adds:

=========================== ===============================================================
``coverage``                0-based coverage index in the stream
``part``                    0-based message index within that coverage
``mars``                    the coverage's MARS keys (CovJSON's ``mars:metadata``)
``time_values``             the coverage's time axis, as CovJSON's ``t``: ISO-8601 'Z' datetimes,
                            or the forecast steps of a trajectory
``levels``                  the coverage's ``levelist`` values, ``[]`` when it has none
``n_points``                points per (parameter, level) of the coverage
=========================== ===============================================================

Per-object metadata (``base[i]``) describes one tensor, always 1-D ``float64``:

=========================== ===============================================================
``name``                    ``"latitude"``, ``"longitude"``, or the parameter's shortname
``role``                    ``"coordinate"`` or ``"data"``
``units``                   ``"degrees_north"`` / ``"degrees_east"`` / the parameter's unit
``description``             the parameter's description (``"data"`` objects only)
``mars``                    ``{"param": id}`` plus ``{"levelist": level}`` when the coverage
                            has levels (``"data"`` objects only)
``point_offset``            index, within the coverage's points, of this tensor's first value
``n_values``                length of this tensor
=========================== ===============================================================

A consumer rebuilds a coverage by collecting the messages with one ``coverage`` value and, per
``(name, mars.levelist)``, concatenating the tensors in ``point_offset`` order.  ``point_offset`` is 0
and ``n_values == n_points`` unless the coverage is larger than ``max_fragment_bytes`` (below).

Why this shape
==============

* **One values tensor per (parameter, level)**, not one ``(n_levels, n_points)`` tensor per parameter:
  the block stream delivers one ``(param, level)`` field at a time, so a tensor per parameter would
  have to buffer all of its levels before anything could be written.
* **Separate ``latitude`` and ``longitude`` tensors**, not one ``(n_points, 2)`` tensor: the blocks
  carry two arrays and tensogram encodes them without a copy, while stacking them would duplicate
  every coordinate in memory.
* **Coverages keep the order the extraction produces them in**, for every domain type.  CovJSON's
  PointSeries, VerticalProfile and Trajectory layouts are point-major across field groups, so
  covjsonkit buffers a whole collection to transpose it; this encoder does not, because the block
  order is already a complete description (each tensor carries its point offset, level and datetimes)
  and a consumer can group by point without the producer holding the request in memory.
* **Compression is tensogram's own** (``zstd`` by default, per data object); the result is therefore
  served without HTTP content encoding.

Bounded fragments
=================

``encode_iter`` yields one complete message per fragment.  A message is closed before writing an
object that would take its raw payload over ``max_fragment_bytes`` (8 MiB by default, as covjsonkit),
and a tensor longer than that is written as several point-slices, so the raw bytes behind one message
never exceed ``max_fragment_bytes`` and the encoder holds one message at a time.  Coverages below that
size -- all but the largest single fields -- are therefore exactly one message each.

Configuration (``encoders.tensogram`` in the polytope-mars config): ``max_fragment_bytes``,
``compression`` (any codec tensogram accepts, or ``none``), ``compression_level``, ``hash``.

Media type
==========

Tensogram registers no media type and reserves no extension of its own in its documentation, its CLI
or its wire format, but names its files ``.tgm`` throughout.  This encoder reports
``application/vnd.ecmwf.tensogram`` and the extension ``tgm``; replace the media type if tensogram
ever registers one.
"""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np

__all__ = ["DEFAULT_MAX_FRAGMENT_BYTES", "SCHEMA", "SCHEMA_VERSION", "TensogramEncoder"]

#: Default upper bound on the raw bytes behind one message of :meth:`TensogramEncoder.encode_iter`.
DEFAULT_MAX_FRAGMENT_BYTES = 8 * 1024 * 1024

#: Name of the message layout documented above, in every message's ``_extra_``.
SCHEMA = "polytope-feature-extraction"

#: Version of that layout.  Bump it when the meaning of a documented key changes.
SCHEMA_VERSION = 1

#: Produced the stream; recorded in every message so a reader can tell where it came from.
SOURCE = "polytope-mars"

_COORDINATE_UNITS = {"latitude": "degrees_north", "longitude": "degrees_east"}


def _fragment_limit(value) -> int:
    """``value`` as a positive fragment size in bytes."""
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"max_fragment_bytes must be an integer number of bytes, got {value!r}") from None
    if limit <= 0:
        raise ValueError(f"max_fragment_bytes must be positive, got {limit}")
    return limit


def _plain(value) -> Any:
    """``value`` as one of the CBOR types tensogram metadata allows.

    Tensogram rejects byte strings, tags and non-string map keys, and numpy scalars have no CBOR
    equivalent, so anything that is not a string, bool, integer, float or None becomes its ``str``.
    """
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


class TensogramEncoder:
    """Tensogram encoder for the polytope-mars block stream (one instance per request).

    See the module documentation for the message layout this produces.
    """

    content_type = "application/vnd.ecmwf.tensogram"
    file_extension = "tgm"

    def __init__(self, config=None, max_fragment_bytes: int = DEFAULT_MAX_FRAGMENT_BYTES):
        self.config = dict(config or {})
        #: upper bound on the raw bytes behind one message (``config["max_fragment_bytes"]`` wins)
        self.max_fragment_bytes = _fragment_limit(self.config.get("max_fragment_bytes") or max_fragment_bytes)
        #: compression of every data object, applied by tensogram itself
        self.compression = self.config.get("compression") or "zstd"
        self.compression_level = self.config.get("compression_level")
        self.hash = self.config.get("hash", "xxh3")
        # the tensogram bindings are a compiled extension re-exported with a star import, so the
        # module object is held as Any rather than as a typed module
        self._tensogram: Any = None
        self._header = None
        self.n_coverages = 0
        self.n_messages = 0
        self._group = None
        self._part = 0
        self._pending: list = []
        self._pending_bytes = 0

    # -- protocol ----------------------------------------------------------------------------------------

    def begin(self, header) -> bytes:
        """The header message: the request's parameter table and MARS keys, no data objects."""
        self._header = header
        self._shortname = {p.id: p.shortname for p in header.parameters}
        self._unit = {p.id: p.unit for p in header.parameters}
        self._description = {p.id: p.description for p in header.parameters}
        self.n_coverages = 0
        self.n_messages = 0
        self._group = None
        self._reset_message()
        extra = dict(self._stream_extra())
        extra["mars"] = _plain(dict(header.mars_metadata))
        extra["parameters"] = [
            {
                "id": p.id,
                "shortname": p.shortname,
                "name": p.name,
                "unit": p.unit,
                "description": p.description,
            }
            for p in header.parameters
        ]
        return self._message(extra, [])

    def encode(self, block) -> bytes:
        """The whole block as one ``bytes`` (``b"".join(self.encode_iter(block))``)."""
        return b"".join(self.encode_iter(block))

    def encode_iter(self, block) -> Iterator[bytes]:
        """The block's messages, one per yielded fragment.

        The fragments of a block must be consumed completely, in order, before the next block is
        encoded: the encoder's open message advances as they are produced.
        """
        if hasattr(block, "lat"):
            return self._coords(block)
        if hasattr(block, "values") and hasattr(block, "param"):
            return self._values(block)
        return self._group_end(block)

    def end(self) -> bytes:
        """The trailer message: the stream's coverage and message counts, no data objects."""
        out = b"".join(self._flush())
        extra = dict(self._stream_extra())
        extra["end_of_stream"] = True
        extra["n_coverages"] = self.n_coverages
        # the trailer counts itself, so that a reader can check it has every message
        extra["n_messages"] = self.n_messages + 1
        return out + self._message(extra, [])

    # -- blocks ------------------------------------------------------------------------------------------

    def _coords(self, block) -> Iterator[bytes]:
        yield from self._open(block.group)
        yield from self._write("latitude", "coordinate", None, None, block.lat)
        yield from self._write("longitude", "coordinate", None, None, block.lon)

    def _values(self, block) -> Iterator[bytes]:
        if self._group is not block.group:
            # a group whose coordinates never arrived: open it so the values are still described
            yield from self._open(block.group)
        name = self._shortname.get(block.param, block.param)
        yield from self._write(name, "data", block.param, block.level, block.values)

    def _group_end(self, block) -> Iterator[bytes]:
        if self._group is block.group:
            yield from self._flush()
            self._group = None

    # -- messages ----------------------------------------------------------------------------------------

    def _open(self, group) -> Iterator[bytes]:
        """Close the open coverage, if any, and start ``group`` as the next one."""
        if self._group is group:
            return
        yield from self._flush()
        self._group = group
        self._part = 0
        self.n_coverages += 1

    def _write(self, name, role, param, level, values) -> Iterator[bytes]:
        """One tensor as objects of at most ``max_fragment_bytes``, closing messages as they fill."""
        values = np.ascontiguousarray(values, dtype=np.float64)
        per_object = max(1, self.max_fragment_bytes // 8)
        for start in range(0, max(values.size, 1), per_object):
            stop = start + per_object
            piece = values[start:stop]
            if self._pending and self._pending_bytes + piece.nbytes > self.max_fragment_bytes:
                yield from self._flush()
            base = {
                "name": name,
                "role": role,
                "units": _COORDINATE_UNITS.get(name, self._unit.get(param, "")),
                "point_offset": start,
                "n_values": _plain(piece.size),
            }
            if role == "data":
                base["description"] = self._description.get(param, "")
                mars = {"param": param}
                if level is not None:
                    mars["levelist"] = _plain(level)
                base["mars"] = mars
            self._pending.append((base, piece))
            self._pending_bytes += piece.nbytes

    def _flush(self) -> Iterator[bytes]:
        """The open message, if it has any objects."""
        group = self._group
        if not self._pending or group is None:
            return
        extra = dict(self._stream_extra())
        extra["coverage"] = self.n_coverages - 1
        extra["part"] = self._part
        extra["mars"] = _plain(dict(group.mars_metadata))
        extra["time_values"] = _plain(list(group.t))
        extra["levels"] = _plain(list(group.levels))
        extra["n_points"] = _plain(group.n_points)
        objects = self._pending
        self._part += 1
        self._reset_message()
        yield self._message(extra, objects)

    def _reset_message(self) -> None:
        self._pending = []
        self._pending_bytes = 0

    def _stream_extra(self) -> dict:
        header = self._header
        if header is None:
            raise RuntimeError("TensogramEncoder.begin() must be called first")
        return {
            "source": SOURCE,
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "feature_type": header.feature_type,
            "domain_type": header.domain_type,
            "time_axis": header.time_axis,
            "missing_value": "nan",
        }

    def _message(self, extra: dict, objects: list) -> bytes:
        """One tensogram message from ``extra`` and ``[(base entry, array), ...]``."""
        tgm = self._library()
        meta = {"base": [base for base, _ in objects], "_extra_": extra}
        payload = [(self._descriptor(array.size), array) for _, array in objects]
        self.n_messages += 1
        # allow_nan: NaN is this format's missing value, and tensogram rejects non-finite values
        # unless it is told to record their positions in the frame's mask companion.
        return tgm.encode(meta, payload, hash=self.hash, allow_nan=True, allow_inf=True)

    def _descriptor(self, size) -> dict:
        desc = {"type": "ntensor", "shape": [_plain(size)], "dtype": "float64"}
        if self.compression and self.compression != "none":
            desc["compression"] = self.compression
            if self.compression_level is not None:
                desc[f"{self.compression}_level"] = self.compression_level
        return desc

    def _library(self):
        if self._tensogram is None:
            try:
                import tensogram
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise ImportError(
                    "The 'tensogram' output format needs the tensogram package: pip install tensogram"
                ) from exc
            self._tensogram = tensogram
        return self._tensogram
