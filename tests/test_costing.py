import math

from polytope_mars.utils.areas import request_cost


class TestCosting:
    def setup_method(self):

        self.bbox_request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": "20250114",
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "step": "0/to/3",
            "feature": {
                "type": "boundingbox",
                "points": [[0, 0], [1, 1]],
                "axes": ["longitude", "latitude"],
            },
        }

        self.polygon_request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": "20250715",
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "step": "0/to/3",
            "feature": {
                "type": "polygon",
                "shape": [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]],
            },
        }

        self.timeseries_request = {
            "class": "od",
            "stream": "enfo",
            "type": "pf",
            "date": "20250114",
            "time": "0000",
            "levtype": "sfc",
            "expver": "0001",
            "domain": "g",
            "param": "167",
            "number": "1",
            "step": "0/to/3",
            "feature": {
                "type": "timeseries",
                "points": [[-9.10, 38.78]],
                "axes": ["longitude", "latitude"],
            },
        }

    # @pytest.mark.skip(reason="Gribjump not set up for ci actions yet")
    def test_timeseries_cost(self):
        request_cost_value = request_cost(self.timeseries_request)
        assert request_cost_value == 4

        self.timeseries_request["number"] = "1/to/2"
        assert request_cost(self.timeseries_request) == 8

        self.timeseries_request["step"] = "0/to/6"
        assert request_cost(self.timeseries_request) == 14

        self.timeseries_request["dataset"] = "reanalysis"
        assert request_cost(self.timeseries_request) == 28

    def test_boundingbox_cost(self):
        tolerance = 10

        request_cost_value = request_cost(self.bbox_request)
        assert math.isclose(
            request_cost_value, 49235, abs_tol=tolerance
        ), f"Value {request_cost_value} is not within {tolerance} of {49235}"

        self.bbox_request["number"] = "1/to/2"
        request_cost_value = request_cost(self.bbox_request)
        assert math.isclose(
            request_cost_value, 49235 * 2, abs_tol=tolerance
        ), f"Value {request_cost_value} is not within {tolerance} of {49235 * 2}"

        self.bbox_request["step"] = "0/to/7"
        request_cost_value = request_cost(self.bbox_request)
        assert math.isclose(
            request_cost_value, 49235 * 2 * 2, abs_tol=tolerance
        ), f"Value {request_cost_value} is not within {tolerance} of {49235 * 2 * 2}"

    def test_polygon_cost(self):
        tolerance = 10

        request_cost_value = request_cost(self.polygon_request)
        assert math.isclose(
            request_cost_value, 49235, abs_tol=tolerance
        ), f"Value {request_cost_value} is not within {tolerance} of {49235}"

        self.polygon_request["number"] = "1/to/2"
        request_cost_value = request_cost(self.polygon_request)
        assert math.isclose(
            request_cost_value, 49235 * 2, abs_tol=tolerance
        ), f"Value {request_cost_value} is not within {tolerance} of {49235 * 2}"

        self.polygon_request["step"] = "0/to/7"
        request_cost_value = request_cost(self.polygon_request)
        assert math.isclose(
            request_cost_value, 49235 * 2 * 2, abs_tol=tolerance
        ), f"Value {request_cost_value} is not within {tolerance} of {49235 * 2 * 2}"
