"""How much memory one extraction unit needs (DESIGN §2.7).

An extraction unit is what one ``datacube.get`` costs at its peak.  Two terms:

**The gribjump buffer.**  The deployed gribjump (0.12.0.26) is not lazy: ``RemoteGribJump::extract``
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

**The Python side**: the values copied into the request tree, the float64 field arrays the block
walker builds and the encoder's buffers -- ``limits.bytes_per_value`` per value (measured, see
MEASUREMENTS.md and ``python tools/measure_memory.py calibrate``).  How many values that term
covers depends on how the unit's results are consumed:

* *whole unit* (``FDBDatacube.get``, the only path today): every field of the call is on the Python
  heap before the first block is emitted, so the term applies to the whole unit;
* *per field* (``FDBDatacube.get_iter``, polytope-feature work in progress): fields are consumed as
  they arrive and each group's blocks are emitted and freed as soon as the group is complete, so
  the term applies to one group (:mod:`polytope_mars.field_stream`).

A unit of ``k`` groups is planned when all of

    ``buffer_bytes(unit) x safety_factor <= memory_budget_bytes``
    ``n_fields x n_points <= max_values_per_unit``
    ``python_values x bytes_per_value <= memory_budget_bytes``

hold, where ``python_values`` is the unit's values on the whole-unit path and one group's values on
the per-field path.  A single group that does not fit is fetched in latitude bands instead
(:meth:`UnitSizing.band_points`).

The sizing is a pure function of (request, config, prepared tree).  Nothing here reads the process
RSS, a cgroup or any other runtime signal; ``timings`` *reports* the estimate and the observed peak
RSS so that production logs can validate the model, but never steers on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

__all__ = ["GRIBJUMP_BYTES_PER_VALUE", "MAX_FIELDS_PER_UNIT", "UNLIMITED", "UnitSizing"]

#: Bytes one extracted value costs in gribjump's own buffer: a C++ ``double``, exactly.  Not
#: configurable: a property of the wire format, not of a grid or of a code path.
GRIBJUMP_BYTES_PER_VALUE = 8

#: Fields one call may request on the per-field path, where memory no longer bounds the unit: keeps
#: the request list gribjump has to parse (and the pruned tree) bounded.
MAX_FIELDS_PER_UNIT = 1024

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


@dataclass(frozen=True)
class UnitSizing:
    """The memory model of one extraction unit, built from ``config.limits``."""

    #: bytes one ``datacube.get`` may cost (``limits.memory_budget_bytes``); None: no budget
    budget: Optional[int] = None
    #: measured Python-side peak bytes per extracted value (``limits.bytes_per_value``)
    bytes_per_value: int = 128
    #: bytes one index range costs in gribjump's result (``limits.bytes_per_range``)
    bytes_per_range: int = 96
    #: multiplier on the gribjump buffer term (``limits.safety_factor``)
    safety_factor: float = 1.5
    #: hard cap on the values of one unit (``limits.max_values_per_unit``); None: off
    max_values_per_unit: Optional[int] = None
    #: True when the unit's fields are consumed one at a time (``FDBDatacube.get_iter``), so that
    #: the Python-side term covers one group instead of the whole unit
    per_field_consumption: bool = False

    @classmethod
    def from_limits(cls, limits, per_field_consumption: bool = False) -> "UnitSizing":
        return cls(
            budget=limits.memory_budget_bytes,
            bytes_per_value=limits.bytes_per_value,
            bytes_per_range=limits.bytes_per_range,
            safety_factor=limits.safety_factor,
            max_values_per_unit=limits.max_values_per_unit,
            per_field_consumption=per_field_consumption,
        )

    # -- the two terms ---------------------------------------------------------------------------

    def field_buffer_bytes(self, n_points: int, n_ranges: int) -> int:
        """Bytes gribjump's ``ExtractionResult`` holds for one field: values, mask, per-range vectors."""
        return GRIBJUMP_BYTES_PER_VALUE * n_points + n_points // 8 + self.bytes_per_range * n_ranges

    def buffer_bytes(self, n_fields: int, n_points: int, n_ranges: int) -> int:
        """Bytes gribjump holds for a whole call (the safety factor included)."""
        per_field = self.field_buffer_bytes(n_points, n_ranges)
        return math.ceil(n_fields * per_field * max(self.safety_factor, 0.0))

    def python_bytes(self, n_values: int) -> int:
        """Bytes the Python side holds for ``n_values`` values (tree results, field copies, blocks)."""
        return n_values * self.bytes_per_value

    def estimate_bytes(self, n_fields: int, n_points: int, n_ranges: int, group_fields: Optional[int] = None) -> int:
        """Estimated peak bytes of one unit: gribjump's buffer plus the Python side."""
        python_fields = n_fields
        if self.per_field_consumption and group_fields is not None:
            python_fields = min(n_fields, group_fields)
        return self.buffer_bytes(n_fields, n_points, n_ranges) + self.python_bytes(python_fields * n_points)

    # -- what fits -------------------------------------------------------------------------------

    def max_unit_groups(self, n_points: int, group_fields: int, n_ranges: int) -> int:
        """Groups of this shape one ``datacube.get`` may fetch; 0 when one group does not even fit.

        Without a budget the whole-unit path keeps one group per call (Phase 2 behaviour: nothing
        bounds a larger call); the hard cap still applies.  The per-field path is bounded by the
        gribjump buffer, the hard cap and :data:`MAX_FIELDS_PER_UNIT`, because its Python side only
        ever holds one group.
        """
        group_fields = max(1, group_fields)
        group_values = group_fields * max(0, n_points)
        if group_values == 0:
            return 1
        limits = []
        if self.max_values_per_unit is not None:
            limits.append(self.max_values_per_unit // group_values)
        if self.budget is not None:
            per_group = self.buffer_bytes(group_fields, n_points, n_ranges)
            limits.append(_floor_div(self.budget, max(per_group, 1)))
            if not self.per_field_consumption:
                limits.append(_floor_div(self.budget, self.python_bytes(group_values)))
        if self.per_field_consumption:
            limits.append(MAX_FIELDS_PER_UNIT // group_fields)
        elif self.budget is None:
            limits.append(1)
        return max(0, min(limits)) if limits else UNLIMITED

    def fits_group(self, n_points: int, group_fields: int, n_ranges: int) -> bool:
        """True when one group can be fetched in one go (else it is fetched in latitude bands)."""
        return self.max_unit_groups(n_points, group_fields, n_ranges) >= 1

    def band_points(self, n_fields: int, ranges_per_point: float = 1.0) -> int:
        """Points per latitude band of a group that does not fit, at least one spatial node's worth.

        One band of every field of the group plus one coordinate block must fit the Python side (the
        band-0 peek holds them all); one band of one field must fit gribjump's buffer and the cap.
        ``ranges_per_point`` is the group's own ratio, so a band of a HEALPix-nested field (nearly
        one range per point) is sized for its ranges and an octahedral band is not.
        """
        n_fields = max(1, n_fields)
        allowed = []
        if self.budget is not None:
            allowed.append(_floor_div(self.budget, self.bytes_per_value * (n_fields + 1)))
            per_point = GRIBJUMP_BYTES_PER_VALUE + 0.125 + self.bytes_per_range * max(ranges_per_point, 0.0)
            allowed.append(_floor_div(self.budget, per_point * max(self.safety_factor, 0.0)))
        if self.max_values_per_unit is not None:
            allowed.append(self.max_values_per_unit // n_fields)
        return max(1, min(allowed)) if allowed else UNLIMITED
