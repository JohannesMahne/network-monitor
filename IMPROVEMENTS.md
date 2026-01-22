# Network Monitor - Implementation Guide

This document contains detailed implementation instructions for improving the network-monitor project. Each section is self-contained and can be implemented independently.

**Last Updated:** After major refactor of scanner.py (MAC vendors now use system OUI database).

**Note:** This document uses British English spelling conventions.

---

## Table of Contents

1. [Critical Bug Fixes](#1-critical-bug-fixes)
2. [Code Quality Improvements](#2-code-quality-improvements)
3. [Performance Improvements](#3-performance-improvements)
4. [Project Infrastructure](#4-project-infrastructure)
5. [Testing](#5-testing)

---

## 1. Critical Bug Fixes

### 1.1 Fix Undefined `indicator` Variable in `_update_title`

**File:** `network_monitor.py`  
**Lines:** 444, 449, 454, 456  
**Severity:** High - causes `NameError` crash when selecting certain display modes

**Problem:**
The `_update_title` method references an undefined variable `indicator` in the "speed" mode's else branch, the "devices" mode, and the default else branch. This will crash the app when those display modes are selected.

**Current Broken Code (lines 437-456):**
```python
elif display_mode == "speed":
    # Speed mode: current up/down speed
    if stats:
        up = format_bytes(stats.upload_speed, speed=True)
        down = format_bytes(stats.download_speed, speed=True)
        self.title = f"↑{up} ↓{down}"
    else:
        self.title = f"{indicator} ↑-- ↓--"  # BUG: indicator undefined

elif display_mode == "devices":
    # Device count mode
    online, total = self.network_scanner.get_device_count()
    self.title = f"{indicator} {online} devices"  # BUG: indicator undefined

else:
    # Default to latency
    if self._current_latency is not None:
        self.title = f"{indicator} {self._current_latency:.0f}ms"  # BUG
    else:
        self.title = f"{indicator} --"  # BUG
```

**Fix:**
Remove the `{indicator}` references since the gauge icon (set via `self.icon`) already provides visual status indication.

**Replace lines 437-456 with:**
```python
elif display_mode == "speed":
    # Speed mode: current up/down speed
    if stats:
        up = format_bytes(stats.upload_speed, speed=True)
        down = format_bytes(stats.download_speed, speed=True)
        self.title = f"↑{up} ↓{down}"
    else:
        self.title = "↑-- ↓--"

elif display_mode == "devices":
    # Device count mode
    online, total = self.network_scanner.get_device_count()
    self.title = f"{online} devices"

else:
    # Default to latency
    if self._current_latency is not None:
        self.title = f"{self._current_latency:.0f}ms"
    else:
        self.title = "--"
```

---

## 2. Code Quality Improvements

### 2.1 Consolidate Duplicate `format_bytes` Functions

**Files to modify:** 
- `monitor/network.py` (lines 124-132)
- `monitor/traffic.py` (lines 461-472)

**File to create:** `monitor/utils.py`

**Problem:**
Two nearly identical `format_bytes` functions exist:
- `format_bytes()` in `monitor/network.py`
- `format_traffic_bytes()` in `monitor/traffic.py`

This violates DRY and makes maintenance harder.

**Implementation Steps:**

#### Step 1: Create shared utility module

Create file: `monitor/utils.py`

```python
"""Shared utility functions for network monitoring."""


def format_bytes(bytes_value: float, speed: bool = False) -> str:
    """Format bytes to human-readable string.
    
    Args:
        bytes_value: The number of bytes to format.
        speed: If True, append '/s' suffix for speed display.
    
    Returns:
        Human-readable string like "1.5 MB" or "1.5 MB/s".
    """
    if bytes_value == 0:
        suffix = "/s" if speed else ""
        return f"0 B{suffix}"
    
    suffix = "/s" if speed else ""
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(bytes_value) < 1024.0:
            return f"{bytes_value:.1f} {unit}{suffix}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB{suffix}"
```

#### Step 2: Update monitor/network.py

Remove the `format_bytes` function (lines 124-132).

Add import at top of file:
```python
from monitor.utils import format_bytes
```

For backwards compatibility, re-export it at the end:
```python
# Re-export for backwards compatibility
from monitor.utils import format_bytes
__all__ = ['NetworkStats', 'SpeedStats', 'format_bytes']
```

#### Step 3: Update monitor/traffic.py

Remove the `format_traffic_bytes` function (lines 461-472).

Add import at top of file:
```python
from monitor.utils import format_bytes
```

Create alias for backwards compatibility at end of file:
```python
# Alias for backwards compatibility
format_traffic_bytes = format_bytes
```

#### Step 4: Update monitor/__init__.py

Add the utils module export:
```python
from .utils import format_bytes
```

---

### 2.2 Add Type Hints to Key Functions

**Files to modify:** Multiple files

**Problem:**
Some functions lack complete type annotations, reducing IDE support and making code harder to understand.

**Functions to annotate:**

#### In `network_monitor.py`:

```python
# Line 240
def _update(self) -> None:

# Line 314
def _scan_devices(self) -> None:

# Line 323
def _initial_device_scan(self) -> None:

# Line 340
def _create_gauge_icon(self, color: str, size: int = 18) -> str:

# Line 400 - add stats type
def _update_title(self, stats: Optional['SpeedStats']) -> None:

# Line 458 - full signature
def _update_menu(
    self,
    conn: 'ConnectionInfo',
    stats: 'SpeedStats',
    avg_up: float,
    avg_down: float,
    peak_up: float,
    peak_down: float,
    session_sent: int,
    session_recv: int
) -> None:

# Line 870 - add device type
def _rename_device(self, device: 'NetworkDevice') -> None:
```

#### In `monitor/scanner.py`:

The file is well-typed after refactor. Verify these signatures:

```python
# Line 413 - check Tuple import
def infer_device_type(
    vendor: Optional[str],
    hostname: Optional[str],
    services: Optional[List[str]] = None,
    mdns_name: Optional[str] = None
) -> Tuple[str, Optional[str], Optional[str]]:
```

---

## 3. Performance Improvements

### 3.1 Batch Disk Writes in JsonStore

**File:** `storage/json_store.py`  
**Lines:** 93-112 (update_stats method), 74-80 (_save method)

**Problem:**
The `update_stats` method calls `self._save()` on every invocation (every 2 seconds). This causes unnecessary disk I/O.

**Implementation Steps:**

#### Step 1: Add dirty flag and save interval tracking

Modify `__init__` (after line 56):

```python
def __init__(self, data_dir: Optional[Path] = None):
    self.data_dir = data_dir or self.DEFAULT_DATA_DIR
    self.data_file = self.data_dir / self.DEFAULT_DATA_FILE
    self._lock = threading.Lock()
    self._data: Dict[str, Dict[str, Any]] = {}
    self._dirty = False  # Track if data needs saving
    self._last_save_time: float = 0  # Last save timestamp
    self._save_interval: float = 30.0  # Save at most every 30 seconds
    self._ensure_data_dir()
    self._load()
```

#### Step 2: Modify _save to be conditional

Replace the `_save` method (lines 74-80):

```python
def _save(self, force: bool = False) -> None:
    """Save data to JSON file if dirty and interval has passed.
    
    Args:
        force: If True, save immediately regardless of interval.
    """
    import time
    current_time = time.time()
    
    if not force and not self._dirty:
        return
    
    if not force and (current_time - self._last_save_time) < self._save_interval:
        return
    
    try:
        # Atomic write: write to temp file then rename
        temp_file = self.data_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(self._data, f, indent=2)
        temp_file.replace(self.data_file)
        self._dirty = False
        self._last_save_time = current_time
    except IOError as e:
        print(f"Error saving data: {e}")
```

#### Step 3: Update update_stats to mark dirty

Modify `update_stats` method - change line 112 from `self._save()` to:

```python
self._dirty = True
self._save()  # Will only actually save if interval passed
```

#### Step 4: Add flush method for shutdown

Add after the `_save` method:

```python
def flush(self) -> None:
    """Force save any pending changes. Call on application shutdown."""
    with self._lock:
        self._save(force=True)
```

#### Step 5: Call flush on app quit

In `network_monitor.py`, modify the `_quit` method (line 1241):

```python
def _quit(self, _):
    """Quit the application."""
    self._running = False
    self.store.flush()  # Save any pending data
    rumps.quit_application()
```

---

### 3.2 Clean Up Temporary Icon and Sparkline Files

**File:** `network_monitor.py`  
**Lines:** 59-64 (status icons), 526-538 (sparklines)

**Problem:**
The app creates temporary PNG files for icons and sparklines but never cleans them up.

**Implementation Steps:**

#### Step 1: Add cleanup infrastructure

Add import at top of `network_monitor.py`:
```python
import atexit
```

Add after line 108 in `NetworkMonitorApp.__init__`:

```python
# Track temp directories for cleanup
self._temp_dirs = [
    Path(tempfile.gettempdir()) / 'netmon-icons',
    Path(tempfile.gettempdir()) / 'netmon-sparklines',
]

# Register cleanup on exit
atexit.register(self._cleanup_temp_files)
```

#### Step 2: Add cleanup methods

Add to `NetworkMonitorApp` class:

```python
def _cleanup_temp_files(self) -> None:
    """Clean up temporary files created by the app."""
    import shutil
    for temp_dir in self._temp_dirs:
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        except Exception as e:
            print(f"Warning: Could not clean up {temp_dir}: {e}")

def _cleanup_old_sparklines(self) -> None:
    """Remove sparkline images older than 5 minutes."""
    import time as time_module
    sparkline_dir = Path(tempfile.gettempdir()) / 'netmon-sparklines'
    if not sparkline_dir.exists():
        return
    
    cutoff = time_module.time() - 300  # 5 minutes
    try:
        for file in sparkline_dir.glob('*.png'):
            if file.stat().st_mtime < cutoff:
                file.unlink()
    except Exception:
        pass
```

#### Step 3: Call cleanup in _quit

Update `_quit` method:

```python
def _quit(self, _):
    """Quit the application."""
    self._running = False
    self.store.flush()
    self._cleanup_temp_files()
    rumps.quit_application()
```

#### Step 4: Periodic cleanup during runtime

Add in `_update` method, after line 265 (device scan check):

```python
# Clean up old sparkline files periodically
if int(current_time) % 300 < self.UPDATE_INTERVAL:
    self._cleanup_old_sparklines()
```

---

## 4. Project Infrastructure

### 4.1 Add .gitignore File

**File to create:** `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
ENV/
env/
.venv/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~
.DS_Store

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/
.nox/

# Temp files
*.tmp
*.bak
*.log
```

---

### 4.2 Add pyproject.toml for Modern Packaging

**File to create:** `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "network-monitor"
version = "1.0.0"
description = "A macOS menu bar application for monitoring network traffic"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.9"
authors = [
    {name = "Your Name", email = "your.email@example.com"}
]
keywords = ["network", "monitor", "macos", "menu-bar", "traffic"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: MacOS X",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: MacOS",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: System :: Networking :: Monitoring",
]

dependencies = [
    "rumps>=0.4.0",
    "psutil>=5.9.0",
    "pillow>=10.0.0",
    "matplotlib>=3.7.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "mypy>=1.0.0",
]

[project.scripts]
network-monitor = "network_monitor:main"

[project.urls]
Homepage = "https://github.com/yourusername/network-monitor"
Repository = "https://github.com/yourusername/network-monitor"

[tool.setuptools.packages.find]
where = ["."]
include = ["monitor*", "storage*", "service*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true

[tool.coverage.run]
source = ["monitor", "storage", "service"]
omit = ["*/tests/*", "*/__pycache__/*"]
```

---

### 4.3 Pin Dependencies in requirements.txt

**File to modify:** `requirements.txt`

Update with pinned versions:

```txt
# Core dependencies - pinned for reproducibility
rumps==0.4.0
psutil==5.9.8
pillow==10.2.0
matplotlib==3.8.2
```

Create `requirements-dev.txt`:

```txt
-r requirements.txt

# Development dependencies
pytest>=7.0.0
pytest-cov>=4.0.0
mypy>=1.0.0
```

---

## 5. Testing

### 5.1 Create Test Suite with pytest

**Directory to create:** `tests/`

**Files to create:**
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/test_network.py`
- `tests/test_scanner.py`
- `tests/test_json_store.py`

#### tests/__init__.py

```python
"""Test suite for network-monitor."""
```

#### tests/conftest.py

```python
"""Pytest configuration and shared fixtures."""
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_stats_data():
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
```

#### tests/test_network.py

```python
"""Tests for monitor/network.py"""
import pytest
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
```

#### tests/test_scanner.py

```python
"""Tests for monitor/scanner.py"""
import pytest
from monitor.scanner import (
    NetworkDevice, DeviceType, DeviceNameStore, OUIDatabase,
    normalize_mac, infer_device_type
)


class TestNormalizeMac:
    """Tests for MAC address normalisation."""
    
    def test_already_normalized(self):
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"
    
    def test_lowercase(self):
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    
    def test_dash_separator(self):
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"
    
    def test_no_leading_zeros(self):
        assert normalize_mac("A:B:C:D:E:F") == "0A:0B:0C:0D:0E:0F"


class TestOUIDatabase:
    """Tests for OUI vendor lookup."""
    
    def test_singleton(self):
        db1 = OUIDatabase()
        db2 = OUIDatabase()
        assert db1 is db2
    
    def test_lookup_unknown(self):
        db = OUIDatabase()
        # Random MAC that's unlikely to be in database
        result = db.lookup("FF:FF:FF:11:22:33")
        # May or may not find it, but shouldn't crash
        assert result is None or isinstance(result, str)


class TestNetworkDevice:
    """Tests for the NetworkDevice dataclass."""
    
    def test_display_name_with_custom_name(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            custom_name="My iPhone"
        )
        assert device.display_name == "My iPhone"
    
    def test_display_name_with_mdns_name(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            mdns_name="Johns-MacBook"
        )
        assert device.display_name == "Johns-MacBook"
    
    def test_display_name_with_model_hint(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            model_hint="MacBook Pro"
        )
        assert device.display_name == "MacBook Pro"
    
    def test_display_name_with_hostname(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            hostname="johns-macbook.local"
        )
        assert device.display_name == "johns-macbook"
    
    def test_display_name_with_vendor(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            vendor="Samsung"
        )
        assert device.display_name == "Samsung"
    
    def test_display_name_fallback_to_ip(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF"
        )
        assert device.display_name == "192.168.1.100"
    
    def test_type_icon(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            device_type=DeviceType.PHONE
        )
        assert device.type_icon == "📱"


class TestInferDeviceType:
    """Tests for device type inference."""
    
    def test_iphone_hostname(self):
        dtype, os_hint, model = infer_device_type(None, "Johns-iPhone")
        assert dtype == DeviceType.PHONE
        assert os_hint == "iOS"
        assert model == "iPhone"
    
    def test_macbook_hostname(self):
        dtype, os_hint, model = infer_device_type(None, "MacBook-Pro")
        assert dtype == DeviceType.LAPTOP
        assert os_hint == "macOS"
    
    def test_apple_vendor_default(self):
        dtype, os_hint, model = infer_device_type("Apple", None)
        assert dtype == DeviceType.LAPTOP  # Default for Apple
    
    def test_samsung_vendor(self):
        dtype, os_hint, model = infer_device_type("Samsung", None)
        assert dtype == DeviceType.PHONE
    
    def test_cisco_vendor(self):
        dtype, os_hint, model = infer_device_type("Cisco", None)
        assert dtype == DeviceType.ROUTER
    
    def test_service_based_inference(self):
        dtype, os_hint, model = infer_device_type(
            None, None, services=["_printer._tcp"]
        )
        assert dtype == DeviceType.PRINTER
```

#### tests/test_json_store.py

```python
"""Tests for storage/json_store.py"""
import pytest
import json
from pathlib import Path
from storage.json_store import JsonStore, ConnectionStats


class TestConnectionStats:
    """Tests for the ConnectionStats dataclass."""
    
    def test_default_values(self):
        stats = ConnectionStats()
        assert stats.bytes_sent == 0
        assert stats.bytes_recv == 0
        assert stats.issues == []
    
    def test_to_dict(self):
        stats = ConnectionStats(bytes_sent=1000, bytes_recv=2000)
        result = stats.to_dict()
        assert result["bytes_sent"] == 1000
        assert result["bytes_recv"] == 2000
    
    def test_from_dict(self):
        data = {"bytes_sent": 5000, "bytes_recv": 10000, "issues": []}
        stats = ConnectionStats.from_dict(data)
        assert stats.bytes_sent == 5000
        assert stats.bytes_recv == 10000


class TestJsonStore:
    """Tests for the JsonStore class."""
    
    def test_init_creates_directory(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        assert temp_data_dir.exists()
    
    def test_update_stats(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Test", 1000, 2000, 100, 200)
        
        with open(store.data_file) as f:
            data = json.load(f)
        
        today = store._get_today_key()
        assert today in data
        assert "WiFi:Test" in data[today]
    
    def test_get_today_totals(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Home", 1000, 2000)
        store.update_stats("WiFi:Work", 3000, 4000)
        
        sent, recv = store.get_today_totals()
        assert sent == 4000
        assert recv == 6000
    
    def test_reset_today(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Test", 1000, 2000)
        store.reset_today()
        
        sent, recv = store.get_today_totals()
        assert sent == 0
        assert recv == 0
```

---

### 5.2 Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest

# Run with coverage
pytest --cov=monitor --cov=storage --cov=service --cov-report=html

# Run specific test file
pytest tests/test_network.py -v
```

---

## Implementation Order (Recommended)

1. **Critical bug fix** (Section 1.1) - Fix the crash first
2. **Add .gitignore** (Section 4.1) - Quick win, prevents accidents  
3. **Create test infrastructure** (Section 5) - Enables validation
4. **Consolidate format_bytes** (Section 2.1) - Code cleanup
5. **Batch disk writes** (Section 3.1) - Performance
6. **Temp file cleanup** (Section 3.2) - Resource management
7. **Add pyproject.toml** (Section 4.2) - Modern packaging
8. **Pin dependencies** (Section 4.3) - Reproducibility
9. **Add type hints** (Section 2.2) - Can be done incrementally

---

## Summary of Recent Changes

**Completed:**
- MAC vendor database extracted - now uses system OUI database from arp-scan (`OUIDatabase` class)
- Added `ToolChecker` class for detecting available tools
- Improved mDNS/Bonjour discovery with actual implementation
- Added `mdns_name` field to `NetworkDevice`
- Scanner reduced from 1711 to 834 lines
- Custom device naming feature

**Still Pending:**
- Critical `indicator` bug fix (lines 444, 449, 454, 456)
- Duplicate `format_bytes` consolidation
- Batched disk writes in JsonStore
- Temp file cleanup
- Project infrastructure (.gitignore, pyproject.toml)
- Test suite
- Type hints completion

---

## Verification Checklist

After implementing each change:

- [ ] Application starts without errors: `python network_monitor.py`
- [ ] All display modes work (latency, speed, session, devices)
- [ ] Device scanning works and shows vendors
- [ ] Tests pass: `pytest`
- [ ] No new linter errors
