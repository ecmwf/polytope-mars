| :warning: This project is BETA and will be experimental for the foreseeable future. Interfaces and functionality are likely to change. DO NOT use this software in any project/software that is operational. |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |

<h3 align="center">
<img src="./docs/images/ECMWF_logo.svg.png" width=60%>
</br>

# Polytope-mars

<p align="center">
  <a href="https://github.com/ecmwf/polytope-mars/actions/workflows/ci.yaml">
  <img src="https://github.com/ecmwf/polytope-mars/actions/workflows/ci.yaml/badge.svg" alt="ci">
</a>
  <a href="https://codecov.io/gh/ecmwf/polytope-mars"><img src="https://codecov.io/gh/ecmwf/polytope-mars/branch/develop/graph/badge.svg"></a>
  <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg"></a>
  <a href="https://github.com/ecmwf/polytope-mars/releases"><img src="https://img.shields.io/github/v/release/ecmwf/polytope-mars?color=blue&label=Release&style=flat-square"></a>
</p>
<p align="center">
  <a href="#concept">Concept</a> •
  <a href="#installation">Installation</a> •
  <a href="#example">Example</a> •
  <a href="#testing">Testing</a>
</p>

## Concept

Repository for high level API of polytope feature extraction such as vertical profile and time series.

Current features include:

* [Time Series](docs/user_guide/timeseries.md)
* [Vertical Profile](docs/user_guide/vertical_profile.md)
* [Bounding Box](docs/user_guide/boundingbox.md)
* [Trajectory](docs/user_guide/trajectory.md)
* [Polygon](docs/user_guide/polygon.md)
* [Frame](docs/user_guide/frame.md)

## Installation

```bash
pip install polytope-mars
```

Or clone the repo and install locally

```bash
git clone git@github.com:ecmwf/polytope-mars.git
cd polytope-mars

pip install -e .
```


## Example

**Create time series request**: Create a request for a time series request using the time series feature, set options for use by polytope feature extraction. "gribjump" indicates the type of data in this case. NB: Assumes data is in a local FDB or or environment variables have been set up to point to a gribjump server.

```python
from polytope_mars.api import PolytopeMars

request = {
    "class": "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20231205",
    "time" : "00:00:00",
    "levtype" : "sfc",
    "expver" : "0001", 
    "domain" : "g",
    "param" : "228/49/164/165/166/167",
    "number" : "1/to/5",
    "step" : "0/1"
    "feature" : {
        "type" : "timeseries",
        "points" : [[51.5073219, 2.1]],
        "axis" : "step",
    },
}

result = PolytopeMars().extract(request)

```

If the user provides no arguments to PolytopeMars then a config is loaded from the default locations:

1. System-wide configuration in /etc/polytope_mars/config.json (and yaml)
2. User configuration in ~/.polytope_mars.json (and yaml)

The user can also pass in a config as a python dictionary to PolytopeMars for a custom config at runtime. 

```python
from polytope_mars.api import PolytopeMars
from conflator import Conflator
from polytope_mars.config import PolytopeMarsConfig

conf = Conflator(app_name="polytope_mars", model=PolytopeMarsConfig).load()
cf = conf.model_dump()
cf["options"] = options

request = {
    "class": "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20231205",
    "time" : "00:00:00",
    "levtype" : "sfc",
    "expver" : "0001", 
    "domain" : "g",
    "param" : "228/49/164/165/166/167",
    "number" : "1/to/5",
    "step" : "0/1"
    "feature" : {
        "type" : "timeseries",
        "points" : [[51.5073219, 2.1]],
        "axis" : "step",
    },
}

result = PolytopeMars(cf).extract(request)

```

A context dictionary can also be passed to PolytopeMars for logging.

Result will be a coverageJSON file with the requested data if it is available, further manipulation of the coverage can be made using [covjsonkit](https://github.com/ecmwf/covjsonkit).

### Config

An example config can be found here [example_config.json](example_config.json). This can be edited to change any of the fields. The config is made up of three main components. 

1. **datacube:** This option is used to set up what type of datacube is being used at the moment, currently only gribjump is supported.
2. **options** These are the options used by polytope for interpreting the data available.
3. **coverageconfig** These options are used by convjsonkit to parse the output of polytope into coverageJSON.