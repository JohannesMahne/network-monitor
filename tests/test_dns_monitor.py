"""Tests for monitor/dns_monitor.py - DNS performance monitoring."""

from collections import deque
from unittest.mock import patch

from monitor.dns_monitor import DNSMonitor


class TestDNSMonitor:
    """Tests for DNSMonitor class."""

    def test_init(self):
        """Test monitor initialization."""
        monitor = DNSMonitor()
        assert isinstance(monitor._latency_samples, deque)
        assert monitor._last_check == 0
        assert monitor._check_interval > 0
        assert monitor._slow_dns_threshold > 0

    def test_test_domains_defined(self):
        """Test that test domains are defined."""
        assert len(DNSMonitor.TEST_DOMAINS) > 0
        assert "google.com" in DNSMonitor.TEST_DOMAINS

    @patch("socket.gethostbyname")
    @patch("time.time")
    def test_check_dns_performance_success(self, mock_time, mock_gethostbyname):
        """Test successful DNS performance check."""
        monitor = DNSMonitor()

        # Mock time to always check
        mock_time.return_value = 1000.0
        monitor._last_check = 0  # Force check

        # Mock fast DNS resolution
        mock_gethostbyname.return_value = "142.250.80.46"

        result = monitor.check_dns_performance(force=True)

        assert result is not None
        assert result >= 0
        assert len(monitor._latency_samples) > 0

    @patch("socket.gethostbyname")
    def test_check_dns_performance_all_fail(self, mock_gethostbyname):
        """Test DNS check when all resolutions fail."""
        monitor = DNSMonitor()
        monitor._last_check = 0

        # Mock DNS failure
        mock_gethostbyname.side_effect = Exception("DNS resolution failed")

        result = monitor.check_dns_performance(force=True)

        assert result is None

    @patch("time.time")
    def test_check_dns_performance_interval_not_elapsed(self, mock_time):
        """Test that check is skipped if interval hasn't elapsed."""
        monitor = DNSMonitor()

        # Set last check to now
        mock_time.return_value = 1000.0
        monitor._last_check = 1000.0  # Just checked

        # Add a sample so get_average returns something
        monitor._latency_samples.append(50.0)

        result = monitor.check_dns_performance(force=False)

        # Should return cached average, not do new check
        assert result == 50.0

    @patch("socket.gethostbyname")
    def test_resolve_domain_success(self, mock_gethostbyname):
        """Test successful domain resolution."""
        monitor = DNSMonitor()
        mock_gethostbyname.return_value = "142.250.80.46"

        result = monitor._resolve_domain("google.com")

        assert result is not None
        assert result >= 0
        mock_gethostbyname.assert_called_once_with("google.com")

    @patch("socket.gethostbyname")
    def test_resolve_domain_failure(self, mock_gethostbyname):
        """Test domain resolution failure."""
        monitor = DNSMonitor()
        mock_gethostbyname.side_effect = Exception("DNS error")

        result = monitor._resolve_domain("nonexistent.invalid")

        assert result is None

    def test_get_average_dns_latency_empty(self):
        """Test get_average_dns_latency with no samples."""
        monitor = DNSMonitor()

        result = monitor.get_average_dns_latency()

        assert result is None

    def test_get_average_dns_latency_with_samples(self):
        """Test get_average_dns_latency with samples."""
        monitor = DNSMonitor()
        monitor._latency_samples.extend([10.0, 20.0, 30.0])

        result = monitor.get_average_dns_latency()

        assert result == 20.0  # (10 + 20 + 30) / 3

    def test_get_current_dns_latency_empty(self):
        """Test get_current_dns_latency with no samples."""
        monitor = DNSMonitor()

        result = monitor.get_current_dns_latency()

        assert result is None

    def test_get_current_dns_latency_with_samples(self):
        """Test get_current_dns_latency returns most recent."""
        monitor = DNSMonitor()
        monitor._latency_samples.extend([10.0, 20.0, 30.0])

        result = monitor.get_current_dns_latency()

        assert result == 30.0  # Most recent

    def test_is_dns_slow_no_samples(self):
        """Test is_dns_slow with no samples."""
        monitor = DNSMonitor()

        result = monitor.is_dns_slow()

        assert result is False

    def test_is_dns_slow_fast_dns(self):
        """Test is_dns_slow with fast DNS."""
        monitor = DNSMonitor()
        monitor._slow_dns_threshold = 200.0
        monitor._latency_samples.extend([10.0, 20.0, 30.0])

        result = monitor.is_dns_slow()

        assert result is False

    def test_is_dns_slow_slow_dns(self):
        """Test is_dns_slow with slow DNS."""
        monitor = DNSMonitor()
        monitor._slow_dns_threshold = 100.0
        monitor._latency_samples.extend([200.0, 250.0, 300.0])

        result = monitor.is_dns_slow()

        assert result is True

    def test_clear_samples(self):
        """Test clearing DNS samples."""
        monitor = DNSMonitor()
        monitor._latency_samples.extend([10.0, 20.0, 30.0])

        monitor.clear_samples()

        assert len(monitor._latency_samples) == 0
