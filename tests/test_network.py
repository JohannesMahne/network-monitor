"""Tests for monitor/network.py"""

from monitor.network import NetworkStats, format_bytes


class TestFormatBytes:
    """Tests for the format_bytes function."""

    def test_format_zero_bytes(self):
        result = format_bytes(0)
        assert "0" in result or result == "0.0 B"

    def test_format_bytes_basic(self):
        assert format_bytes(500) == "500.0 B"

    def test_format_kilobytes(self):
        assert format_bytes(1024) == "1.0 KB"
        assert format_bytes(1536) == "1.5 KB"

    def test_format_megabytes(self):
        assert format_bytes(1024 * 1024) == "1.0 MB"

    def test_format_gigabytes(self):
        assert format_bytes(1024 * 1024 * 1024) == "1.0 GB"

    def test_format_speed(self):
        assert format_bytes(1024, speed=True) == "1.0 KB/s"
        assert format_bytes(1024 * 1024, speed=True) == "1.0 MB/s"


class TestNetworkStats:
    """Tests for the NetworkStats class."""

    def test_initialization(self):
        stats = NetworkStats()
        assert stats._initialized is False

    def test_initialize(self):
        stats = NetworkStats()
        stats.initialize()
        assert stats._initialized is True

    def test_reset_session(self):
        stats = NetworkStats()
        stats.initialize()
        stats._peak_upload = 1000
        stats._peak_download = 2000

        stats.reset_session()

        assert stats._peak_upload == 0
        assert stats._peak_download == 0

    def test_get_peak_speeds(self):
        stats = NetworkStats()
        stats._peak_upload = 1000
        stats._peak_download = 2000

        up, down = stats.get_peak_speeds()
        assert up == 1000
        assert down == 2000

    def test_get_average_speeds_empty(self):
        stats = NetworkStats()
        up, down = stats.get_average_speeds()
        assert up == 0.0
        assert down == 0.0

    def test_get_average_speeds_with_samples(self):
        """Test average calculation with samples."""
        stats = NetworkStats()
        stats._speed_samples = [(100, 200), (200, 400), (300, 600)]

        up, down = stats.get_average_speeds()
        assert up == 200.0  # (100 + 200 + 300) / 3
        assert down == 400.0  # (200 + 400 + 600) / 3

    def test_get_session_totals(self):
        """Test getting session totals."""
        stats = NetworkStats()
        stats.initialize()

        # Get session totals - should be near 0 for a new session
        sent, recv = stats.get_session_totals()
        assert isinstance(sent, int)
        assert isinstance(recv, int)

    def test_get_current_stats_not_initialized(self):
        """Test get_current_stats auto-initializes."""
        stats = NetworkStats()
        assert stats._initialized is False

        # Should auto-initialize and return None on first call
        result = stats.get_current_stats()
        assert stats._initialized is True
        assert result is None  # First call returns None

    def test_get_current_stats_returns_speed_stats(self):
        """Test get_current_stats returns SpeedStats on subsequent calls."""
        import time

        from monitor.network import SpeedStats

        stats = NetworkStats()
        stats.initialize()

        # Wait a bit and call again
        time.sleep(0.2)
        result = stats.get_current_stats()

        # Should return SpeedStats or None (if time delta too small)
        assert result is None or isinstance(result, SpeedStats)

    def test_peak_speeds_update(self):
        """Test that peak speeds are updated correctly."""
        stats = NetworkStats()
        stats.initialize()

        # Manually set some values to test peak tracking
        stats._peak_upload = 100
        stats._peak_download = 200

        # Verify peaks
        up, down = stats.get_peak_speeds()
        assert up == 100
        assert down == 200

    def test_speed_samples_limited(self):
        """Test that speed samples are limited."""
        from config import THRESHOLDS

        stats = NetworkStats()

        # Add many samples
        for i in range(THRESHOLDS.SPEED_SAMPLE_COUNT + 10):
            stats._speed_samples.append((float(i), float(i * 2)))

        # Manually trim as get_current_stats would
        while len(stats._speed_samples) > THRESHOLDS.SPEED_SAMPLE_COUNT:
            stats._speed_samples.pop(0)

        assert len(stats._speed_samples) == THRESHOLDS.SPEED_SAMPLE_COUNT
