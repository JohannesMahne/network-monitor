# Network Monitor v2.0 - Proposed Changes

## Executive Summary

The Network Monitor is a well-designed macOS menu bar application with solid foundations. This document outlines improvements for version 2.0, focusing on architecture, performance, reliability, and new features.

**Current Strengths:**
- Clean modular structure with separate concerns (monitor, storage, service)
- Effective use of dataclasses for type-safe data structures
- Thread-safe design with appropriate locking
- Multiple fallback strategies for system data collection
- Comprehensive device identification with OUI database
- User-friendly macOS integration

---

## 1. Architecture Improvements

### 1.1 Split the Main Application File

**Problem:** `network_monitor.py` is 1292 lines, mixing UI logic with business logic.

**Solution:** Refactor into a proper MVC/presenter pattern:

```
network_monitor/
├── app/
│   ├── __init__.py
│   ├── main.py              # Entry point (50 lines)
│   ├── controller.py        # Business logic orchestration
│   └── views/
│       ├── __init__.py
│       ├── menu_bar.py      # Menu bar UI components
│       ├── menu_items.py    # Individual menu item factories
│       ├── dialogs.py       # Alert/input dialogs
│       └── icons.py         # Icon generation (gauge, sparklines)
├── monitor/                  # (existing - data collection)
├── storage/                  # (existing - persistence)
├── service/                  # (existing - system services)
└── config/
    ├── __init__.py
    └── constants.py          # All magic numbers/strings
```

### 1.2 Introduce Dependency Injection

**Problem:** Components are tightly coupled and hard to test.

**Solution:** Use a simple DI container or constructor injection:

```python
# Before (tightly coupled)
class NetworkMonitorApp(rumps.App):
    def __init__(self):
        self.network_stats = NetworkStats()
        self.connection_detector = ConnectionDetector()
        # ... many more

# After (injectable dependencies)
@dataclass
class AppDependencies:
    network_stats: NetworkStats
    connection_detector: ConnectionDetector
    issue_detector: IssueDetector
    network_scanner: NetworkScanner
    traffic_monitor: TrafficMonitor
    store: JsonStore
    settings: SettingsManager

class NetworkMonitorApp(rumps.App):
    def __init__(self, deps: AppDependencies):
        self.deps = deps
```

### 1.3 Event-Driven Updates

**Problem:** Polling-based updates can miss events and waste resources.

**Solution:** Implement an event bus for internal communication:

```python
from enum import Enum, auto
from typing import Callable, Dict, List

class EventType(Enum):
    CONNECTION_CHANGED = auto()
    SPEED_UPDATE = auto()
    DEVICE_DISCOVERED = auto()
    DEVICE_OFFLINE = auto()
    BUDGET_WARNING = auto()
    BUDGET_EXCEEDED = auto()
    LATENCY_SPIKE = auto()

class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
    
    def subscribe(self, event_type: EventType, callback: Callable):
        self._subscribers.setdefault(event_type, []).append(callback)
    
    def publish(self, event_type: EventType, data: dict = None):
        for callback in self._subscribers.get(event_type, []):
            callback(data or {})
```

---

## 2. Error Handling & Logging

### 2.1 Structured Logging System

**Problem:** Current code uses `print()` for errors, which disappear in production.

**Solution:** Implement proper logging with rotation:

```python
# logging_config.py
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(data_dir: Path, debug: bool = False):
    log_file = data_dir / "network_monitor.log"
    
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5_000_000,  # 5MB
        backupCount=3
    )
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    root = logging.getLogger('netmon')
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(handler)
    
    return root
```

### 2.2 Custom Exception Hierarchy

**Problem:** Bare `except Exception` catches hide bugs and make debugging difficult.

**Solution:** Define specific exceptions:

```python
# exceptions.py
class NetworkMonitorError(Exception):
    """Base exception for Network Monitor."""
    pass

class ConnectionError(NetworkMonitorError):
    """Network connection related errors."""
    pass

class StorageError(NetworkMonitorError):
    """Data persistence errors."""
    pass

class ScannerError(NetworkMonitorError):
    """Device scanning errors."""
    pass

class ConfigurationError(NetworkMonitorError):
    """Settings/configuration errors."""
    pass
```

