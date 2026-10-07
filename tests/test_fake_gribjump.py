import copy
import json

import numpy as np

import polytope_mars.api
from polytope_mars.api import PolytopeMars
from polytope_mars.testing import (
    FakeGribJump,
    decode_value,
    expected_values,
    fake_gribjump_config_dict,
    field_id,
    make_fake_gribjump,
)

REQUEST = {
    "class": "od",
    "stream": "oper",
    "type": "fc",
    "levtype": "sfc",
    "expver": "0001",
    "domain": "g",
    "date": "20240101",
    "time": "0000",
    "step": "0/6",
    "param": "167",
    "feature": {"type": "boundingbox", "points": [[51.6, 0.0], [51.3, 0.3]]},
}


def test_axes_are_sorted_and_narrowed_by_partial_request():
    fake = FakeGribJump(
        [
            {"stream": ["oper"], "class": ["od"], "step": ["0", "6"]},
            {"stream": ["enfo"], "class": ["od"], "step": ["0", "12"], "number": ["1", "2"]},
        ]
    )
    assert fake.axes({"stream": "oper"}) == {"class": ["od"], "step": ["0", "6"], "stream": ["oper"]}
    both = fake.axes({"class": "od"})
    assert list(both) == sorted(both)
    assert both["step"] == ["0", "6", "12"]
    assert fake.axes({"stream": "wave"}) == {}


def test_extract_values_missing_and_nan():
    fake = FakeGribJump({"param": ["1", "2"]}, missing=[{"param": "2"}], nan_indices=[11])
    present, missing = fake.extract([({"param": "1"}, [(10, 13), (20, 21)], "h"), ({"param": "2"}, [(0, 5)], "h")])
    assert missing.values == []
    assert [v.dtype for v in present.values] == [np.float64, np.float64]
    np.testing.assert_array_equal(present.values[1], expected_values({"param": "1"}, [20]))
    assert np.isnan(present.values[0][1])
    fid, index = decode_value(present.values[0][2])
    assert fid == field_id({"param": "1"})
    assert index == 12
    assert fake.n_requests == 2
    assert fake.n_values == 4  # missing fields deliver no values


def test_datacube_factory_and_timings():
    fake = make_fake_gribjump("octahedral_1280")
    pm = PolytopeMars(fake_gribjump_config_dict("octahedral_1280", REQUEST), datacube_factory=lambda: fake)
    result = pm.extract(copy.deepcopy(REQUEST))
    assert len(result["coverages"]) == 2
    # one extraction unit (one gribjump call) per field group (= coverage) when there is no memory budget
    assert fake.n_extract_calls == 2
    t = pm.timings
    assert t["n_coverages"] == t["n_groups"] == 2
    assert t["n_units"] == t["n_gribjump_calls"] == t["n_bands"] == 2
    for key in ("datacube_init_ms", "retrieve_ms", "slice_ms", "prepare_ms", "get_ms", "encode_ms", "first_byte_ms"):
        assert t[key] >= 0
    assert abs(t["slice_ms"] + t["prepare_ms"] + t["get_ms"] - t["retrieve_ms"]) < 0.01


def test_monkeypatched_gribjump_class_still_used(monkeypatch):
    fake = make_fake_gribjump("octahedral_1280")
    monkeypatch.setattr(polytope_mars.api.gj, "GribJump", lambda: fake)
    pm = PolytopeMars(fake_gribjump_config_dict("octahedral_1280", REQUEST))
    via_patch = json.dumps(pm.extract(copy.deepcopy(REQUEST)))
    pm2 = PolytopeMars(
        fake_gribjump_config_dict("octahedral_1280", REQUEST),
        datacube_factory=lambda: make_fake_gribjump("octahedral_1280"),
    )
    assert via_patch == json.dumps(pm2.extract(copy.deepcopy(REQUEST)))
    assert fake.n_extract_calls == 2  # one per field group
