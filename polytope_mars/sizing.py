"""How much memory one extraction unit needs (DESIGN §2.7).

An extraction unit is what one ``datacube.get`` (or one ``get_iter`` pass) costs at its peak.  Four
terms, all resident at the same time, so they are added:

**gribjump's own buffer.**  The deployed gribjump (0.12.0.26) is not lazy: ``RemoteGribJump::extract``
decodes the whole TCP reply into a vector before returning and pygribjump's iterator is a cursor
over that vector, so the C++ side holds every value of the call until the call is over.  (Streaming
exists upstream but is unreleased, so sizing is done against what is deployed.)  One
``ExtractionResult`` per field holds ``std::vector<std::vector<double>> values_`` and
``std::vector<std::vector<std::bitset<64>>> mask_``, one inner vector each per index *range*
(``gribjump/src/gribjump/ExtractionData.h``), which makes the term mechanical:

    ``n_fields x (8 x n_points + n_points / 8 + bytes_per_range x n_ranges)``

8 B per value, one mask bit per value, and ``limits.bytes_per_range`` (default 96 B: two vector
headers plus two heap allocations) per range.  ``n_ranges`` is counted from the prepared tree
(:mod:`polytope_mars.grid_ranges`), so ``bytes_per_range`` is the only approximation in this term.
``limits.safety_factor`` multiplies it, and nothing else.

**The request side, once per call.**  ``FDBDatacube`` builds one Python ``int`` per point per leaf
and sorts ``enumerate(...)`` of those lists before anything is fetched, which is what a call with
few fields peaks on: ``limits.bytes_per_point_call x n_points``, paid once however many fields the
call asks for (measured ~220 B/point on HEALPix nested, ~88 B/point on EFAS; see
``../polytope/MEASUREMENTS.md`` and ``python tools/measure_memory.py calibrate``).

**The values the Python side holds**: ``limits.bytes_per_value`` per value (~24 B measured: the
leaf arrays plus the float64 field copy the block walker hands to the encoder).  How many values
that term covers depends on how the unit's results are consumed:

* *per field* (``FDBDatacube.get_iter``, ``limits.per_field_consumption``, **the default**): the
  fields arrive one at a time and each group's blocks are emitted and freed as soon as the group is
  complete, so the term covers **one group** whatever the unit's size
  (:mod:`polytope_mars.field_stream`);
* *whole unit* (``FDBDatacube.get``, the opt-out): every field of the call is on the Python heap
  before the first block is emitted, so the term covers the whole unit.

**The encoder's fragments**: ``fragment_bytes``, twice the encoder's ``max_fragment_bytes`` (one
fragment being built while the previous one is still on the wire), independent of the unit.

A unit of ``k`` groups is planned when

    ``buffer_cpp(unit) x safety_factor``
    ``  + bytes_per_point_call x n_points``
    ``  + bytes_per_value x python_values``
    ``  + fragment_bytes <= memory_budget_bytes``
    ``k x group_fields <= max_fields_per_call``
    ``k x group_fields x n_points <= max_values_per_unit``

where ``python_values`` is one group's values on the per-field path and the unit's values on the
whole-unit path.  Without a budget a unit is a single group (Phase 2 behaviour: nothing bounds a
larger call).  A single group that does not fit is fetched in latitude bands instead
(:meth:`UnitSizing.band_points`); a band is one field of one call, so its own cost is one field's
buffer plus the request side of that call plus one band of every field of the group (the band-0
peek holds them all) plus the fragments.

The sizing is a pure function of (request, config, prepared tree).  Nothing here reads the process
RSS, a cgroup or any other runtime signal; ``timings`` *reports* the estimate and the observed peak
RSS so that production logs can validate the model, but never steers on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "DEFAULT_FRAGMENT_BYTES",
    "GRIBJUMP_BYTES_PER_VALUE",
    "MAX_FIELDS_PER_CALL",
    "UNLIMITED",
    "UnitSizing",
]

#: Bytes one extracted value costs in gribjump's own buffer: a C++ ``double``, exactly.  Not
#: configurable: a property of the wire format, not of a grid or of a code path.
GRIBJUMP_BYTES_PER_VALUE = 8

#: Fields one call may request (``limits.max_fields_per_call``): keeps the request list gribjump has
#: to parse (and the pruned tree) bounded however large the budget is.  Lower it if the gribjump
#: team reports that the union of a call's requests costs more than linearly on their side.
MAX_FIELDS_PER_CALL = 1024

#: Bytes the encoder's fragments cost while a block is being written: twice covjsonkit's
#: ``max_fragment_bytes`` (8 MiB), i.e. one fragment being built and one still referenced.
DEFAULT_FRAGMENT_BYTES = 2 * 8 * 1024 * 1024

#: Stands in for "no limit" where a number is needed; larger than any request that can be sliced.
UNLIMITED = 1 << 62


def _floor_div(numerator: int, denominator: float) -> int:
    """``numerator // denominator`` for a positive denominator; ``UNLIMITED`` for a useless one."""
    if not isinstance(denominator, (int, float)) or denominator <= 0 or not math.isfinite(denominator):
        return UNLIMITED
    try:
        return int(numerator / denominator)
    except (ArithmeticError, ValueError, TypeError):  # pragma: no cover - guarded above
        return UNLIMITED


