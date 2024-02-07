from typing import List
from ..feature import Feature
from polytope import shapes

class TimeSeries(Feature):

    def __init__(self, config):
        
        assert config.pop('type') == "timeseries"
        self.start_step = config.pop('start', None)
        self.end_step = config.pop('end', None)        

        self.points = config.pop('points', [])

        assert len(config) == 0, f"Unexpected keys in config: {config.keys()}"

    def get_shapes(self):

        # Time-series is a squashed box from start_step to start_end for each point
        return [shapes.Union(["latitude", "longitude"],
            *[shapes.Point(["latitude", "longitude"], [[p[0],p[1]]], method="nearest") for p in self.points]), shapes.Span("step", self.start_step, self.end_step)]

        

    def incompatible_keys(self):
        return ["step", "levellist"]

    def coverage_type(self):
        return "PointSeries"
    
    def name(self):
        return "Time Series"
    

