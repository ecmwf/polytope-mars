"""``format: tensogram`` carries the same data as the CovJSON of the same request.

Each case of the golden corpus is extracted twice: once as CovJSON, whose bytes are the corpus'
``expected``/``expected_fixed`` file, and once as tensogram, which is decoded again with the
``tensogram`` package.  The two are compared as records -- one per (datetime, parameter, level,
latitude, longitude, ensemble member) -- because the two layouts differ by design: CovJSON transposes
point features into point-major coverages while the tensogram stream keeps the field-group order it
is produced in (:mod:`polytope_mars.encoders.tensogram`).  For MultiPoint domains, where the layouts
do agree, the coverages are also compared in order, coordinate by coordinate.

Tensogram stamps a timestamp and a UUID into every message's ``_reserved_`` section, so tensogram
output is never byte-reproducible; everything here is asserted on the decoded content.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

from polytope_mars.encoders import get_encoder
from polytope_mars.encoders.tensogram import (  # type: ignore[import-not-found]
    SCHEMA,
    SCHEMA_VERSION,
    TensogramEncoder,
)
from polytope_mars.testing.golden import load_case, make_polytope_mars

tensogram = pytest.importorskip("tensogram")  # the output format under test

GOLDEN = Path(__file__).parent / "golden"

#: One case per layout the encoder has to cover: MultiPoint box and polygon, an ensemble, levels,
#: bitmap-missing points, a missing field, a time series on both coverage plans, a vertical profile
#: and a trajectory.
CASES = [
    "efas_bbox_multiparam",
    "efas_polygon_fc",
    "efas_bbox_ensemble",
    "cdt_bbox_levelist",
    "o1280_bbox_nan_points",
    "o1280_bbox_missing_field",
    "o1280_timeseries_steps",
    "cdt_timeseries",
    "o1280_verticalprofile",
    "o1280_trajectory",
]

#: keys of the coordinate tensors in the reassembled form below (they carry no level)
LATITUDE = ("latitude", "0")
LONGITUDE = ("longitude", "0")

MULTIPOINT_CASES = [
    "efas_bbox_multiparam",
    "efas_polygon_fc",
    "efas_bbox_ensemble",
    "cdt_bbox_levelist",
    "o1280_bbox_nan_points",
    "o1280_bbox_missing_field",
]


# -- running a case ---------------------------------------------------------------------------------


def case_of(name: str) -> dict:
    return load_case(GOLDEN / "cases" / f"{name}.yaml")


def covjson_of(name: str) -> dict:
    """The corpus' CovJSON document for ``name`` (the bytes the covjson encoder ships)."""
    case = case_of(name)
    folder = "expected_fixed" if case.get("fixes") else "expected"
    raw = (GOLDEN / folder / f"{name}.covjson").read_bytes()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{folder}/{name}.covjson is not valid JSON: {exc}") from exc


def tensogram_bytes(name: str, config_update: dict | None = None) -> bytes:
    """``b"".join(extract_stream(request))`` for ``name`` with ``format: tensogram``."""
    case = copy.deepcopy(case_of(name))
    case["request"]["format"] = "tensogram"
    pm, request = make_polytope_mars(case, config_update=config_update)
    data = b"".join(pm.extract_stream(request))
    assert pm.content_type == "application/vnd.ecmwf.tensogram"
    assert pm.file_extension == "tgm"
    return data


def messages(data: bytes) -> list:
    """``[(metadata, objects), ...]`` of a tensogram stream, as a reader of the result file sees it."""
    return [(meta, objects) for meta, objects in tensogram.iter_messages(data)]


def decode(name: str, config_update: dict | None = None) -> list:
    return messages(tensogram_bytes(name, config_update))


# -- comparable records -----------------------------------------------------------------------------


def _level(value) -> str:
    """A level as both layouts spell it: no level is level 0 (as the legacy encoders wrote it)."""
    return "0" if value is None or value == () else str(value)


def _number(value) -> str:
    """A value of the range axis, or ``"null"`` where CovJSON has no value and tensogram has NaN."""
    if value is None:
        return "null"
    value = value + 0.0
    return "null" if math.isnan(value) else repr(value)


def _record(t, name, level, lat, lon, discriminator, value) -> str:
    """One data point in a form both layouts produce identically and a diff can be read."""
    axis = ",".join(str(v) for v in t)
    return "|".join([axis, name, level, repr(lat), repr(lon), discriminator, _number(value)])