def _fragment_bytes(value) -> int:
    """``value`` as a byte count; the default for None and for anything unusable (an encoder that
    reports its fragment limit in some other way must not break the planner)."""
    if value is None:
        return DEFAULT_FRAGMENT_BYTES
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_FRAGMENT_BYTES
    return limit if limit > 0 else DEFAULT_FRAGMENT_BYTES


@dataclass(frozen=True)
class UnitSizing:
    """The memory model of one extraction unit, built from ``config.limits``."""

    #: bytes one ``datacube.get`` may cost (``limits.memory_budget_bytes``); None: no budget
    budget: Optional[int] = None
    #: measured Python-side peak bytes per extracted value (``limits.bytes_per_value``)
    bytes_per_value: int = 32
    #: measured Python-side peak bytes per point of one call, whatever its number of fields
    #: (``limits.bytes_per_point_call``: the request-side grid indices)
    bytes_per_point_call: int = 128
    #: bytes one index range costs in gribjump's result (``limits.bytes_per_range``)
    bytes_per_range: int = 96
    #: multiplier on the gribjump buffer term (``limits.safety_factor``)
    safety_factor: float = 1.5
    #: bytes the encoder's fragments cost (twice its ``max_fragment_bytes``)
    fragment_bytes: int = DEFAULT_FRAGMENT_BYTES
    #: hard cap on the values of one unit (``limits.max_values_per_unit``); None: off
    max_values_per_unit: Optional[int] = None
    #: hard cap on the fields of one call (``limits.max_fields_per_call``)
    max_fields_per_call: int = MAX_FIELDS_PER_CALL
    #: True when the unit's fields are consumed one at a time (``FDBDatacube.get_iter``), so that
    #: the per-value term covers one group instead of the whole unit
    per_field_consumption: bool = False

    @classmethod
    def from_limits(cls, limits, per_field_consumption: bool = False, fragment_bytes=None) -> "UnitSizing":
        """The model of ``config.limits``; ``fragment_bytes`` comes from the encoder in use."""
        return cls(
            budget=limits.memory_budget_bytes,
            bytes_per_value=limits.bytes_per_value,
            bytes_per_point_call=limits.bytes_per_point_call,
            bytes_per_range=limits.bytes_per_range,
            safety_factor=limits.safety_factor,
            fragment_bytes=_fragment_bytes(fragment_bytes),
            max_values_per_unit=limits.max_values_per_unit,
            max_fields_per_call=limits.max_fields_per_call,
            per_field_consumption=per_field_consumption,
        )

    # -- the terms -------------------------------------------------------------------------------

    def field_buffer_bytes(self, n_points: int, n_ranges: int) -> int:
        """Bytes gribjump's ``ExtractionResult`` holds for one field: values, mask, per-range vectors."""
        return GRIBJUMP_BYTES_PER_VALUE * n_points + n_points // 8 + self.bytes_per_range * n_ranges

    def buffer_bytes(self, n_fields: int, n_points: int, n_ranges: int) -> int:
        """Bytes gribjump holds for a whole call (the safety factor included)."""
        per_field = self.field_buffer_bytes(n_points, n_ranges)
        return math.ceil(n_fields * per_field * max(self.safety_factor, 0.0))

    def python_bytes(self, n_values: int) -> int:
        """Bytes the Python side holds for ``n_values`` values (leaf arrays, field copies, blocks)."""
        return n_values * self.bytes_per_value

    def request_bytes(self, n_points: int, n_branches: int = 1) -> int:
        """Bytes the request side of one call holds: the grid indices of every point it asks for.

        ``FDBDatacube`` builds those per *spatial sub-tree* (branch) and keeps them for the whole
        call, and the fields of one branch share them.  A unit whose groups sit in one branch (the
        group axes compressed, e.g. an EFAS ensemble's ``number``/``step``) therefore pays this once
        however many groups it fetches, while a unit of ``k`` branches (climate-dt's merged
        date/time axis puts every hourly field in its own branch) pays it ``k`` times.
        """
        return self.bytes_per_point_call * max(0, n_points) * max(1, n_branches)

    def call_bytes(self, n_points: int, python_values: int, n_branches: int = 1) -> int:
        """Python-side bytes of one call: its request side, its live values, the encoder's fragments."""
        return self.request_bytes(n_points, n_branches) + self.python_bytes(python_values) + self.fragment_bytes

    def python_values(self, n_fields: int, group_fields: Optional[int]) -> int:
        """Fields of a unit whose values are live at once: one group, or all of them."""
        if not self.per_field_consumption or group_fields is None:
            return n_fields
        return min(n_fields, max(1, group_fields))

    def estimate_bytes(
        self,
        n_fields: int,
        n_points: int,
        n_ranges: int,
        group_fields: Optional[int] = None,
        n_branches: int = 1,
    ) -> int:
        """Estimated peak bytes of one unit: gribjump's buffer plus the Python side of the call."""
        live_fields = self.python_values(n_fields, group_fields)
        buffer = self.buffer_bytes(n_fields, n_points, n_ranges)
        return buffer + self.call_bytes(n_points, live_fields * n_points, n_branches)

    # -- what fits -------------------------------------------------------------------------------

    def max_unit_groups(self, n_points: int, group_fields: int, n_ranges: int, own_branch: bool = False) -> int:
        """Groups of this shape one ``datacube.get`` may fetch; 0 when one group does not even fit.

        Without a budget every unit is a single group (Phase 2 behaviour: nothing bounds a larger
        call), the hard caps still applying.  With a budget the per-field path is bounded by
        gribjump's buffer -- plus, when every group brings its own branch (``own_branch``), that
        branch's request side -- because its live values are one group's whatever the unit's size.
        """
        group_fields = max(1, group_fields)
        group_values = group_fields * max(0, n_points)
        if group_values == 0:
            return 1
        limits = [max(0, self.max_fields_per_call // group_fields)]
        if self.max_values_per_unit is not None:
            limits.append(self.max_values_per_unit // group_values)
        if self.budget is None:
            limits.append(1)
        else:
            per_group = max(self.buffer_bytes(group_fields, n_points, n_ranges), 1)
            shared = self.fragment_bytes
            if own_branch:
                per_group += self.request_bytes(n_points)
            else:
                shared += self.request_bytes(n_points)
            if self.per_field_consumption:
                # the Python side holds one group however many groups the call fetches
                limits.append(_floor_div(self.budget - shared - self.python_bytes(group_values), per_group))
            else:
                limits.append(_floor_div(self.budget - shared, per_group + self.python_bytes(group_values)))
        return max(0, min(limits))

    def fits_group(self, n_points: int, group_fields: int, n_ranges: int) -> bool:
        """True when one group can be fetched in one go (else it is fetched in latitude bands)."""
        return self.max_unit_groups(n_points, group_fields, n_ranges) >= 1

    def band_points(self, n_fields: int, ranges_per_point: float = 1.0) -> int:
        """Points per latitude band of a group that does not fit, at least one spatial node's worth.

        A band is one field of one call: it costs that field's gribjump buffer and that call's
        request side, plus one band of every field of the group and one coordinate block (the
        band-0 peek holds them all), plus the encoder's fragments.  ``ranges_per_point`` is the
        group's own ratio, so a band of a HEALPix-nested field (nearly one range per point) is
        sized for its ranges and an octahedral band is not.
        """
        n_fields = max(1, n_fields)
        allowed = []
        if self.budget is not None:
            buffer_point = GRIBJUMP_BYTES_PER_VALUE + 0.125 + self.bytes_per_range * max(ranges_per_point, 0.0)
            python_point = self.bytes_per_point_call + self.bytes_per_value * (n_fields + 1)
            per_point = buffer_point * max(self.safety_factor, 0.0) + python_point
            allowed.append(_floor_div(self.budget - self.fragment_bytes, per_point))
        if self.max_values_per_unit is not None:
            allowed.append(self.max_values_per_unit // n_fields)
        return max(1, min(allowed)) if allowed else UNLIMITED
