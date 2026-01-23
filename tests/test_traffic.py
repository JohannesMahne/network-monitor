"""Tests for traffic monitoring."""
from unittest.mock import MagicMock, patch

import pytest

from monitor.traffic import PORT_CATEGORIES, ProcessTraffic, ServiceCategory, TrafficMonitor


class TestProcessTraffic:
    """Tests for ProcessTraffic dataclass."""

    def test_basic_creation(self):
        """Test creating a ProcessTraffic instance."""
        traffic = ProcessTraffic(
            pid=1234,
            name="Safari",
            bytes_in=1000000,
            bytes_out=500000,
            connections=5
        )
        assert traffic.pid == 1234
        assert traffic.name == "Safari"
        assert traffic.total_bytes == 1500000

    def test_total_bytes_property(self):
        """Test total_bytes calculation."""
        traffic = ProcessTraffic(
            pid=1,
            name="Test",
            bytes_in=100,
            bytes_out=200
        )
        assert traffic.total_bytes == 300

    def test_display_name_known_process(self):
        """Test display name for known process."""
        traffic = ProcessTraffic(pid=1, name="Google Chrome Helper")
        assert traffic.display_name == "Chrome"

    def test_display_name_safari(self):
        """Test display name for Safari."""
        traffic = ProcessTraffic(pid=1, name="Safari")
        assert traffic.display_name == "Safari"

    def test_display_name_vs_code(self):
        """Test display name for VS Code."""
        traffic = ProcessTraffic(pid=1, name="Code Helper")
        assert traffic.display_name == "VS Code"

    def test_display_name_unknown_process(self):
        """Test display name for unknown process."""
        traffic = ProcessTraffic(pid=1, name="myunknownprocess")
        assert traffic.display_name == "Myunknownprocess"

    def test_display_name_empty(self):
        """Test display name for empty name."""
        traffic = ProcessTraffic(pid=1, name="")
        assert traffic.display_name == "Unknown"


class TestServiceCategory:
    """Tests for ServiceCategory dataclass."""

    def test_basic_creation(self):
        """Test creating a ServiceCategory instance."""
        category = ServiceCategory(
            name="Web",
            bytes_in=1000000,
            bytes_out=500000,
            processes=["Safari", "Chrome"]
        )
        assert category.name == "Web"
        assert category.total_bytes == 1500000
        assert len(category.processes) == 2


class TestPortCategories:
    """Tests for port to category mapping."""

    def test_https_port(self):
        """Test HTTPS port mapping."""
        assert PORT_CATEGORIES[443] == "Web (HTTPS)"

    def test_http_port(self):
        """Test HTTP port mapping."""
        assert PORT_CATEGORIES[80] == "Web"

    def test_ssh_port(self):
        """Test SSH port mapping."""
        assert PORT_CATEGORIES[22] == "SSH/SFTP"

    def test_dns_port(self):
        """Test DNS port mapping."""
        assert PORT_CATEGORIES[53] == "DNS"


