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

* Time Series
* Vertical Profile
* Bounding Box
* Path
* WKT POLYGON shape
* Shape File
* Frame

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

**Create time series request**: Create a request for a time series request using the time series feature, set options and config for use by polytope feature extraction. NB: Assumes data is in a local FDB.

```python

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

```
