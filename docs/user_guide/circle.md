# Circle

## Basic Example

An example circle requested via Earthkit-data:

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
        "type" : "circle",
        "center" : [[0, 0]],
        "radius" : 1,
    },
    "format" : "covjson",
}

ds = earthkit.data.from_source("polytope", "ecmwf-mars", request, stream=False, address='polytope.ecmwf.int')
```

This request will return all grid points that fall within a circle of radius
`1` degree, centred on latitude `0`, longitude `0`, for forecast date
`20240930T000000`, `step` `0`, ensemble `number` `1`, and the three requested
parameters.

`"polytope"` refers to the underlying service being used to return the data. `"ecmwf-mars"` is the dataset we are looking to retrieve from. Setting `stream=False` returns all the requested data to us once it is available. `address` points to the endpoint for the polytope server.

Notes:
* The data has to exist in the fdb on the polytope server.
* No config is required to be passed when using this method, it is generated on the server side.
* Further details on the `from_source` method can be found here: https://earthkit-data.readthedocs.io/en/latest/guide/sources.html

## Required Fields

For a circle within the `feature` dictionary three fields are required

* `type`
* `center`
* `radius`

For a circle `type` must be `circle`.

`center` is a nested list containing a single point. By default this point
corresponds to a `[latitude, longitude]`, e.g. `[[0, 0]]`.

`radius` is the radius of the circle in degrees. Points on the underlying grid
that fall within this radius of the `center` are returned.

The circle feature is constrained by the `max_area` in the config; a circle
whose area exceeds this value is rejected.

## Optional Fields

`axes` refers to the axes on which to generate the circle. The default is
`["latitude", "longitude"]`. If provided, the number of values in `axes` must
match the number of values in each `center` point. A third axis (e.g.
`levelist`) may be added, in which case each `center` point must contain a
matching third value:

```python
"feature" : {
    "type" : "circle",
    "center" : [[0, 0, 500]],
    "radius" : 1,
    "axes" : ["latitude", "longitude", "levelist"],
}
```