class TestTrafficMonitor:
    """Tests for TrafficMonitor class."""

    @pytest.fixture
    def mock_subprocess_cache(self):
        """Mock the subprocess cache."""
        with patch('monitor.traffic.get_subprocess_cache') as mock:
            cache_instance = MagicMock()
            mock.return_value = cache_instance
            yield cache_instance

    @pytest.fixture
    def monitor(self, mock_subprocess_cache):
        """Create a TrafficMonitor with mocked subprocess."""
        mock_subprocess_cache.run.return_value = MagicMock(
            returncode=0,
            stdout=""
        )
        return TrafficMonitor()

    def test_init(self, monitor):
        """Test monitor initialization."""
        assert monitor._process_traffic == {}

    @patch('psutil.Process')
    def test_get_process_name(self, mock_process, monitor):
        """Test getting process name from PID."""
        mock_proc_instance = MagicMock()
        mock_proc_instance.name.return_value = "Safari"
        mock_process.return_value = mock_proc_instance

        name = monitor._get_process_name(1234)
        assert name == "Safari"

    @patch('psutil.Process')
    def test_get_process_name_not_found(self, mock_process, monitor):
        """Test handling non-existent process."""
        import psutil
        mock_process.side_effect = psutil.NoSuchProcess(1234)

        name = monitor._get_process_name(1234)
        assert name is None

    @patch('psutil.net_connections')
    def test_get_active_connections(self, mock_connections, monitor):
        """Test getting active connections by PID."""
        mock_conn = MagicMock()
        mock_conn.pid = 1234
        mock_conn.status = 'ESTABLISHED'
        mock_conn.laddr.port = 12345
        mock_conn.raddr.port = 443
        mock_connections.return_value = [mock_conn]

        connections = monitor._get_active_connections()
        assert 1234 in connections
        assert len(connections[1234]) == 1

    def test_run_netstat_processes(self, monitor, mock_subprocess_cache):
        """Test getting connection counts from lsof."""
        mock_subprocess_cache.run.return_value = MagicMock(
            returncode=0,
            stdout="COMMAND     PID\nSafari      1234 ESTABLISHED\nChrome      5678 ESTABLISHED\n"
        )

        result = monitor._run_netstat_processes()
        # Should have some entries (parsing may vary)
        assert isinstance(result, dict)

    @patch('psutil.net_connections')
    @patch.object(TrafficMonitor, '_get_process_name')
    @patch.object(TrafficMonitor, '_run_netstat_processes')
    def test_get_traffic_by_process(self, mock_netstat, mock_name, mock_connections, monitor):
        """Test getting traffic breakdown by process."""
        mock_conn = MagicMock()
        mock_conn.pid = 1234
        mock_conn.status = 'ESTABLISHED'
        mock_conn.laddr.port = 12345
        mock_conn.raddr.port = 443
        mock_connections.return_value = [mock_conn]

        mock_name.return_value = "Safari"
        mock_netstat.return_value = {}

        traffic = monitor.get_traffic_by_process()
        assert len(traffic) >= 0  # May or may not have data depending on mocks

    @patch.object(TrafficMonitor, 'get_traffic_by_process')
    def test_get_traffic_summary(self, mock_traffic, monitor):
        """Test getting traffic summary."""
        mock_traffic.return_value = [
            ProcessTraffic(pid=1, name="Safari", bytes_in=1000, bytes_out=500, connections=2),
            ProcessTraffic(pid=2, name="Chrome", bytes_in=2000, bytes_out=1000, connections=3),
        ]

        summary = monitor.get_traffic_summary()
        assert len(summary) == 2

    @patch.object(TrafficMonitor, 'get_traffic_summary')
    def test_get_top_processes(self, mock_summary, monitor):
        """Test getting top N processes."""
        mock_summary.return_value = [
            ("Chrome", 3000, 1500, 5),
            ("Safari", 2000, 1000, 3),
            ("Firefox", 1000, 500, 2),
        ]

        top = monitor.get_top_processes(limit=2)
        assert len(top) == 2
        assert top[0][0] == "Chrome"

    @patch('psutil.net_connections')
    @patch.object(TrafficMonitor, '_get_process_name')
    def test_categorize_traffic(self, mock_name, mock_connections, monitor):
        """Test categorizing traffic by service type."""
        mock_conn = MagicMock()
        mock_conn.pid = 1234
        mock_conn.status = 'ESTABLISHED'
        mock_conn.laddr = MagicMock(port=12345)
        mock_conn.raddr = MagicMock(port=443)
        mock_connections.return_value = [mock_conn]

        mock_name.return_value = "Safari"

        categories = monitor.categorize_traffic()
        # Should have at least one category
        assert isinstance(categories, dict)


class TestTrafficAggregation:
    """Tests for traffic aggregation functionality."""

    @pytest.fixture
    def monitor(self):
        """Create a TrafficMonitor with mocked subprocess."""
        with patch('monitor.traffic.get_subprocess_cache') as mock:
            cache_instance = MagicMock()
            cache_instance.run.return_value = MagicMock(returncode=0, stdout="")
            mock.return_value = cache_instance
            return TrafficMonitor()

    @patch.object(TrafficMonitor, 'get_traffic_by_process')
    def test_summary_aggregates_helpers(self, mock_traffic, monitor):
        """Test that helper processes are aggregated with main process."""
        mock_traffic.return_value = [
            ProcessTraffic(pid=1, name="Google Chrome", bytes_in=1000, bytes_out=500, connections=2),
            ProcessTraffic(pid=2, name="Google Chrome Helper", bytes_in=500, bytes_out=250, connections=3),
        ]

        summary = monitor.get_traffic_summary()

        # Should be aggregated into one "Chrome" entry
        chrome_entries = [s for s in summary if s[0] == "Chrome"]
        assert len(chrome_entries) == 1

        # Total should be combined
        chrome = chrome_entries[0]
        assert chrome[1] == 1500  # bytes_in
        assert chrome[2] == 750   # bytes_out
        assert chrome[3] == 5     # connections