### 2.3 Graceful Degradation

**Problem:** External command failures can break features silently.

**Solution:** Implement result types with fallback chains:

```python
from dataclasses import dataclass
from typing import TypeVar, Generic, Optional

T = TypeVar('T')

@dataclass
class Result(Generic[T]):
    value: Optional[T]
    error: Optional[str]
    source: str  # Which method succeeded
    
    @property
    def ok(self) -> bool:
        return self.value is not None

def get_wifi_ssid() -> Result[str]:
    """Try multiple methods with clear fallback chain."""
    methods = [
        ("CoreWLAN", _get_ssid_corewlan),
        ("networksetup", _get_ssid_networksetup),
        ("airport", _get_ssid_airport),
        ("ipconfig", _get_ssid_ipconfig),
    ]
    
    errors = []
    for name, method in methods:
        try:
            ssid = method()
            if ssid:
                return Result(value=ssid, error=None, source=name)
        except Exception as e:
            errors.append(f"{name}: {e}")
    
    return Result(value=None, error="; ".join(errors), source="none")
```

---

## 3. Performance Optimizations

### 3.1 Sparkline Caching & Optimization

**Problem:** Matplotlib sparklines are regenerated every 2 seconds, which is CPU-intensive.

**Solution:** Replace matplotlib with lightweight custom rendering:

```python
# Lightweight sparkline using PIL only (no matplotlib)
def create_sparkline_pil(values: list, color: tuple, 
                         width: int = 100, height: int = 16) -> Image:
    """Create sparkline using PIL directly - 10x faster than matplotlib."""
    if len(values) < 2:
        values = [0, 0]
    
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Normalize values
    min_val, max_val = min(values), max(values)
    if max_val == min_val:
        max_val = min_val + 1
    
    # Calculate points
    points = []
    for i, v in enumerate(values):
        x = int(i * (width - 1) / (len(values) - 1))
        y = int(height - 1 - (v - min_val) / (max_val - min_val) * (height - 2))
        points.append((x, y))
    
    # Draw line
    draw.line(points, fill=color, width=1)
    
    # Draw end dot
    if points:
        x, y = points[-1]
        draw.ellipse([x-2, y-2, x+2, y+2], fill=color)
    
    return img
```

**Alternative:** Consider removing sparklines entirely or making them optional, as they add complexity for modest UX benefit.

### 3.2 Reduce Subprocess Calls

**Problem:** Frequent subprocess calls (`arp`, `ping`, `lsof`) are expensive.

**Solution:** Batch and cache results:

```python
class SubprocessCache:
    def __init__(self, ttl_seconds: float = 5.0):
        self._cache: Dict[str, tuple] = {}  # cmd -> (result, timestamp)
        self._ttl = ttl_seconds
    
    def run(self, cmd: list, **kwargs) -> subprocess.CompletedProcess:
        key = tuple(cmd)
        now = time.time()
        
        if key in self._cache:
            result, ts = self._cache[key]
            if now - ts < self._ttl:
                return result
        
        result = subprocess.run(cmd, **kwargs)
        self._cache[key] = (result, now)
        return result
```

### 3.3 Lazy Device Resolution

**Problem:** Hostname/mDNS resolution blocks scanning.

**Solution:** Background resolution with priority queue:

```python
from queue import PriorityQueue
from dataclasses import dataclass, field

@dataclass(order=True)
class ResolutionTask:
    priority: int
    mac_address: str = field(compare=False)
    task_type: str = field(compare=False)  # 'hostname', 'mdns', 'vendor'

class AsyncResolver:
    def __init__(self, max_workers: int = 3):
        self._queue = PriorityQueue()
        self._workers = []
        self._results: Dict[str, dict] = {}
        self._start_workers(max_workers)
    
    def enqueue(self, mac: str, task_type: str, priority: int = 5):
        self._queue.put(ResolutionTask(priority, mac, task_type))
    
    def get_result(self, mac: str) -> Optional[dict]:
        return self._results.get(mac)
```

