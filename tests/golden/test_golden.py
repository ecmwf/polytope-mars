"""Golden corpus: the exact bytes the fe-worker ships for each case must not change.

Each ``cases/<name>.yaml`` is run through ``PolytopeMars.extract`` against the fake gribjump
(``polytope_mars.testing``) and ``json.dumps(...).encode("utf-8")`` is compared byte for byte
with ``expected/<name>.covjson``. Cases with ``expect_error`` assert the legacy exception instead.

Regenerate after a deliberate output change (and record it in CHANGES.md):
``pytest tests/golden --golden-regen`` or ``GOLDEN_REGEN=1 pytest tests/golden``.
"""

import builtins
import re
from pathlib import Path

import pytest

from polytope_mars.testing.golden import load_case, run_case

HERE = Path(__file__).parent
CASES = sorted((HERE / "cases").glob("*.yaml"))


def _first_difference(actual: bytes, expected: bytes) -> str:
    n = next((i for i, (a, b) in enumerate(zip(actual, expected)) if a != b), min(len(actual), len(expected)))
    lo = max(0, n - 80)
    return (
        f"lengths actual={len(actual)} expected={len(expected)}; first difference at byte {n}\n"
        f"  actual:   ...{actual[lo:n + 80]!r}\n"
        f"  expected: ...{expected[lo:n + 80]!r}"
    )


@pytest.mark.parametrize("case_path", CASES, ids=[p.stem for p in CASES])
def test_golden(case_path, golden_regen):
    case = load_case(case_path)
    expected_path = HERE / "expected" / f"{case_path.stem}.covjson"

    if "expect_error" in case:
        err = case["expect_error"]
        exc_type = getattr(builtins, err["type"])
        with pytest.raises(exc_type, match=re.escape(err.get("match", ""))):
            run_case(case)
        assert not expected_path.exists(), f"{expected_path.name} exists for a case that expects an error"
        return

    actual = run_case(case)
    if golden_regen:
        expected_path.write_bytes(actual)
        return
    assert expected_path.exists(), f"missing {expected_path}; run with --golden-regen to create it"
    expected = expected_path.read_bytes()
    assert actual == expected, _first_difference(actual, expected)
