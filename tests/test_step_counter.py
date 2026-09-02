import pytest

from polytope_mars.utils.datetimes import _count_range_steps, count_steps


class TestStepCounter:
    """Test suite for MARS step string counting functionality."""

    def test_simple_list_format(self):
        """Test basic list format with simple numbers."""
        assert count_steps("0/1/2") == 3
        assert count_steps("0/1/2/3") == 4
        assert count_steps("5") == 1
        assert count_steps("0/5/10/15/20") == 5

    def test_list_format_with_time_units(self):
        """Test list format with time unit suffixes."""
        assert count_steps("1h/6h") == 2
        assert count_steps("1h/2h/3h/6h") == 4
        assert count_steps("30m/1h/90m") == 3
        assert count_steps("30s/1m/90s") == 3
        assert count_steps("1d/2d/3d") == 3

    def test_simple_range_format(self):
        """Test range format with simple numbers."""
        assert count_steps("0/to/10/by/2") == 6  # 0, 2, 4, 6, 8, 10
        assert count_steps("0/to/100/by/10") == 11  # 0, 10, 20, ..., 100
        assert count_steps("1/to/5/by/1") == 5  # 1, 2, 3, 4, 5
        assert count_steps("0/to/3/by/1") == 4  # 0, 1, 2, 3

    def test_range_format_default_increment(self):
        """Test range format with default 1h increment."""
        assert count_steps("0/to/10") == 11  # 0, 1, 2, ..., 10
        assert count_steps("1/to/5") == 5  # 1, 2, 3, 4, 5
        assert count_steps("1h/to/6h") == 6  # 1h, 2h, 3h, 4h, 5h, 6h

    def test_sub_hourly_ranges_minutes(self):
        """Test ranges with minute increments."""
        assert count_steps("1h/to/6h/by/30m") == 11  # 1h, 1h30m, 2h, ..., 6h
        assert count_steps("30m/to/2h/by/15m") == 7  # 30m, 45m, 1h, 1h15m, 1h30m, 1h45m, 2h
        assert count_steps("0h/to/1h/by/10m") == 7  # 0h, 10m, 20m, 30m, 40m, 50m, 1h

    def test_sub_hourly_ranges_seconds(self):
        """Test ranges with second increments."""
        assert count_steps("1h/to/1h30m/by/20s") == 91  # 1h to 1.5h in 20s increments
        assert count_steps("0s/to/1m/by/10s") == 7  # 0s, 10s, 20s, 30s, 40s, 50s, 60s
        assert count_steps("0s/to/2m/by/30s") == 5  # 0s, 30s, 1m, 1m30s, 2m
        assert count_steps("30s/to/90s/by/15s") == 5  # 30s, 45s, 60s, 75s, 90s

    def test_day_ranges(self):
        """Test ranges with day increments."""
        assert count_steps("1d/to/3d/by/1d") == 3  # 1d, 2d, 3d
        assert count_steps("0d/to/7d/by/1d") == 8  # 0d, 1d, 2d, ..., 7d
        assert count_steps("1d/to/5d/by/2d") == 3  # 1d, 3d, 5d

    def test_mixed_units(self):
        """Test ranges with mixed time units."""
        assert count_steps("30m/to/2h30m/by/30m") == 5  # 30m, 1h, 1h30m, 2h, 2h30m
        assert count_steps("0h/to/2h/by/45m") == 3  # 0h, 45m, 1h30m (approximately)

    def test_edge_cases(self):
        """Test edge cases and boundary conditions."""
        # Single value
        assert count_steps("0") == 1
        assert count_steps("1h") == 1

        # Same start and end
        assert count_steps("5/to/5/by/1") == 1
        assert count_steps("1h/to/1h/by/1h") == 1

        # Large ranges
        assert count_steps("0/to/1000/by/100") == 11

    def test_count_range_steps_direct(self):
        """Test the internal _count_range_steps function directly."""
        # Test with pure digits
        assert _count_range_steps("0", "10", "2") == 6
        assert _count_range_steps("1", "5", "1") == 5

        # Test with hours
        assert _count_range_steps("1h", "6h", "1h") == 6
        assert _count_range_steps("0h", "24h", "6h") == 5

        # Test with minutes
        assert _count_range_steps("0m", "60m", "15m") == 5

        # Test with seconds
        assert _count_range_steps("0s", "60s", "10s") == 7

        # Test with days
        assert _count_range_steps("1d", "7d", "1d") == 7

    def test_real_world_examples(self):
        """Test with real-world MARS request examples."""
        # Common forecast steps
        assert count_steps("0/to/240/by/6") == 41  # 10-day forecast every 6 hours
        assert count_steps("0/3/6/9/12") == 5  # Specific forecast hours

        # Sub-hourly forecasts
        assert count_steps("0h/to/12h/by/15m") == 49  # 12 hours in 15-minute increments

        # Mixed step definitions
        assert count_steps("0/1/2/3/6/9/12/18/24") == 9

    def test_invalid_formats_gracefully_handled(self):
        """Test that the function handles unusual but parseable inputs."""
        # These should still work with our implementation
        assert count_steps("1") == 1
        assert count_steps("1/2") == 2


if __name__ == "__main__":
    # Run with pytest
    pytest.main([__file__, "-v"])