### 3.4 Smarter Update Intervals

**Problem:** Fixed 2-second interval regardless of activity.

**Solution:** Adaptive intervals based on network activity:

```python
class AdaptiveTimer:
    MIN_INTERVAL = 1.0   # During high activity
    MAX_INTERVAL = 10.0  # During idle
    
    def __init__(self):
        self._last_traffic = 0
        self._interval = 2.0
    
    def update(self, current_traffic: int) -> float:
        delta = abs(current_traffic - self._last_traffic)
        self._last_traffic = current_traffic
        
        # High activity = faster updates
        if delta > 1_000_000:  # >1MB/interval
            self._interval = max(self.MIN_INTERVAL, self._interval * 0.8)
        else:
            self._interval = min(self.MAX_INTERVAL, self._interval * 1.1)
        
        return self._interval
```

---

## 4. Storage & Data Management

### 4.1 SQLite Migration

**Problem:** JSON storage doesn't scale well for historical queries.

**Solution:** Migrate to SQLite with JSON export:

```python
# storage/database.py
import sqlite3
from contextlib import contextmanager

class NetworkDatabase:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS traffic_stats (
        id INTEGER PRIMARY KEY,
        date TEXT NOT NULL,
        connection_key TEXT NOT NULL,
        bytes_sent INTEGER DEFAULT 0,
        bytes_recv INTEGER DEFAULT 0,
        peak_upload REAL DEFAULT 0,
        peak_download REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, connection_key)
    );
    
    CREATE TABLE IF NOT EXISTS devices (
        mac_address TEXT PRIMARY KEY,
        custom_name TEXT,
        vendor TEXT,
        device_type TEXT,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        last_ip TEXT
    );
    
    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY,
        timestamp TIMESTAMP NOT NULL,
        connection_key TEXT,
        issue_type TEXT NOT NULL,
        description TEXT,
        details TEXT  -- JSON
    );
    
    CREATE INDEX idx_stats_date ON traffic_stats(date);
    CREATE INDEX idx_issues_timestamp ON issues(timestamp);
    """
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
```

### 4.2 Data Export/Import

**Problem:** No way to backup or analyze data externally.

**Solution:** Add export functionality:

```python
class DataExporter:
    def export_csv(self, start_date: date, end_date: date, 
                   output_path: Path) -> None:
        """Export traffic data to CSV."""
        pass
    
    def export_json(self, output_path: Path) -> None:
        """Full JSON export for backup."""
        pass
    
    def import_json(self, input_path: Path) -> None:
        """Import from JSON backup."""
        pass
```

### 4.3 Automatic Data Cleanup

**Problem:** `cleanup_old_data()` exists but isn't called automatically.

**Solution:** Schedule periodic cleanup:

```python
class DataManager:
    RETENTION_DAYS = 90  # Configurable
    
    def __init__(self, store: NetworkDatabase):
        self._store = store
        self._schedule_cleanup()
    
    def _schedule_cleanup(self):
        """Run cleanup weekly."""
        # Check last cleanup date, run if >7 days
        pass
```

---

## 5. Testing Improvements

### 5.1 Comprehensive Mock System

**Problem:** Tests require real system access, making them flaky.

**Solution:** Create mock providers:

```python
# tests/mocks.py
class MockNetworkInterface:
    """Mock for psutil network interfaces."""
    
    def __init__(self):
        self.bytes_sent = 1000000
        self.bytes_recv = 5000000
    
    def increment(self, sent: int = 1000, recv: int = 5000):
        self.bytes_sent += sent
        self.bytes_recv += recv

class MockSubprocess:
    """Mock subprocess.run for testing."""
    
    def __init__(self):
        self.responses = {}
    
    def set_response(self, cmd: tuple, stdout: str, returncode: int = 0):
        self.responses[cmd] = (stdout, returncode)
    
    def run(self, cmd, **kwargs):
        key = tuple(cmd)
        stdout, code = self.responses.get(key, ("", 1))
        return subprocess.CompletedProcess(cmd, code, stdout=stdout)
```

