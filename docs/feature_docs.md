<h3 align="center">
<img src="./images/ECMWF_logo.svg.png" width=60%>
</br>

# Polytope-mars

## Feature Documentation

### Feature Keyword

Feature extraction expands existing mars requests to include a `feature` keyword that includes a json dictionary taht describes the given feature. This feature is then extracted using the Polytope feature extraction algoithm and only points within the given feature are returned.

```python
"feature" : {
    "type" : "timeseries",
    "points" : [[-9.109280931080349, 38.78655345978706]],
}
```

#### Type

An example of a minimal feature of `type` : `timeseries` can be seen above. A feature dictionary must always contain a `type`. The `type` in this case refers to what feature is being requested, the `type` of feaature requested will then determine the format of the output returned, what other keys can go in the feature and suitable defaults if they are not available. In some cases it may also affect keys outside of the feature dictionary that come from the traditional mars request. For example if `type` : `verticalprofile` and `levtype` : `sfc`, this request wont be sent as a vertical profile expects either `levtype` : `pl/ml`. Other exceptions will be given for each seperate feature `type`.

The value available for `type` currently are as follows:

* `timeseries`
* `verticalprofile`
* `polygon`
* `trajectory`
* `frame`
* `boundingbox`

More feature types will be added in the future.

#### Geometry

A feature dictionary must also contain the requested geometry in some form. For a `timeseries` as seen above this comes in the form `points` which requests a timeseries at a given point, however this geometry is not always a point and depends upon `type`. The geometry is a mandatory field for all features.

#### Axis

A non mandatory field that is available for each feature that isnt present in the above example is `axis`. `axis` determines what field that the data should be enumerated along. In the case of a `timeseries` this will default to `step` meaning the timeseries will be along the `step` axis, however there are other available `axis` such as `datetime`, this would be for climate data which contains no `step` `axis`.

#### Range

`range` is a json dictionary that is available for some features, it contains the extents of a given a `axes`. For example:

```python
"range" : {
    "start" : 0,
    "end" : 10,
    "step" : 2,
}
```

If this range was included in the above feature dictionary for a `timeseries` it would ask for `step` (due to it being the default axis for timeseries) starting at `0` and ending at `10` with an interval of `2`, the returned steps would be `0,2,4,6,8,10`. Or equivilint to asking for the following in a mars request.

```python
"step" : "0/to/10/by/2"
```

The above can also be put in the not feature key however it must then be mutually exclusive with `range`. If both or neither are in the request an error is thrown.

`range` can also appear in the following form:

```python
"range" : [0,1,4,7,10]
```

This will only return the asked steps similar to in a mars request where a user asks for the following:

```python
"step" : "0/1/4/7/10"
```

Again either a `range` within the feature or an explicit `step` within the main body of the request can be used but not both or neither as there is no suitable default value unlike mars.


### MARS Fields

