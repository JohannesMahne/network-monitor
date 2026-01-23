"""Mock implementations for testing Network Monitor.

Provides mock versions of all major components that can be used
in unit tests without requiring actual system access.

Usage:
    from tests.mocks import MockNetworkStats, MockConnectionDetector

    stats = MockNetworkStats()
    stats.set_speeds(upload=1000, download=5000)
"""

import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# === Mock Data Classes ===


@dataclass
class MockSpeedStats:
    """Mock speed statistics."""

    upload_speed: float = 0
    download_speed: float = 0
    total_sent: int = 0
    total_recv: int = 0


@dataclass
class MockConnectionInfo:
    """Mock connection information."""

    connection_type: str = "WiFi"
    name: str = "TestNetwork"
    interface: str = "en0"
    is_connected: bool = True
    ip_address: str = "192.168.1.100"


@dataclass
class MockNetworkDevice:
    """Mock network device."""

    ip_address: str = "192.168.1.1"
    mac_address: str = "00:11:22:33:44:55"
    hostname: Optional[str] = None
    vendor: Optional[str] = "Apple"
    device_type: str = "unknown"
    custom_name: Optional[str] = None
    is_online: bool = True

    @property
    def display_name(self) -> str:
        return self.custom_name or self.hostname or self.ip_address

    @property
    def type_icon(self) -> str:
        return "❓"


@dataclass
class MockNetworkIssue:
    """Mock network issue."""

    timestamp: datetime = field(default_factory=datetime.now)
    issue_type: str = "test"
    description: str = "Test issue"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.issue_type,
            "description": self.description,
        }


# === Mock Components ===


class MockNetworkStats:
    """Mock NetworkStats for testing."""

    def __init__(self):
        self._initialized = False
        self._upload_speed = 0.0
        self._download_speed = 0.0
        self._total_sent = 0
        self._total_recv = 0
        self._session_sent = 0
        self._session_recv = 0
        self._peak_upload = 0.0
        self._peak_download = 0.0

    def initialize(self) -> None:
        self._initialized = True

    def set_speeds(self, upload: float = 0, download: float = 0) -> None:
        """Set mock upload/download speeds."""
        self._upload_speed = upload
        self._download_speed = download
        self._peak_upload = max(self._peak_upload, upload)
        self._peak_download = max(self._peak_download, download)

    def add_traffic(self, sent: int = 0, recv: int = 0) -> None:
        """Add mock traffic."""
        self._total_sent += sent
        self._total_recv += recv
        self._session_sent += sent
        self._session_recv += recv

    def get_current_stats(self) -> MockSpeedStats:
        return MockSpeedStats(
            upload_speed=self._upload_speed,
            download_speed=self._download_speed,
            total_sent=self._total_sent,
            total_recv=self._total_recv,
        )

    def get_session_totals(self) -> Tuple[int, int]:
        return self._session_sent, self._session_recv

    def get_peak_speeds(self) -> Tuple[float, float]:
        return self._peak_upload, self._peak_download

    def get_average_speeds(self) -> Tuple[float, float]:
        return self._upload_speed * 0.8, self._download_speed * 0.8

    def reset_session(self) -> None:
        self._session_sent = 0
        self._session_recv = 0
        self._peak_upload = 0
        self._peak_download = 0


class MockConnectionDetector:
    """Mock ConnectionDetector for testing."""

    def __init__(self):
        self._connection = MockConnectionInfo()
        self._connection_key = "WiFi:TestNetwork"

    def set_connection(
        self,
        conn_type: str = "WiFi",
        name: str = "TestNetwork",
        is_connected: bool = True,
        ip: str = "192.168.1.100",
    ) -> None:
        """Set mock connection state."""
        self._connection = MockConnectionInfo(
            connection_type=conn_type,
            name=name,
            is_connected=is_connected,
            ip_address=ip,
        )
        self._connection_key = f"{conn_type}:{name}"

    def get_current_connection(self) -> MockConnectionInfo:
        return self._connection

    def get_connection_key(self) -> str:
        return self._connection_key

    def has_connection_changed(self) -> bool:
        return False


class MockIssueDetector:
    """Mock IssueDetector for testing."""

    def __init__(self):
        self._issues: List[MockNetworkIssue] = []
        self._latency = 25.0

    def set_latency(self, latency: float) -> None:
        """Set mock latency value."""
        self._latency = latency

    def add_issue(self, description: str, issue_type: str = "test") -> None:
        """Add a mock issue."""
        self._issues.append(
            MockNetworkIssue(
                description=description,
                issue_type=issue_type,
            )
        )

    def check_connectivity(self, is_connected: bool) -> None:
        pass

    def check_latency(self, force: bool = False) -> None:
        pass

    def check_speed_drop(self, current: float, average: float) -> None:
        pass

    def log_connection_change(self, old: str, new: str) -> None:
        self._issues.append(
            MockNetworkIssue(
                description=f"Connection changed: {old} → {new}",
                issue_type="connection_change",
            )
        )

    def get_current_latency(self) -> Optional[float]:
        return self._latency

    def get_recent_issues(self, count: int = 10) -> List[MockNetworkIssue]:
        return self._issues[-count:]

    def clear_issues(self) -> None:
        self._issues.clear()


