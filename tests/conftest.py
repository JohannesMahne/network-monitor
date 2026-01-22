"""Pytest configuration and shared fixtures.

This module provides:
- Common test fixtures for data directories, sample data, and mocks
- Pytest markers for test categorization (unit, integration, slow)
- Deprecation warning filters
"""
import json
import sqlite3
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

# Filter matplotlib/pyparsing deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="matplotlib")
warnings.filterwarnings("ignore", message=".*deprecated.*", module="pyparsing")


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for test categorization."""
    config.addinivalue_line("markers", "unit: mark test as a unit test (fast, isolated)")
    config.addinivalue_line("markers", "integration: mark test as an integration test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "macos_only: mark test as requiring macOS")


# =============================================================================
# Directory and Path Fixtures
# =============================================================================


@pytest.fixture
def temp_data_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db_path(temp_data_dir: Path) -> Path:
    """Create a path for a temporary SQLite database."""
    return temp_data_dir / "test_network_monitor.db"


@pytest.fixture
def temp_json_path(temp_data_dir: Path) -> Path:
    """Create a path for a temporary JSON file."""
    return temp_data_dir / "test_stats.json"


@pytest.fixture
def temp_settings_path(temp_data_dir: Path) -> Path:
    """Create a path for temporary settings."""
    return temp_data_dir / "test_settings.json"


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_stats_data() -> dict[str, Any]:
    """Sample statistics data for testing."""
    return {
        "2026-01-20": {
            "WiFi:TestNetwork": {
                "bytes_sent": 1000000,
                "bytes_recv": 5000000,
                "peak_upload": 100000,
                "peak_download": 500000,
                "issues": []
            }
        }
    }


@pytest.fixture
def sample_device_data() -> dict[str, Any]:
    """Sample network device data for testing."""
    return {
        "mac": "AA:BB:CC:DD:EE:FF",
        "ip": "192.168.1.100",
        "hostname": "test-device.local",
        "vendor": "Apple, Inc.",
        "device_type": "laptop",
        "first_seen": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "is_online": True,
        "custom_name": None,
    }


@pytest.fixture
def sample_connection_info() -> dict[str, Any]:
    """Sample connection info for testing."""
    return {
        "type": "WiFi",
        "ssid": "TestNetwork",
        "ip_address": "192.168.1.50",
        "is_connected": True,
        "is_vpn": False,
        "interface": "en0",
    }


@pytest.fixture
def sample_issue_data() -> dict[str, Any]:
    """Sample network issue data for testing."""
    return {
        "type": "high_latency",
        "message": "Latency spike detected: 150ms",
        "timestamp": datetime.now().isoformat(),
        "connection_key": "WiFi:TestNetwork",
        "severity": "warning",
    }


@pytest.fixture
def sample_traffic_data() -> list[dict[str, Any]]:
    """Sample traffic data for testing."""
    return [
        {
            "pid": 1234,
            "name": "chrome",
            "display_name": "Chrome",
            "bytes_in": 5000000,
            "bytes_out": 500000,
            "connections": 25,
        },
        {
            "pid": 5678,
            "name": "slack",
            "display_name": "Slack",
            "bytes_in": 1000000,
            "bytes_out": 200000,
            "connections": 5,
        },
    ]


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_psutil() -> Generator[MagicMock, None, None]:
    """Mock psutil module for network stats testing."""
    with patch("psutil.net_io_counters") as mock_io:
        mock_io.return_value = MagicMock(
            bytes_sent=1000000,
            bytes_recv=5000000,
            packets_sent=1000,
            packets_recv=5000,
            errin=0,
            errout=0,
            dropin=0,
            dropout=0,
        )
        yield mock_io


@pytest.fixture
def mock_subprocess() -> Generator[MagicMock, None, None]:
    """Mock subprocess for command execution testing."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        yield mock_run


@pytest.fixture
def mock_rumps_app() -> MagicMock:
    """Create a mock rumps.App for UI testing."""
    mock_app = MagicMock()
    mock_app.title = "Test"
    mock_app.icon = None
    mock_app.menu = MagicMock()
    mock_app.menu.clear = MagicMock()
    mock_app.menu.update = MagicMock()
    return mock_app


@pytest.fixture
def mock_rumps_menu_item() -> MagicMock:
    """Create a mock rumps.MenuItem for menu testing."""
    mock_item = MagicMock()
    mock_item.title = "Test Item"
    mock_item.state = 0
    mock_item.callback = None
    return mock_item


@pytest.fixture
def mock_network_interface() -> Generator[MagicMock, None, None]:
    """Mock network interface detection."""
    with patch("psutil.net_if_addrs") as mock_addrs:
        mock_addrs.return_value = {
            "en0": [
                MagicMock(family=2, address="192.168.1.50", netmask="255.255.255.0"),
            ],
            "lo0": [
                MagicMock(family=2, address="127.0.0.1", netmask="255.0.0.0"),
            ],
        }
        yield mock_addrs


# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
def sqlite_connection(temp_db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Create a temporary SQLite connection for testing."""
    conn = sqlite3.connect(str(temp_db_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def populated_json_store(temp_json_path: Path, sample_stats_data: dict) -> Path:
    """Create a JSON file with sample data."""
    with open(temp_json_path, "w") as f:
        json.dump(sample_stats_data, f)
    return temp_json_path


# =============================================================================
# Event Bus Fixtures
# =============================================================================


@pytest.fixture
def mock_event_bus() -> MagicMock:
    """Create a mock event bus for testing event-driven components."""
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock()
    mock_bus.subscribe = MagicMock()
    mock_bus.unsubscribe = MagicMock()
    return mock_bus


# =============================================================================
# Integration Test Fixtures
# =============================================================================


@pytest.fixture
def integration_data_dir(tmp_path: Path) -> Path:
    """Create a complete data directory structure for integration tests."""
    data_dir = tmp_path / ".network-monitor"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def integration_store(integration_data_dir: Path):
    """Create a real SQLite store for integration testing."""
    from storage.sqlite_store import SQLiteStore
    
    db_path = integration_data_dir / "network_monitor.db"
    store = SQLiteStore(str(db_path))
    yield store
    store.close()
