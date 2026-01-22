"""Tests for connection detection."""
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

from monitor.connection import ConnectionDetector, ConnectionInfo


class TestConnectionInfo:
    """Tests for ConnectionInfo dataclass."""

    def test_basic_creation(self):
        """Test creating a ConnectionInfo instance."""
        conn = ConnectionInfo(
            connection_type="WiFi",
            name="TestNetwork",
            interface="en0",
            is_connected=True,
            ip_address="192.168.1.100"
        )
        assert conn.connection_type == "WiFi"
        assert conn.name == "TestNetwork"
        assert conn.is_connected is True

    def test_disconnected_state(self):
        """Test disconnected connection info."""
        conn = ConnectionInfo(
            connection_type="None",
            name="Disconnected",
            interface="",
            is_connected=False
        )
        assert conn.is_connected is False
        assert conn.ip_address is None


class TestConnectionDetector:
    """Tests for ConnectionDetector class."""

    @pytest.fixture
    def mock_subprocess_cache(self):
        """Mock the subprocess cache."""
        with patch('monitor.connection.get_subprocess_cache') as mock:
            cache_instance = MagicMock()
            mock.return_value = cache_instance
            yield cache_instance

    @pytest.fixture
    def detector(self, mock_subprocess_cache):
        """Create a ConnectionDetector with mocked subprocess."""
        mock_subprocess_cache.run.return_value = MagicMock(
            returncode=0,
            stdout="Hardware Port: Wi-Fi\nDevice: en0\n"
        )
        return ConnectionDetector()

    def test_init(self, detector):
        """Test detector initialization."""
        assert detector._wifi_interface == "en0"

    def test_get_connection_key_disconnected(self, detector):
        """Test connection key when disconnected."""
        with patch.object(detector, 'get_current_connection') as mock:
            mock.return_value = ConnectionInfo(
                connection_type="None",
                name="Disconnected",
                interface="",
                is_connected=False
            )
            assert detector.get_connection_key() == "Disconnected"

    def test_get_connection_key_connected(self, detector):
        """Test connection key when connected."""
        with patch.object(detector, 'get_current_connection') as mock:
            mock.return_value = ConnectionInfo(
                connection_type="WiFi",
                name="MyNetwork",
                interface="en0",
                is_connected=True
            )
            key = detector.get_connection_key()
            assert key == "WiFi:MyNetwork"

    def test_has_connection_changed_initial(self, detector):
        """Test connection change detection on first call."""
        with patch.object(detector, 'get_current_connection') as mock:
            mock.return_value = ConnectionInfo(
                connection_type="WiFi",
                name="Network1",
                interface="en0",
                is_connected=True
            )
            # First call should return True
            assert detector.has_connection_changed() is True

    def test_has_connection_changed_same(self, detector):
        """Test connection change when connection is the same."""
        conn = ConnectionInfo(
            connection_type="WiFi",
            name="Network1",
            interface="en0",
            is_connected=True
        )
        with patch.object(detector, 'get_current_connection') as mock:
            mock.return_value = conn
            # First call
            detector.has_connection_changed()
            # Second call with same connection
            assert detector.has_connection_changed() is False

    def test_has_connection_changed_different(self, detector):
        """Test connection change detection when connection changes."""
        with patch.object(detector, 'get_current_connection') as mock:
            # First connection
            mock.return_value = ConnectionInfo(
                connection_type="WiFi",
                name="Network1",
                interface="en0",
                is_connected=True
            )
            detector.has_connection_changed()
            
            # Different connection
            mock.return_value = ConnectionInfo(
                connection_type="WiFi",
                name="Network2",
                interface="en0",
                is_connected=True
            )
            assert detector.has_connection_changed() is True

    def test_detect_vpn_no_vpn(self, detector):
        """Test VPN detection when no VPN is active."""
        with patch.object(detector, '_check_vpn_interfaces', return_value=None):
            with patch.object(detector, '_check_vpn_processes', return_value=None):
                with patch.object(detector, '_check_vpn_services', return_value=None):
                    active, name = detector.detect_vpn()
                    assert active is False
                    assert name is None

    def test_detect_vpn_interface(self, detector):
        """Test VPN detection via interface."""
        with patch.object(detector, '_check_vpn_interfaces', return_value="VPN (utun0)"):
            active, name = detector.detect_vpn()
            assert active is True
            assert name == "VPN (utun0)"

    def test_detect_vpn_process(self, detector):
        """Test VPN detection via process."""
        with patch.object(detector, '_check_vpn_interfaces', return_value=None):
            with patch.object(detector, '_check_vpn_processes', return_value="OpenVPN"):
                active, name = detector.detect_vpn()
                assert active is True
                assert name == "OpenVPN"

    @patch('psutil.net_if_addrs')
    @patch('psutil.net_if_stats')
    def test_get_active_interfaces(self, mock_stats, mock_addrs, detector):
        """Test getting active network interfaces."""
        # Mock interface stats
        mock_stats.return_value = {
            'en0': MagicMock(isup=True),
            'lo0': MagicMock(isup=True),
        }
        
        # Mock interface addresses
        mock_addr = MagicMock()
        mock_addr.family.name = 'AF_INET'
        mock_addr.address = '192.168.1.100'
        
        mock_lo_addr = MagicMock()
        mock_lo_addr.family.name = 'AF_INET'
        mock_lo_addr.address = '127.0.0.1'
        
        mock_addrs.return_value = {
            'en0': [mock_addr],
            'lo0': [mock_lo_addr],
        }
        
        active = detector._get_active_interfaces()
        assert 'en0' in active
        assert 'lo0' not in active  # Loopback should be excluded

    @patch('psutil.net_if_addrs')
    def test_get_ip_address(self, mock_addrs, detector):
        """Test getting IP address for an interface."""
        mock_addr = MagicMock()
        mock_addr.family.name = 'AF_INET'
        mock_addr.address = '192.168.1.100'
        
        mock_addrs.return_value = {'en0': [mock_addr]}
        
        ip = detector._get_ip_address('en0')
        assert ip == '192.168.1.100'

    def test_get_ip_address_not_found(self, detector):
        """Test getting IP address for non-existent interface."""
        with patch('psutil.net_if_addrs', return_value={}):
            ip = detector._get_ip_address('nonexistent')
            assert ip is None


