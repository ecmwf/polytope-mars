# Position

## Basic Example

An example position request via Earthkit-data:

```python
import earthkit.data

request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "levtype" : "sfc",
    "expver" : "0079",
    "domain" : "g",
    "param" : "164/167/169",
    "number" : "1",
    "step" : "0",
    "feature" : {
        "type" : "position",
        "points" : [[-9.10, 38.78], [51.5, 0.1]],
    },
    "format" : "covjson",
}

ds = earthkit.data.from_source("polytope", "ecmwf-mars", request, stream=False, address='polytope.ecmwf.int')
```

This request returns the value at the **nearest grid point** to each requested
point, for forecast date `20240930T000000`, `step` `0`, ensemble `number` `1`,
and the three requested parameters. The result is returned as a point series.

Position differs from [Time Series](timeseries.md) in that it snaps each
requested coordinate to the single nearest grid point rather than generating a
series along a time axis.

`"polytope"` refers to the underlying service being used to return the data. `"ecmwf-mars"` is the dataset we are looking to retrieve from. Setting `stream=False` returns all the requested data to us once it is available. `address` points to the endpoint for the polytope server.

Notes:
* The data has to exist in the fdb on the polytope server.
* No config is required to be passed when using this method, it is generated on the server side.
* Further details on the `from_source` method can be found here: https://earthkit-data.readthedocs.io/en/latest/guide/sources.html

## Required Fields

For a position within the `feature` dictionary two fields are required

* `type`
* `points`

For a position `type` must be `position`.

`points` is a nested list of one or more points. Each point corresponds to a
`[latitude, longitude]`.

## Optional Fields

`axes` refers to the axes on which to generate the position. The default is
`["latitude", "longitude"]`. Only `latitude` and `longitude` are permitted for
the position feature; time axes such as `step` or `date` are not allowed and
will raise an error.