### 5.2 Integration Tests

**Problem:** No tests for component interaction.

**Solution:** Add integration test suite:

```python
# tests/test_integration.py
class TestFullUpdateCycle:
    """Test complete update cycle with mocked system."""
    
    def test_connection_change_updates_all_components(self):
        """Verify connection change propagates correctly."""
        pass
    
    def test_device_discovery_persists_to_storage(self):
        """Verify discovered devices are saved."""
        pass
```

### 5.3 Property-Based Testing

**Solution:** Use Hypothesis for edge cases:

```python
from hypothesis import given, strategies as st

@given(st.integers(min_value=0, max_value=10**15))
def test_format_bytes_never_crashes(bytes_value):
    """format_bytes handles any reasonable input."""
    result = format_bytes(bytes_value)
    assert isinstance(result, str)
    assert len(result) < 20
```

---

## 6. New Features

### 6.1 Budget Notifications

**Problem:** Budget warnings only show in menu, easily missed.

**Solution:** Add macOS notifications:

```python
def check_and_notify_budget(self, connection_key: str, usage: int):
    status = self.settings.check_budget_status(connection_key, 0, usage)
    
    if status['exceeded'] and not self._notified_exceeded.get(connection_key):
        rumps.notification(
            title="Data Budget Exceeded",
            subtitle=connection_key,
            message=f"You've used {format_bytes(usage)} of your {format_bytes(status['limit_bytes'])} budget.",
            sound=True
        )
        self._notified_exceeded[connection_key] = True
    
    elif status['warning'] and not self._notified_warning.get(connection_key):
        rumps.notification(
            title="Data Budget Warning",
            subtitle=connection_key,
            message=f"{status['percent_used']:.0f}% of budget used.",
            sound=False
        )
        self._notified_warning[connection_key] = True
```

### 6.2 Speed Test Integration

**Solution:** Add on-demand speed test:

```python
class SpeedTest:
    """Simple speed test using public CDN endpoints."""
    
    TEST_URLS = [
        "https://speed.cloudflare.com/__down?bytes=10000000",
        "https://proof.ovh.net/files/10Mb.dat",
    ]
    
    async def run_download_test(self) -> float:
        """Returns download speed in bytes/second."""
        pass
    
    async def run_upload_test(self) -> float:
        """Returns upload speed in bytes/second."""
        pass
```

### 6.3 VPN Detection

**Solution:** Detect and display VPN status:

```python
class VPNDetector:
    VPN_INTERFACES = ['utun', 'ppp', 'ipsec', 'tun', 'tap']
    
    def is_vpn_active(self) -> bool:
        """Check if any VPN interface is active."""
        for iface, stats in psutil.net_if_stats().items():
            if any(iface.startswith(prefix) for prefix in self.VPN_INTERFACES):
                if stats.isup:
                    return True
        return False
    
    def get_vpn_info(self) -> Optional[dict]:
        """Get details about active VPN connection."""
        pass
```

### 6.4 Network Quality Score

**Solution:** Calculate overall network health:

```python
@dataclass
class NetworkQuality:
    score: int  # 0-100
    latency_score: int
    stability_score: int
    speed_score: int
    description: str  # "Excellent", "Good", "Fair", "Poor"
    
    @classmethod
    def calculate(cls, latency_ms: float, packet_loss: float, 
                  speed_ratio: float) -> 'NetworkQuality':
        # Weighted scoring algorithm
        pass
```

### 6.5 Historical Charts View

**Solution:** Add a detailed statistics window:

```python
class StatsWindow:
    """Separate window for detailed statistics."""
    
    def show_traffic_chart(self, days: int = 30):
        """Show traffic over time chart."""
        pass
    
    def show_connection_breakdown(self):
        """Pie chart of traffic by connection."""
        pass
```