class TestVPNDetection:
    """Tests for VPN detection functionality."""

    @pytest.fixture
    def detector(self):
        """Create a ConnectionDetector with mocked subprocess."""
        with patch('monitor.connection.get_subprocess_cache') as mock:
            cache_instance = MagicMock()
            cache_instance.run.return_value = MagicMock(
                returncode=0,
                stdout="Hardware Port: Wi-Fi\nDevice: en0\n"
            )
            mock.return_value = cache_instance
            return ConnectionDetector()

    @patch('psutil.net_if_stats')
    @patch('psutil.net_if_addrs')
    def test_check_vpn_interfaces_utun(self, mock_addrs, mock_stats, detector):
        """Test detecting VPN via utun interface."""
        mock_stats.return_value = {
            'utun0': MagicMock(isup=True),
        }
        
        mock_addr = MagicMock()
        mock_addr.family.name = 'AF_INET'
        mock_addrs.return_value = {
            'utun0': [mock_addr],
        }
        
        result = detector._check_vpn_interfaces()
        assert result is not None
        assert 'utun0' in result

    @patch('psutil.process_iter')
    def test_check_vpn_processes(self, mock_process_iter, detector):
        """Test detecting VPN via running process."""
        mock_proc = MagicMock()
        mock_proc.info = {'name': 'openvpn'}
        mock_process_iter.return_value = [mock_proc]
        
        result = detector._check_vpn_processes()
        assert result == 'openvpn'
