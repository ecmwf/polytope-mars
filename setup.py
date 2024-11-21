import io
import re

from setuptools import find_packages, setup

__version__ = re.search(
    r'__version__\s*=\s*[\'"]([^\'"]*)[\'"]',
    io.open("polytope_mars/version.py", encoding="utf_8_sig").read(),
).group(1)


with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="polytope-mars",
    version=__version__,
    description="High level meteorological feature extraction interface to Polytope",  # noqa: E501
    long_description="",
    url="https://github.com/ecmwf/polytope-mars",
    author="ECMWF",
    author_email="James.Hawkes@ecmwf.int, Adam.Warde@ecmwf.int, Mathilde.Leuridan@ecmwf.int",  # noqa: E501
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=requirements,
)
