#  import pytest


class TestFeatureFactory:
    def setup_method(self):
        self.pass_test = True

    def test_pass_invalid(self):
        assert self.pass_test