---

## 7. Configuration Improvements

### 7.1 Centralized Constants

**Problem:** Magic numbers scattered throughout code.

**Solution:** Create configuration module:

```python
# config/constants.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Intervals:
    UPDATE_SECONDS: float = 2.0
    DEVICE_SCAN_SECONDS: float = 30.0
    LATENCY_CHECK_SECONDS: float = 10.0
    TRAFFIC_UPDATE_SECONDS: float = 5.0
    MDNS_SCAN_SECONDS: float = 120.0

@dataclass(frozen=True)
class Thresholds:
    LATENCY_GOOD_MS: int = 50
    LATENCY_OK_MS: int = 100
    HIGH_LATENCY_MS: int = 200
    SPEED_DROP_RATIO: float = 0.1

@dataclass(frozen=True)
class Storage:
    DATA_DIR_NAME: str = ".network-monitor"
    STATS_FILE: str = "stats.json"
    SETTINGS_FILE: str = "settings.json"
    DEVICES_FILE: str = "device_names.json"
    RETENTION_DAYS: int = 90

# Global config instance
INTERVALS = Intervals()
THRESHOLDS = Thresholds()
STORAGE = Storage()
```

### 7.2 User-Configurable Settings

**Problem:** Many values are hardcoded that users might want to change.

**Solution:** Expand settings with validation:

```python
@dataclass
class UserSettings:
    # Display
    title_display: str = "latency"
    show_sparklines: bool = True
    sparkline_history_size: int = 20
    
    # Intervals (seconds)
    update_interval: float = 2.0
    device_scan_interval: float = 30.0
    latency_check_interval: float = 10.0
    
    # Thresholds
    latency_good_ms: int = 50
    latency_ok_ms: int = 100
    
    # Notifications
    enable_notifications: bool = True
    notify_on_disconnect: bool = True
    notify_on_budget_warning: bool = True
    
    # Data retention
    retention_days: int = 90
    
    def validate(self) -> List[str]:
        """Return list of validation errors."""
        errors = []
        if self.update_interval < 1.0:
            errors.append("Update interval must be at least 1 second")
        if self.latency_good_ms >= self.latency_ok_ms:
            errors.append("Good latency threshold must be less than OK threshold")
        return errors
```

---

## 8. Security Improvements

### 8.1 Safer Subprocess Calls

**Problem:** Subprocess calls could be vulnerable to injection.

**Solution:** Use explicit argument lists (already done) and add validation:

```python
def safe_run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    """Run subprocess with safety checks."""
    # Validate command is in allowed list
    ALLOWED_COMMANDS = {'arp', 'ping', 'networksetup', 'lsof', 'nettop', 'dns-sd'}
    
    if cmd[0] not in ALLOWED_COMMANDS and not cmd[0].startswith('/'):
        raise SecurityError(f"Command not in allowlist: {cmd[0]}")
    
    # Ensure capture_output to prevent terminal injection
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('timeout', 10)
    
    return subprocess.run(cmd, **kwargs)
```

### 8.2 File Permission Handling

**Solution:** Set explicit permissions on data files:

```python
def secure_write(path: Path, content: str, mode: int = 0o600):
    """Write file with restricted permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temp file first
    temp_path = path.with_suffix('.tmp')
    with open(temp_path, 'w') as f:
        f.write(content)
    
    # Set permissions before making visible
    os.chmod(temp_path, mode)
    
    # Atomic rename
    temp_path.replace(path)
```

---

## 9. Code Quality

### 9.1 Complete Type Hints

**Problem:** Incomplete type annotations make IDE support and refactoring harder.

**Solution:** Add comprehensive type hints with strict mypy:

```python
# pyproject.toml additions
[tool.mypy]
python_version = "3.9"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
```

### 9.2 Docstring Standards

**Solution:** Use Google-style docstrings consistently:

```python
def format_bytes(bytes_value: int, speed: bool = False) -> str:
    """Format bytes into human-readable string.
    
    Args:
        bytes_value: The number of bytes to format.
        speed: If True, append "/s" for speed display.
    
    Returns:
        Formatted string like "1.5 MB" or "1.5 MB/s".
    
    Examples:
        >>> format_bytes(1500000)
        '1.4 MB'
        >>> format_bytes(1500000, speed=True)
        '1.4 MB/s'
    """
```

### 9.3 Code Formatting

**Solution:** Add pre-commit hooks:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
```

---

## 10. Dependency Optimization

### 10.1 Remove matplotlib Dependency

**Problem:** matplotlib is ~50MB for just sparklines.

**Solution:** Use PIL-only sparklines (see 3.1) or make matplotlib optional:

```python
# requirements.txt
rumps>=0.4.0
psutil>=5.9.0
pillow>=10.0.0

# requirements-full.txt (optional features)
matplotlib>=3.7.0  # For detailed charts window
```

### 10.2 Dependency Version Ranges

**Problem:** Pinned versions may become outdated.

**Solution:** Use compatible release specifiers:

```python
# pyproject.toml
dependencies = [
    "rumps>=0.4.0,<1.0",
    "psutil>=5.9.0,<7.0",
    "pillow>=10.0.0,<12.0",
]
```

---

## 11. Implementation Roadmap

### Phase 1: Foundation (1-2 weeks) ✅ COMPLETED
- [x] Set up logging system (`config/logging_config.py`)
- [x] Create exception hierarchy (`config/exceptions.py`)
- [x] Add configuration module (`config/constants.py`)
- [x] Implement subprocess caching (`config/subprocess_cache.py`)

### Phase 2: Architecture (2-3 weeks) ✅ COMPLETED
- [x] Split `network_monitor.py` into modules (`app/views/icons.py`, `app/views/menu_builder.py`)
- [x] Implement dependency injection (`app/dependencies.py`)
- [x] Add event bus for internal communication (`app/events.py`)
- [x] Create comprehensive mocks for testing (`tests/mocks.py`)
- [x] Create AppController with business logic (`app/controller.py`)

### Phase 3: Performance (1-2 weeks)
- [ ] Replace matplotlib sparklines with PIL
- [ ] Implement adaptive update intervals
- [ ] Add lazy device resolution
- [ ] Optimize subprocess calls

### Phase 4: Features (2-3 weeks)
- [ ] Add budget notifications
- [ ] Implement VPN detection
- [ ] Add network quality score
- [ ] Create data export functionality

### Phase 5: Storage (1-2 weeks)
- [ ] Migrate to SQLite
- [ ] Add automatic cleanup
- [ ] Implement backup/restore

### Phase 6: Polish (1 week)
- [ ] Complete type hints
- [ ] Add docstrings
- [ ] Set up pre-commit hooks
- [ ] Update documentation

---

## 12. Breaking Changes

The following changes would require migration:

1. **Storage format**: JSON to SQLite migration requires a one-time conversion
2. **Settings structure**: New settings format with more options
3. **Python version**: Consider requiring Python 3.10+ for better type hint support

**Migration Strategy:**
```python
class Migrator:
    def migrate_if_needed(self):
        current_version = self._get_stored_version()
        
        if current_version < 2:
            self._migrate_json_to_sqlite()
        if current_version < 2.1:
            self._migrate_settings_format()
        
        self._set_stored_version(2.1)
```

---

## Summary

These changes would transform Network Monitor from a functional tool into a robust, maintainable, and extensible application. The key improvements are:

1. **Better architecture** - Separated concerns, dependency injection
2. **Improved reliability** - Proper logging, error handling, graceful degradation  
3. **Better performance** - Caching, lighter sparklines, adaptive intervals
4. **Enhanced testing** - Comprehensive mocks, integration tests
5. **New features** - Notifications, VPN detection, quality scores
6. **Better data management** - SQLite, exports, automatic cleanup

Total estimated effort: 8-12 weeks for full implementation.
