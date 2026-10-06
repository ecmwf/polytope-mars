# Bounding Box

## Basic Example

<!-- ### Polytope-mars

A basic example of requesting a trajectory using polytope-mars:

```python
from polytope_mars.api import PolytopeMars

request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "expver" : "0079",
    "domain" : "g",
    "param" : "164/167/169",
    "levtype" : "pl",
    "number" : "1",
    "feature" : {
        "type" : "boundingbox",
        "points" : [[-1, -1], [1, 1]],
	},
    "format" : "covjson",
}

result = PolytopeMars().extract(request)
```

This request will return a bounding box with forecast date of `20240930T000000` for the three requested parameters for the points within a bounding box with lower-left (south-west) corner at latitude -1 and longitude -1, and upper-right (north-east) corner at latitude 1 and longitude 1.



Notes:
* The data has to exist in the data source pointed to in the config.
* No config is provided via the PolytopeMars interface so a config will be loaded from the default locations. The config can also be passed directly via the interface.

### Earthkit-data -->

An example bounding box requested via Earthkit-data:

```python
import earthkit.data

request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "expver" : "0079",
    "domain" : "g",
    "param" : "164/167/169",
    "levtype" : "sfc",
    "number" : "1",
    "feature" : {
        "type" : "boundingbox",
        "points" : [[-1, -1], [1, 1]],
	},
    "format" : "covjson",
}

ds = earthkit.data.from_source("polytope", "ecmwf-mars", request, stream=False, address='polytope.ecmwf.int')
```

This request will return a bounding box with forecast date of `20240930T000000` for the three requested parameters for the points within a bounding box with lower-left (south-west) corner at latitude -1 and longitude -1, and upper-right (north-east) corner at latitude 1 and longitude 1.

`"polytope"` refers to the underlying service being used to return the data. `"emcwf-mars"` is the dataset we are looking to retrieve from. Setting `stream=False` returns all the requested data to us once it is available. `address` points to the endpoint for the polytope server.

Notes:
* The data has to exist in the fdb on the polytope server.
* No config is required to be passed when using this method, it is generated on the server side.
* Further details on the `from_source` method can be found here: https://earthkit-data.readthedocs.io/en/latest/guide/sources.html

## Required Fields

For a boundingbox within the `feature` dictionary two fields are required

* `type`
* `points`

For a bounding box `type` must be `boundingbox`.

`points` must contain two points, the first corresponding to the lower-left (south-west) corner of the requested box, and the second corresponding to the upper-right (north-east) corner. By default they should only contain a latitude and longitude. However as seen below this can be changed with the `axes` key.

## Longitude conventions and meridian crossing

The two points define the box corners as `[[south, west], [north, east]]`
(lower-left, then upper-right — matching the OGC EDR corner semantics). The
box is always the arc swept **eastward from the west edge to the east edge**,
so the order of the two longitudes is what selects the region.

Longitudes may be supplied either as signed values (`[-180, 180]`) or wrapped
values (`[0, 360)`); they are normalised internally as needed, so the same
physical box can be requested in either convention.

Meridian- and antimeridian-crossing boxes are supported directly — you do not
need to split the request manually:

* A box that already sweeps west-to-east (west longitude numerically less than
  east) is used as given, e.g. `[[-1, 170], [1, 190]]`.
* A box crossing the prime meridian works with signed longitudes, e.g.
  `[[-1, -0.1], [1, 0.1]]`, and equivalently with wrapped longitudes
  `[[-1, 359.9], [1, 0.1]]`.
* A box crossing the antimeridian, e.g. `[[-1, 179.9], [1, -179.9]]`, is
  handled automatically by splitting internally at ±180.

Equal longitudes define a **zero-width** box on a single meridian rather than a
full sweep: `[[0, 10], [1, 10]]` selects only longitude `10` (grid points that
land exactly on that meridian are returned). To request a full wrap-around,
specify the east edge as the west edge plus 360, e.g. `[[0, 10], [1, 370]]` (or
`[[0, 0], [1, 360]]`).

Latitude must satisfy `south <= north` and lie within `[-90, 90]`; otherwise
the request is rejected.

## Optional Fields

`axes` refers to the axes on which to generate the bounding box. As stated above the minimum default `axes` contains `latitude` and `longitude` meaning if `axes` is not included these values must be provided per point. By default the level is taken from the main body of the request.

However `axes` can also be provided by the user and with a value for level. Such as here:

```python
"axes" : ["latitude", "longitude", "levelist"]
```

In this case the user must provide a `latitude`, `longitude` and `levelist`. `levelist` should not be included in the main body of the request in this case. An example can be seen here:


```python
request = {
    "class" : "od",
    "stream" : "enfo",
    "type" : "pf",
    "date" : "20240930",
    "time" : "0000",
    "expver" : "0079",
    "domain" : "g",
    "param" : "164/167/169",
    "levtype" : "pl",
    "number" : "1",
    "feature" : {
        "type" : "boundingbox",
        "points" : [[-1, -1, 1000], [1, 1, 500]],
        "axes" : ["latitude", "longitude", "levelist"],
	},
    "format" : "covjson",
}
```

For this request a bounding box with lower-left (south-west) corner at lat -1, long -1 and pressure level 1000, and upper-right (north-east) corner at lat 1, long 1, and pressure level 500.

Without level in the `axes` this will be taken from the main body of the request. In the case of `levtype` = `sfc`, no levelist is required.
