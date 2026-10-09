import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--golden-regen",
        action="store_true",
        default=False,
        help="Rewrite tests/golden/expected/*.covjson from the current code instead of comparing "
        "(same as GOLDEN_REGEN=1).",
    )


@pytest.fixture
def golden_regen(request):
    return request.config.getoption("--golden-regen") or os.environ.get("GOLDEN_REGEN", "") not in ("", "0")