def covjson_records(doc: dict) -> list:
    """The data points of a CovJSON collection, sorted, as :func:`_record` strings.

    The four domain layouts the legacy encoders produce are read back into one flat form: a
    MultiPoint or Trajectory coverage carries its points in composite tuples, a PointSeries coverage
    one point and a ``t`` axis, a VerticalProfile coverage one point and a ``levelist`` axis.
    """
    domain = doc["domainType"]
    out = []
    for coverage in doc["coverages"]:
        axes = coverage["domain"]["axes"]
        discriminator = _discriminator(domain, coverage["mars:metadata"])
        t = tuple(axes["t"]["values"]) if "t" in axes else ()
        if domain == "MultiPoint":
            points = [(t, lat, lon, _level(lev)) for lat, lon, lev in axes["composite"]["values"]]
        elif domain == "Trajectory":
            points = [((ti,), lat, lon, _level(lev)) for ti, lat, lon, lev in axes["composite"]["values"]]
        elif domain == "PointSeries":
            lat = axes["latitude"]["values"][0]
            lon = axes["longitude"]["values"][0]
            level = _level(axes["levelist"]["values"][0])
            points = [((ti,), lat, lon, level) for ti in t]
        elif domain == "VerticalProfile":
            lat = axes["latitude"]["values"][0]
            lon = axes["longitude"]["values"][0]
            points = [(t, lat, lon, _level(lev)) for lev in axes["levelist"]["values"]]
        else:
            raise AssertionError(f"unsupported domain type {domain!r}")
        for name, rng in coverage["ranges"].items():
            assert len(rng["values"]) == len(points), f"{name}: {len(rng['values'])} values, {len(points)} points"
            for (ti, lat, lon, level), value in zip(points, rng["values"]):
                out.append(_record(ti, name, level, lat, lon, discriminator, value))
    return sorted(out)


def _discriminator(domain: str, mars: dict) -> str:
    """What tells two coverages with the same point and datetime apart.

    A MultiPoint coverage keeps keys such as ``step`` out of its ``t`` axis, so its whole MARS
    metadata is needed; the point-feature layouts put every such key on the ``t`` axis of a series
    and carry the metadata of the series' first field group, so only the ensemble member is left.
    """
    if domain == "MultiPoint":
        return repr(sorted((k, str(v)) for k, v in mars.items()))
    return str(mars.get("number"))


def tensogram_coverages(msgs: list) -> list:
    """Per coverage, ``{"extra": ..., "tensors": {(name, level): array}}``, parts concatenated.

    This is the reassembly the format definition asks a consumer for: collect the messages of one
    ``coverage``, then concatenate each tensor's pieces in ``point_offset`` order.
    """
    body = [(meta, objects) for meta, objects in msgs if "coverage" in meta.extra]
    out: list = []
    pieces: dict = {}
    for meta, objects in body:
        index = meta.extra["coverage"]
        if not out or out[-1]["extra"]["coverage"] != index:
            assert meta.extra["part"] == 0, f"coverage {index} does not start at part 0"
            out.append({"extra": dict(meta.extra), "tensors": {}})
            pieces = {}
        else:
            assert meta.extra["part"] == out[-1]["parts"], "coverage parts are not consecutive"
        out[-1]["parts"] = meta.extra["part"] + 1
        for base, array in zip(meta.base, objects):
            _, values = array if isinstance(array, tuple) else (None, array)
            key = (base["name"], _level((base.get("mars") or {}).get("levelist")))
            pieces.setdefault(key, []).append((base["point_offset"], base["n_values"], values))
        for key, parts in pieces.items():
            parts.sort()
            offset = 0
            for start, count, values in parts:
                assert start == offset, f"{key}: piece at {start} follows {offset} values"
                assert count == len(values), f"{key}: n_values {count} != tensor length {len(values)}"
                offset += count
            out[-1]["tensors"][key] = np.concatenate([values for _, _, values in parts])
    return out


