from polytope_feature import shapes


def validate_labels(labels, n_units, feature_name, unit_name):
    """Check that optional feature labels are a list of str/int with one entry per unit."""
    if labels is None:
        return
    if not isinstance(labels, list):
        raise ValueError(f"{feature_name} labels must be a list")
    if len(labels) != n_units:
        raise ValueError(f"Number of labels ({len(labels)}) must match number of {unit_name} ({n_units})")
    for label in labels:
        if isinstance(label, bool) or not isinstance(label, (str, int)):
            raise ValueError(f"{feature_name} labels must be strings or integers, got {label!r}")


def tagged_point_union(axes, points, labels=None):
    """Union of nearest-neighbour Points, each tagged (index, label).

    The tags let points that snap to the same grid point be separated downstream, in request order.
    A Union of single Points is used because the multi-point shapes.Point only takes one tag.
    """
    if labels is None:
        labels = [None] * len(points)
    return shapes.Union(
        axes,
        *[
            shapes.Point(axes, [list(p)], method="nearest", tag=(i, label))
            for i, (p, label) in enumerate(zip(points, labels))
        ],
    )


def tagged_multi_point(axes, points, labels=None):
    """Single nearest-neighbour multi-point Point, with one (index, label) tag per point.

    The tags let points that snap to the same grid point be separated downstream, in request order.
    Needs a polytope Point that accepts a list of per-point tags.
    """
    if labels is None:
        labels = [None] * len(points)
    return shapes.Point(axes, [list(p) for p in points], method="nearest", tag=list(enumerate(labels)))