class MockNetworkScanner:
    """Mock NetworkScanner for testing."""

    def __init__(self):
        self._devices: List[MockNetworkDevice] = []
        self._names: Dict[str, str] = {}

    def add_device(
        self, ip: str, mac: str, vendor: str = None, is_online: bool = True
    ) -> MockNetworkDevice:
        """Add a mock device."""
        device = MockNetworkDevice(
            ip_address=ip,
            mac_address=mac,
            vendor=vendor,
            is_online=is_online,
        )
        self._devices.append(device)
        return device

    def scan(self, force: bool = False, quick: bool = False) -> List[MockNetworkDevice]:
        return self._devices

    def resolve_missing_hostnames(self) -> None:
        pass

    def get_all_devices(self) -> List[MockNetworkDevice]:
        return self._devices

    def get_online_devices(self) -> List[MockNetworkDevice]:
        return [d for d in self._devices if d.is_online]

    def get_device_count(self) -> Tuple[int, int]:
        online = sum(1 for d in self._devices if d.is_online)
        return online, len(self._devices)

    def set_device_name(self, mac: str, name: str) -> None:
        self._names[mac] = name
        for device in self._devices:
            if device.mac_address == mac:
                device.custom_name = name


class MockTrafficMonitor:
    """Mock TrafficMonitor for testing."""

    def __init__(self):
        self._processes: List[Tuple[str, int, int, int]] = []

    def add_process(
        self, name: str, bytes_in: int = 0, bytes_out: int = 0, connections: int = 1
    ) -> None:
        """Add a mock process."""
        self._processes.append((name, bytes_in, bytes_out, connections))

    def get_top_processes(self, limit: int = 10) -> List[Tuple[str, int, int, int]]:
        return self._processes[:limit]

    def get_traffic_summary(self) -> List[Tuple[str, int, int, int]]:
        return self._processes


class MockJsonStore:
    """Mock JsonStore for testing."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(tempfile.gettempdir()) / "mock_netmon"
        self._data: Dict[str, Dict[str, Any]] = {}
        self._today_key = datetime.now().strftime("%Y-%m-%d")

    def update_stats(
        self, conn_key: str, sent: int, recv: int, peak_up: float = 0, peak_down: float = 0
    ) -> None:
        if self._today_key not in self._data:
            self._data[self._today_key] = {}
        if conn_key not in self._data[self._today_key]:
            self._data[self._today_key][conn_key] = {
                "bytes_sent": 0,
                "bytes_recv": 0,
                "peak_upload": 0,
                "peak_download": 0,
                "issues": [],
            }
        # Add to existing values (accumulate deltas, don't replace)
        stats = self._data[self._today_key][conn_key]
        stats["bytes_sent"] += sent
        stats["bytes_recv"] += recv
        stats["peak_upload"] = max(stats["peak_upload"], peak_up)
        stats["peak_download"] = max(stats["peak_download"], peak_down)

    def get_today_totals(self) -> Tuple[int, int]:
        if self._today_key not in self._data:
            return 0, 0
        total_sent = sum(c.get("bytes_sent", 0) for c in self._data[self._today_key].values())
        total_recv = sum(c.get("bytes_recv", 0) for c in self._data[self._today_key].values())
        return total_sent, total_recv

    def get_weekly_totals(self) -> Dict:
        return {"sent": 1000000, "recv": 5000000, "by_connection": {}}

    def get_monthly_totals(self) -> Dict:
        return {"sent": 10000000, "recv": 50000000, "by_connection": {}}

    def get_daily_totals(self, days: int = 7) -> List[Dict]:
        return [{"date": self._today_key, "sent": 0, "recv": 0, "connections": []}]

    def get_connection_history(self, conn_key: str, days: int = 30) -> List[Dict]:
        return []

    def get_today_issues(self) -> List[dict]:
        return []

    def add_issue(self, conn_key: str, issue: dict) -> None:
        pass

    def reset_today(self) -> None:
        if self._today_key in self._data:
            del self._data[self._today_key]

    def flush(self) -> None:
        pass


class MockSettingsManager:
    """Mock SettingsManager for testing."""

    def __init__(self):
        self._title_display = "latency"
        self._budgets: Dict[str, Any] = {}

    def get_title_display(self) -> str:
        return self._title_display

    def set_title_display(self, mode: str) -> None:
        self._title_display = mode

    def get_title_display_options(self) -> List[Tuple[str, str]]:
        return [
            ("latency", "Latency"),
            ("session", "Session Data"),
            ("speed", "Current Speed"),
            ("devices", "Device Count"),
        ]

    def get_latency_color(self, latency: float) -> str:
        if latency < 50:
            return "green"
        elif latency < 100:
            return "yellow"
        return "red"

    def get_budget(self, conn_key: str) -> Optional[Any]:
        return self._budgets.get(conn_key)

    def set_budget(self, conn_key: str, budget: Any) -> None:
        self._budgets[conn_key] = budget

    def remove_budget(self, conn_key: str) -> None:
        self._budgets.pop(conn_key, None)

    def get_all_budgets(self) -> Dict[str, Any]:
        return self._budgets

    def check_budget_status(self, conn_key: str, current: int, period: int) -> Dict:
        return {
            "has_budget": False,
            "exceeded": False,
            "warning": False,
            "percent_used": 0,
        }


class MockLaunchAgentManager:
    """Mock LaunchAgentManager for testing."""

    def __init__(self):
        self._enabled = False

    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> Tuple[bool, str]:
        self._enabled = True
        return True, "Launch at Login enabled"

    def disable(self) -> Tuple[bool, str]:
        self._enabled = False
        return True, "Launch at Login disabled"

    def toggle(self) -> Tuple[bool, str]:
        if self._enabled:
            return self.disable()
        return self.enable()

    def get_status(self) -> str:
        if self._enabled:
            return "✓ Launch at Login: On"
        return "○ Launch at Login: Off"