def tensogram_records(msgs: list) -> list:
    """The data points of a tensogram stream, sorted, as :func:`_record` strings."""
    out = []
    for coverage in tensogram_coverages(msgs):
        extra = coverage["extra"]
        t = tuple(extra["time_values"])
        discriminator = _discriminator(extra["domain_type"], extra["mars"])
        lat = coverage["tensors"][LATITUDE]
        lon = coverage["tensors"][LONGITUDE]
        for name, level, values in data_tensors(coverage):
            assert len(values) == len(lat), f"{name}: {len(values)} values for {len(lat)} points"
            for i, value in enumerate(values):
                out.append(_record(t, name, level, lat[i].item(), lon[i].item(), discriminator, value.item()))
    return sorted(out)


def data_tensors(coverage: dict) -> list:
    """The coverage's value tensors as ``[(shortname, level, array), ...]``, the coordinates aside."""
    return [
        (name, level, values)
        for (name, level), values in coverage["tensors"].items()
        if name not in ("latitude", "longitude")
    ]


def assert_same_records(expected: list, actual: list) -> None:
    if expected == actual:
        return
    only_actual = sorted(set(actual) - set(expected))
    only_expected = sorted(set(expected) - set(actual))
    raise AssertionError(
        f"{len(only_actual)} records only in tensogram, e.g. {only_actual[:2]}; "
        f"{len(only_expected)} only in covjson, e.g. {only_expected[:2]}"
    )


# -- the stream's shape -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_header_message_describes_the_request_and_its_parameters(name):
    doc = covjson_of(name)
    meta, objects = decode(name)[0]
    assert objects == []
    extra = meta.extra
    assert extra["source"] == "polytope-mars"
    assert extra["schema"] == SCHEMA
    assert extra["schema_version"] == SCHEMA_VERSION
    assert extra["missing_value"] == "nan"
    assert extra["domain_type"] == doc["domainType"]
    assert extra["feature_type"] == case_of(name)["request"]["feature"]["type"]
    parameters = {p["shortname"]: p for p in extra["parameters"]}
    assert set(doc["parameters"]) <= set(parameters)
    for shortname, expected in doc["parameters"].items():
        got = parameters[shortname]
        assert got["unit"] == expected["unit"]["symbol"]
        assert got["name"] == expected["observedProperty"]["label"]["en"]
        assert got["description"] == expected["description"]["en"]
        assert got["id"].isdigit()


@pytest.mark.parametrize("name", CASES)
def test_the_trailer_message_lists_the_parameters_the_coverages_hold(name):
    doc = covjson_of(name)
    meta, objects = decode(name)[-1]
    assert objects == []
    assert [p["shortname"] for p in meta.extra["parameters"]] == list(doc["parameters"])


@pytest.mark.parametrize("name", CASES)
def test_the_trailer_message_counts_the_coverages_and_the_messages(name):
    doc = covjson_of(name)
    msgs = decode(name)
    meta, objects = msgs[-1]
    assert objects == []
    assert meta.extra["end_of_stream"]
    assert meta.extra["n_messages"] == len(msgs)
    assert meta.extra["n_coverages"] == len(tensogram_coverages(msgs))
    if doc["domainType"] == "MultiPoint":
        assert meta.extra["n_coverages"] == len(doc["coverages"])


@pytest.mark.parametrize("name", CASES)
def test_every_coverage_message_names_its_tensors_and_their_place(name):
    for coverage in tensogram_coverages(decode(name)):
        extra = coverage["extra"]
        assert extra["n_points"] == len(coverage["tensors"][LATITUDE])
        assert isinstance(extra["time_values"], list)
        assert extra["mars"]


# -- the data ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_values_are_those_of_the_covjson_of_the_same_request(name):
    assert_same_records(covjson_records(covjson_of(name)), tensogram_records(decode(name)))


@pytest.mark.parametrize("name", MULTIPOINT_CASES)
def test_a_multipoint_coverage_matches_the_covjson_coverage_in_order(name):
    doc = covjson_of(name)
    coverages = tensogram_coverages(decode(name))
    assert len(coverages) == len(doc["coverages"])
    for coverage, expected in zip(coverages, doc["coverages"]):
        extra = coverage["extra"]
        assert extra["mars"] == expected["mars:metadata"]
        assert extra["time_values"] == expected["domain"]["axes"]["t"]["values"]
        composite = expected["domain"]["axes"]["composite"]["values"]
        n_points = extra["n_points"]
        points = composite[:n_points]
        assert np.array_equal(coverage["tensors"][LATITUDE], [c[0] for c in points])
        assert np.array_equal(coverage["tensors"][LONGITUDE], [c[1] for c in points])
        levels = [_level(lev) for lev in extra["levels"]] or ["0"]
        assert sorted({lev for _, lev, _ in data_tensors(coverage)}) == sorted(set(levels))
        for shortname, rng in expected["ranges"].items():
            for i, level in enumerate(levels):
                lo, hi = i * n_points, (i + 1) * n_points
                piece = rng["values"][lo:hi]
                got = coverage["tensors"][(shortname, level)]
                assert len(got) == len(piece)
                assert [_number(e) for e in piece] == [_number(a.item()) for a in got]


