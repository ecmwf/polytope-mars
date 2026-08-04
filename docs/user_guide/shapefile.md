# Shapefile

## Basic Example

An example shapefile request via Earthkit-data:

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
        "type" : "shapefile",
        "file" : "path/to/shape.shp",
    },
    "format" : "covjson",
}

ds = earthkit.data.from_source("polytope", "ecmwf-mars", request, stream=False, address='polytope.ecmwf.int')
```

This request returns all grid points contained within the geometry read from
the shapefile, for forecast date `20240930T000000`, `step` `0`, ensemble
`number` `1`, and the three requested parameters.

The shapefile is read with [GeoPandas](https://geopandas.org/). `Polygon` and
`MultiPolygon` geometries are converted to one or more polygons internally and
treated the same way as the [Polygon](polygon.md) feature. Note that only the
first geometry (row) in the shapefile is currently used.

`"polytope"` refers to the underlying service being used to return the data. `"ecmwf-mars"` is the dataset we are looking to retrieve from. Setting `stream=False` returns all the requested data to us once it is available. `address` points to the endpoint for the polytope server.

Notes:
* The data has to exist in the fdb on the polytope server.
* No config is required to be passed when using this method, it is generated on the server side.
* The shapefile must be readable by GeoPandas and accessible from the machine running the request.
* Further details on the `from_source` method can be found here: https://earthkit-data.readthedocs.io/en/latest/guide/sources.html

## Required Fields

For a shapefile within the `feature` dictionary two fields are required

* `type`
* `file`

For a shapefile `type` must be `shapefile`.

`file` is the path to a shapefile on disk that can be read by GeoPandas. The
geometry contained in the file defines the region for which grid points are
returned.

## Related

The shapefile feature reuses the same underlying polygon extraction as the
[Polygon](polygon.md) feature; see that page for details on how points inside a
polygon are selected.
