import io
import re

from setuptools import find_packages, setup

_version = re.search(
    r'__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
    io.open("polytope_mars/version.py", encoding="utf_8_sig").read(),
)
if _version is None:
    raise SystemExit("polytope_mars/version.py does not define __version__")
__version__ = _version.group(1)


try:
    with open("requirements.txt") as f:
        requirements = f.read().splitlines()
except OSError as exc:
    raise SystemExit(f"requirements.txt cannot be read: {exc}") from exc

setup(
    name="polytope_mars",
    version=__version__,
    description="High level meteorological feature extraction interface to Polytope",  # noqa: E501
    long_description="",
    url="https://github.com/ecmwf/polytope-mars",
    author="ECMWF",
    author_email="James.Hawkes@ecmwf.int, Adam.Warde@ecmwf.int, Mathilde.Leuridan@ecmwf.int",  # noqa: E501
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    package_data={"polytope_mars": ["data/ecmwf/*.json", "data/dwd/*.json"]},
    install_requires=requirements,
    # format: tensogram needs it; every other format works without it
    extras_require={"tensogram": ["tensogram>=0.24.0"]},
)