def test_a_bitmap_missing_point_is_nan_where_the_covjson_is_null():
    doc = covjson_of("o1280_bbox_nan_points")
    nulls = sum(v is None for c in doc["coverages"] for r in c["ranges"].values() for v in r["values"])
    assert nulls > 0
    nans = sum(
        np.isnan(values).sum()
        for coverage in tensogram_coverages(decode("o1280_bbox_nan_points"))
        for _, _, values in data_tensors(coverage)
    )
    assert nans == nulls


def test_a_missing_field_leaves_its_parameter_out_of_the_coverage():
    doc = covjson_of("o1280_bbox_missing_field")
    coverages = tensogram_coverages(decode("o1280_bbox_missing_field"))
    expected = [sorted(c["ranges"]) for c in doc["coverages"]]
    actual = [sorted({name for name, _, _ in data_tensors(c)}) for c in coverages]
    assert actual == expected
    assert min(len(names) for names in expected) < max(len(names) for names in expected)


# -- bounded fragments ------------------------------------------------------------------------------


def test_the_encoder_reports_the_fragment_bound_the_unit_sizing_reads():
    assert isinstance(get_encoder("tensogram"), TensogramEncoder)
    assert TensogramEncoder().max_fragment_bytes == 8 * 1024 * 1024
    configured = get_encoder("tensogram", {"tensogram": {"max_fragment_bytes": 4096}})
    assert getattr(configured, "max_fragment_bytes") == 4096
    with pytest.raises(ValueError, match="max_fragment_bytes must be positive"):
        get_encoder("tensogram", {"tensogram": {"max_fragment_bytes": -1}})


@pytest.mark.parametrize("bound", [512, 2048])
def test_a_fragment_bound_splits_the_tensors_without_changing_the_data(bound):
    """A coverage larger than the bound becomes several messages, each within it."""
    name = "efas_frame_fc"  # 360 points per coverage, i.e. 2.8 kB of coordinates
    update = {"encoders": {"tensogram": {"max_fragment_bytes": bound}}}
    fragments = []
    case = copy.deepcopy(case_of(name))
    case["request"]["format"] = "tensogram"
    pm, request = make_polytope_mars(case, config_update=update)
    for fragment in pm.extract_stream(request):
        fragments.append(fragment)
    data = b"".join(fragments)
    msgs = messages(data)

    assert len(fragments) == len(msgs), "every fragment is one complete message"
    for meta, objects in msgs:
        payload = sum(array.nbytes for _, array in objects)
        assert payload <= bound, f"message payload {payload} over the bound {bound}"
        for base, (_, array) in zip(meta.base, objects):
            assert base["n_values"] <= bound // 8

    coverages = tensogram_coverages(msgs)
    assert max(c["parts"] for c in coverages) > 1, "the bound did not split anything"
    assert_same_records(covjson_records(covjson_of(name)), tensogram_records(msgs))


def test_the_default_bound_gives_one_message_per_coverage():
    msgs = decode("efas_frame_fc")
    assert [c["parts"] for c in tensogram_coverages(msgs)] == [1]
    assert len(msgs) == 3  # header, the one coverage, trailer


# -- invariance -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", MULTIPOINT_CASES)
def test_the_data_does_not_depend_on_how_many_groups_one_call_fetches(name):
    """One field group per gribjump call and all of them in one call give the same records."""
    one = {"limits": {"memory_budget_bytes": 1610612736, "max_fields_per_call": 1}}
    everything = {"limits": {"memory_budget_bytes": 1610612736, "max_fields_per_call": 4096}}
    expected = covjson_records(covjson_of(name))
    for update in (one, everything):
        assert_same_records(expected, tensogram_records(decode(name, update)))
