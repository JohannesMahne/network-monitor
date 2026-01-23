"""Tests for monitor/bandwidth_monitor.py - Bandwidth throttling detection."""

from unittest.mock import patch

from monitor.bandwidth_monitor import BandwidthAlert, BandwidthMonitor, BandwidthSample


class TestBandwidthSample:
    """Tests for BandwidthSample dataclass."""

    def test_creation(self):
        """Test creating a bandwidth sample."""
        sample = BandwidthSample(timestamp=1234567890.0, bytes_in=1000, bytes_out=500)
        assert sample.timestamp == 1234567890.0
        assert sample.bytes_in == 1000
        assert sample.bytes_out == 500


class TestBandwidthAlert:
    """Tests for BandwidthAlert dataclass."""

    def test_creation(self):
        """Test creating a bandwidth alert."""
        alert = BandwidthAlert(
            app_name="Safari",
            current_mbps=15.5,
            threshold_mbps=10.0,
            window_seconds=30,
            timestamp=1234567890.0,
        )
        assert alert.app_name == "Safari"
        assert alert.current_mbps == 15.5
        assert alert.threshold_mbps == 10.0
        assert alert.window_seconds == 30


class TestBandwidthMonitor:
    """Tests for BandwidthMonitor class."""

    def test_init(self):
        """Test monitor initialization."""
        monitor = BandwidthMonitor()
        assert monitor._app_samples == {}
        assert monitor._previous_bytes == {}
        assert monitor._alerted_apps == {}
        assert monitor._alert_cooldown == 300.0

    def test_check_thresholds_empty_thresholds(self):
        """Test check_thresholds with no thresholds configured."""
        monitor = BandwidthMonitor()
        process_traffic = [("Safari", 1000, 500, 2)]

        alerts = monitor.check_thresholds(process_traffic, {})
        assert alerts == []

    def test_check_thresholds_no_matching_apps(self):
        """Test check_thresholds when no apps match thresholds."""
        monitor = BandwidthMonitor()
        process_traffic = [("Safari", 1000, 500, 2)]
        thresholds = {"Chrome": 10.0}

        alerts = monitor.check_thresholds(process_traffic, thresholds)
        assert alerts == []

    def test_check_thresholds_disabled_threshold(self):
        """Test check_thresholds ignores disabled (<=0) thresholds."""
        monitor = BandwidthMonitor()
        process_traffic = [("Safari", 1000, 500, 2)]
        thresholds = {"Safari": 0}  # Disabled

        alerts = monitor.check_thresholds(process_traffic, thresholds)
        assert alerts == []

    def test_check_thresholds_first_sample_no_alert(self):
        """Test that first sample doesn't trigger alert (need baseline)."""
        monitor = BandwidthMonitor()
        process_traffic = [("Safari", 1000, 500, 2)]
        thresholds = {"Safari": 0.001}  # Very low threshold

        alerts = monitor.check_thresholds(process_traffic, thresholds)
        assert alerts == []
        assert "Safari" in monitor._app_samples

    def test_check_thresholds_accumulates_samples(self):
        """Test that samples are accumulated over time."""
        monitor = BandwidthMonitor()
        thresholds = {"Safari": 100.0}  # High threshold, won't trigger

        # First call establishes baseline
        monitor.check_thresholds([("Safari", 1000, 500, 2)], thresholds)

        # Second call adds sample
        monitor.check_thresholds([("Safari", 2000, 1000, 2)], thresholds)

        assert len(monitor._app_samples["Safari"]) == 1

    @patch("monitor.bandwidth_monitor.time")
    def test_check_thresholds_triggers_alert(self, mock_time_module):
        """Test that threshold violation triggers alert."""
        monitor = BandwidthMonitor()

        # Simulate time progression
        mock_time_module.time.side_effect = [1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0]

        # 1 Mbps = 125,000 bytes/sec
        # Set threshold to 0.1 Mbps = 12,500 bytes/sec
        thresholds = {"Safari": 0.1}

        # First call - baseline
        monitor.check_thresholds([("Safari", 0, 0, 2)], thresholds)

        # Second call - accumulate bytes (100KB = way over threshold)
        monitor.check_thresholds([("Safari", 100000, 100000, 2)], thresholds)

        # Third call - check threshold
        alerts = monitor.check_thresholds([("Safari", 200000, 200000, 2)], thresholds)

        # Should trigger alert (high bandwidth)
        assert len(alerts) == 1
        assert alerts[0].app_name == "Safari"

    @patch("time.time")
    def test_check_thresholds_alert_cooldown(self, mock_time):
        """Test that alert cooldown prevents alert spam."""
        monitor = BandwidthMonitor()
        monitor._alert_cooldown = 60.0  # 60 second cooldown

        # Mark Safari as recently alerted
        mock_time.return_value = 1000.0
        monitor._alerted_apps["Safari"] = 990.0  # 10 seconds ago

        # Even with high bandwidth, should not alert due to cooldown
        thresholds = {"Safari": 0.1}

        # Set up samples manually to simulate threshold violation
        from collections import deque

        monitor._app_samples["Safari"] = deque(
            [
                BandwidthSample(998.0, 100000, 100000),
                BandwidthSample(999.0, 100000, 100000),
            ],
            maxlen=30,
        )
        monitor._previous_bytes["Safari"] = (200000, 200000)

        alerts = monitor.check_thresholds([("Safari", 300000, 300000, 2)], thresholds)

        # Should not trigger due to cooldown
        assert len(alerts) == 0

    def test_reset_alert_cooldown(self):
        """Test resetting alert cooldown for an app."""
        monitor = BandwidthMonitor()
        monitor._alerted_apps["Safari"] = 1234567890.0

        monitor.reset_alert_cooldown("Safari")

        assert "Safari" not in monitor._alerted_apps

    def test_reset_alert_cooldown_nonexistent(self):
        """Test reset_alert_cooldown for app that hasn't alerted."""
        monitor = BandwidthMonitor()

        # Should not raise
        monitor.reset_alert_cooldown("Chrome")

    def test_clear_samples(self):
        """Test clearing all samples."""
        monitor = BandwidthMonitor()

        # Add some data
        from collections import deque

        monitor._app_samples["Safari"] = deque([BandwidthSample(1.0, 100, 100)])
        monitor._previous_bytes["Safari"] = (100, 100)
        monitor._alerted_apps["Safari"] = 1000.0

        monitor.clear_samples()

        assert monitor._app_samples == {}
        assert monitor._previous_bytes == {}
        assert monitor._alerted_apps == {}
