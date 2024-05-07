# polytope-mars

> [!WARNING]
> This project is BETA and will be experimental for the forseable future. Interfaces and functionality are likely to change, and the project itself may be scrapped. DO NOT use this software in any project/software that is operational.

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
pip install -e .
```

Currently no pypi package available. WIll be added in the future.

## Usage

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
    "feature" : {
        "type" : "timeseries",
        "points": [[51.5073219, 2.1]],
        "start": 0,
        "end" : 9
    },
}

```
