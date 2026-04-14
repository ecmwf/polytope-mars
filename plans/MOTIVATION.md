# Motivation: Why Polytope-Mars Exists

## The Problem

ECMWF's Meteorological Archival and Retrieval System (MARS) is designed for field-level data retrieval — users request 2D grids of weather parameters. But downstream consumers increasingly need **meteorological features**: a time series at a specific location, a vertical profile through the atmosphere, all data points within a polygon, or observations along an aircraft trajectory.

Extracting these features from gridded data today requires users to:

1. Retrieve entire global fields (far more data than needed)
2. Post-process the fields client-side to extract the feature of interest
3. Handle coordinate systems, grid types (octahedral reduced Gaussian), and data formats manually

This wastes bandwidth, compute, and developer time. The data they actually need — a few hundred points from a time series, or a spatial cutout — is a tiny fraction of the full field.

## Why Not Just Use Polytope Directly?

[Polytope](https://github.com/ecmwf/polytope) is ECMWF's low-level feature extraction engine. It operates on N-dimensional datacubes using geometric shapes (points, boxes, polygons, paths, disks) to extract data efficiently — without retrieving full fields.

However, polytope-python is a **geometry library**, not a **meteorological API**. Using it directly requires:

- Understanding polytope's shape primitives (Select, Span, Union, Point, Box, Polygon, Path, Disk, Ellipsoid)
- Knowing how MARS axes map to datacube dimensions
- Manually configuring axis transformations (octahedral grid mapping, date/time merging, cyclic longitude wrapping)
- Handling MARS-specific conventions (range syntax like `0/to/360/by/6`, parameter ID resolution, ensemble numbers)
- Encoding results into a standard output format

This is too low-level for most data consumers.

## What We're Building

A **high-level meteorological feature extraction API** that sits between MARS-like requests and the Polytope engine. Users write requests in familiar MARS syntax, augmented with a `feature` keyword, and receive [CoverageJSON](https://covjson.org/) — a standard format for geospatial coverage data.

### Core Properties

1. **MARS-like request syntax** — users specify class, stream, type, date, param, etc. exactly as they would in a MARS request
2. **Feature keyword** — a single `feature` dictionary declares the extraction type (timeseries, vertical profile, bounding box, polygon, trajectory, etc.) and its geometry
3. **Automatic shape translation** — the library converts MARS range syntax and feature geometry into polytope shapes
4. **CoverageJSON output** — results are encoded as CoverageJSON via [covjsonkit](https://github.com/ecmwf/covjsonkit), ready for visualization or downstream processing
5. **Configurable datacube backend** — currently GribJump for GRIB data in ECMWF's FDB
6. **Request validation and cost control** — validates feature/request compatibility, estimates request cost, enforces area limits

### Target Users

- ECMWF data consumers using the Polytope web service
- [earthkit-data](https://earthkit-data.readthedocs.io/) users accessing data via the Polytope source
- Climate-DT users requesting feature extractions from climate datasets
- Application developers building weather data APIs

### Supported Features

| Feature | Geometry | Output Type |
|---------|----------|-------------|
| Time Series | Point(s) + time axis | PointSeries |
| Vertical Profile | Point(s) + level axis | VerticalProfile |
| Bounding Box | Two corner points | MultiPoint |
| Polygon | Closed polygon shape(s) | MultiPoint |
| Circle | Center + radius | MultiPoint |
| Frame | Outer box - inner box | MultiPoint |
| Trajectory | Path of 2D/3D/4D points | Trajectory |
| Position | Point(s), no time axis | PointSeries |
| Shapefile | Polygons from .shp file | MultiPoint |

### Constraints

- Must be pip-installable with minimal dependencies
- Must work with ECMWF's operational GribJump/FDB infrastructure
- Must support both operational forecasts and climate-DT datasets
- CoverageJSON is the only output format currently supported
- Request cost must be estimable and limitable to prevent runaway queries

## Success Criteria

1. **Correct feature extraction**: Output matches what a user would get by retrieving full fields and post-processing manually
2. **All feature types functional**: Time series, vertical profiles, bounding boxes, polygons, circles, frames, trajectories, positions, and shapefiles
3. **MARS compatibility**: Any valid MARS request should accept a valid `feature` and produce a valid polytope-mars request
4. **Cost control**: Requests exceeding configured area/size limits are rejected with clear error messages
5. **CoverageJSON conformance**: Output is valid CoverageJSON consumable by covjsonkit and standard viewers
