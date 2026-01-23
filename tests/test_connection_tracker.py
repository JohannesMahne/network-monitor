"""Tests for monitor/connection_tracker.py - External connection tracking."""

from unittest.mock import MagicMock, patch

from monitor.connection_tracker import ConnectionInfo, ConnectionTracker


class TestConnectionInfo:
    """Tests for ConnectionInfo dataclass."""

    def test_creation_minimal(self):
        """Test creating ConnectionInfo with minimal fields."""
        info = ConnectionInfo(remote_ip="8.8.8.8", remote_port=443, local_port=54321)
        assert info.remote_ip == "8.8.8.8"
        assert info.remote_port == 443
        assert info.local_port == 54321
        assert info.country_code is None
        assert info.bytes_transferred == 0
        assert info.last_seen == 0

    def test_creation_full(self):
        """Test creating ConnectionInfo with all fields."""
        info = ConnectionInfo(
            remote_ip="8.8.8.8",
            remote_port=443,
            local_port=54321,
            country_code="US",
            bytes_transferred=1024,
            last_seen=1234567890.0,
        )
        assert info.country_code == "US"
        assert info.bytes_transferred == 1024
        assert info.last_seen == 1234567890.0


class TestConnectionTracker:
    """Tests for ConnectionTracker class."""

    def test_init_without_geolocation(self):
        """Test tracker initialization without geolocation service."""
        tracker = ConnectionTracker()
        assert tracker._geolocation is None
        assert tracker._app_connections == {}
        assert tracker._seen_ips == set()

    def test_init_with_geolocation(self):
        """Test tracker initialization with geolocation service."""
        mock_geo = MagicMock()
        tracker = ConnectionTracker(geolocation_service=mock_geo)
        assert tracker._geolocation is mock_geo

    def test_is_external_ip_private_10(self):
        """Test is_external_ip returns False for 10.x.x.x."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("10.0.0.1") is False

    def test_is_external_ip_private_192(self):
        """Test is_external_ip returns False for 192.168.x.x."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("192.168.1.1") is False

    def test_is_external_ip_private_172(self):
        """Test is_external_ip returns False for 172.16-31.x.x."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("172.16.0.1") is False
        assert tracker._is_external_ip("172.31.255.255") is False

    def test_is_external_ip_loopback(self):
        """Test is_external_ip returns False for loopback."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("127.0.0.1") is False

    def test_is_external_ip_link_local(self):
        """Test is_external_ip returns False for link-local."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("169.254.1.1") is False

    def test_is_external_ip_public(self):
        """Test is_external_ip returns True for public IPs."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("8.8.8.8") is True
        assert tracker._is_external_ip("1.1.1.1") is True
        assert tracker._is_external_ip("142.250.80.46") is True

    def test_is_external_ip_invalid(self):
        """Test is_external_ip returns False for invalid IPs."""
        tracker = ConnectionTracker()
        assert tracker._is_external_ip("not-an-ip") is False
        assert tracker._is_external_ip("") is False

    @patch("psutil.net_connections")
    def test_get_external_connections_empty(self, mock_net_connections):
        """Test get_external_connections with no connections."""
        tracker = ConnectionTracker()
        mock_net_connections.return_value = []

        result = tracker.get_external_connections()

        assert result == {}

    @patch("psutil.net_connections")
    def test_get_external_connections_filters_private(self, mock_net_connections):
        """Test that private IPs are filtered out."""
        tracker = ConnectionTracker()

        # Create mock connection with private IP
        mock_conn = MagicMock()
        mock_conn.status = "ESTABLISHED"
        mock_conn.raddr.ip = "192.168.1.1"
        mock_conn.raddr.port = 443
        mock_conn.laddr.port = 54321
        mock_conn.pid = 1234

        mock_net_connections.return_value = [mock_conn]

        result = tracker.get_external_connections()

        assert result == {}

    @patch("psutil.Process")
    @patch("psutil.net_connections")
    def test_get_external_connections_includes_external(self, mock_net_connections, mock_process):
        """Test that external IPs are included."""
        tracker = ConnectionTracker()

        # Create mock connection with external IP
        mock_conn = MagicMock()
        mock_conn.status = "ESTABLISHED"
        mock_conn.raddr.ip = "8.8.8.8"
        mock_conn.raddr.port = 443
        mock_conn.laddr.port = 54321
        mock_conn.pid = 1234

        mock_net_connections.return_value = [mock_conn]

        # Mock process lookup
        mock_proc = MagicMock()
        mock_proc.name.return_value = "Safari"
        mock_process.return_value = mock_proc

        result = tracker.get_external_connections()

        assert "Safari" in result
        assert len(result["Safari"]) == 1
        assert result["Safari"][0].remote_ip == "8.8.8.8"

    @patch("psutil.net_connections")
    def test_get_external_connections_filters_non_established(self, mock_net_connections):
        """Test that non-ESTABLISHED connections are filtered."""
        tracker = ConnectionTracker()

        mock_conn = MagicMock()
        mock_conn.status = "TIME_WAIT"  # Not ESTABLISHED
        mock_conn.raddr.ip = "8.8.8.8"

        mock_net_connections.return_value = [mock_conn]

        result = tracker.get_external_connections()

        assert result == {}

    @patch("psutil.net_connections")
    def test_get_external_connections_handles_no_raddr(self, mock_net_connections):
        """Test handling of connections without remote address."""
        tracker = ConnectionTracker()

        mock_conn = MagicMock()
        mock_conn.status = "ESTABLISHED"
        mock_conn.raddr = None  # No remote address

        mock_net_connections.return_value = [mock_conn]

        result = tracker.get_external_connections()

        assert result == {}

    @patch("psutil.Process")
    @patch("psutil.net_connections")
    def test_get_external_connections_with_geolocation(self, mock_net_connections, mock_process):
        """Test that geolocation is looked up when service provided."""
        mock_geo = MagicMock()
        mock_geo.lookup_country.return_value = "US"
        tracker = ConnectionTracker(geolocation_service=mock_geo)

        mock_conn = MagicMock()
        mock_conn.status = "ESTABLISHED"
        mock_conn.raddr.ip = "8.8.8.8"
        mock_conn.raddr.port = 443
        mock_conn.laddr.port = 54321
        mock_conn.pid = 1234

        mock_net_connections.return_value = [mock_conn]

        mock_proc = MagicMock()
        mock_proc.name.return_value = "Safari"
        mock_process.return_value = mock_proc

        result = tracker.get_external_connections()

        mock_geo.lookup_country.assert_called_once_with("8.8.8.8")
        assert result["Safari"][0].country_code == "US"

    @patch("psutil.net_connections")
    def test_get_external_connections_handles_access_denied(self, mock_net_connections):
        """Test handling of psutil.AccessDenied."""
        import psutil

        tracker = ConnectionTracker()
        mock_net_connections.side_effect = psutil.AccessDenied(pid=1234)

        result = tracker.get_external_connections()

        assert result == {}

    @patch("psutil.Process")
    @patch("psutil.net_connections")
    def test_get_countries_per_app(self, mock_net_connections, mock_process):
        """Test get_countries_per_app returns unique countries."""
        mock_geo = MagicMock()
        mock_geo.lookup_country.side_effect = ["US", "DE", "US"]  # Duplicate US
        tracker = ConnectionTracker(geolocation_service=mock_geo)

        # Create multiple connections
        conns = []
        for i, ip in enumerate(["8.8.8.8", "1.1.1.1", "142.250.80.46"]):
            mock_conn = MagicMock()
            mock_conn.status = "ESTABLISHED"
            mock_conn.raddr.ip = ip
            mock_conn.raddr.port = 443
            mock_conn.laddr.port = 54320 + i
            mock_conn.pid = 1234
            conns.append(mock_conn)

        mock_net_connections.return_value = conns

        mock_proc = MagicMock()
        mock_proc.name.return_value = "Safari"
        mock_process.return_value = mock_proc

        result = tracker.get_countries_per_app()

        # Should have unique, sorted countries
        assert "Safari" in result
        assert result["Safari"] == ["DE", "US"]  # Sorted, unique
