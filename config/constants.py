"""Centralized constants and configuration for Network Monitor.

This module contains all magic numbers, strings, and configuration values
that were previously scattered throughout the codebase. Centralizing them
makes the code easier to maintain and configure.

Usage:
    from config.constants import INTERVALS, THRESHOLDS, STORAGE
    
    # Access values
    update_interval = INTERVALS.UPDATE_SECONDS
    latency_threshold = THRESHOLDS.LATENCY_GOOD_MS
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Intervals:
    """Time intervals for various operations (in seconds).
    
    All interval values are in seconds unless otherwise specified.
    """
    # Main update loop
    UPDATE_SECONDS: float = 3.0

    # Adaptive update intervals (adjusts based on activity)
    UPDATE_FAST_SECONDS: float = 2.0     # When high activity detected
    UPDATE_NORMAL_SECONDS: float = 4.0   # Normal operation
    UPDATE_SLOW_SECONDS: float = 6.0     # When idle/low activity

    # Activity thresholds for adaptive intervals (bytes/sec)
    ACTIVITY_HIGH_THRESHOLD: int = 100_000     # 100 KB/s = fast updates
    ACTIVITY_LOW_THRESHOLD: int = 1_000        # 1 KB/s = slow updates
    ACTIVITY_CHECK_SAMPLES: int = 5            # Number of samples to average

    # Device scanning
    DEVICE_SCAN_SECONDS: float = 10800.0  # 3 hours
    MDNS_SCAN_SECONDS: float = 10800.0    # 3 hours

    # Latency checking
    LATENCY_CHECK_SECONDS: float = 10.0

    # Traffic monitoring
    TRAFFIC_UPDATE_SECONDS: float = 5.0

    # Data persistence
    SAVE_INTERVAL_SECONDS: float = 30.0

    # Subprocess timeouts
    SUBPROCESS_TIMEOUT_SECONDS: float = 5.0
    PING_TIMEOUT_SECONDS: float = 2.0
    LSOF_TIMEOUT_SECONDS: float = 3.0
    NETTOP_TIMEOUT_SECONDS: float = 5.0


@dataclass(frozen=True)
class Thresholds:
    """Threshold values for various measurements."""
    # Latency thresholds (milliseconds)
    LATENCY_GOOD_MS: int = 50      # Green: < 50ms
    LATENCY_OK_MS: int = 100       # Yellow: 50-100ms
    LATENCY_POOR_MS: int = 150     # Red: > 100ms (for reference)
    HIGH_LATENCY_MS: int = 200     # Trigger issue logging

    # Speed drop detection
    SPEED_DROP_RATIO: float = 0.1  # Alert if speed drops to 10% of average
    MIN_SPEED_FOR_DROP_ALERT: int = 1024  # Only alert if avg > 1KB/s

    # History sizes
    SPEED_SAMPLE_COUNT: int = 100  # Number of samples for speed averaging
    LATENCY_SAMPLE_COUNT: int = 30  # Number of samples for latency averaging
    SPARKLINE_HISTORY_SIZE: int = 20  # Data points in sparkline graphs

    # Issue tracking
    MAX_ISSUES_STORED: int = 100


@dataclass(frozen=True)
class StorageConfig:
    """Storage and file-related configuration."""
    # Directory and file names
    DATA_DIR_NAME: str = ".network-monitor"
    STATS_FILE: str = "stats.json"  # Legacy JSON storage
    SETTINGS_FILE: str = "settings.json"
    DEVICES_FILE: str = "device_names.json"
    LOG_FILE: str = "network_monitor.log"
    STDOUT_LOG: str = "stdout.log"
    STDERR_LOG: str = "stderr.log"

    # SQLite database
    DATABASE_FILE: str = "network_monitor.db"

    # Data retention
    RETENTION_DAYS: int = 90
    HISTORY_DAYS_DEFAULT: int = 7
    MONTHLY_DAYS: int = 30

    # Automatic cleanup
    CLEANUP_ON_STARTUP: bool = True  # Run cleanup when app starts

    # Log rotation
    LOG_MAX_BYTES: int = 5_000_000  # 5MB
    LOG_BACKUP_COUNT: int = 3

    # Temp directories
    ICON_TEMP_DIR: str = "netmon-icons"
    SPARKLINE_TEMP_DIR: str = "netmon-sparklines"

    # Sparkline cleanup
    SPARKLINE_MAX_AGE_SECONDS: int = 300  # 5 minutes

    # Backup settings
    BACKUP_DIR: str = "backups"
    MAX_BACKUPS: int = 5  # Keep last N backups


@dataclass(frozen=True)
class Colors:
    """Color definitions for UI elements.
    
    Colors are defined as RGBA tuples (0-255) for PIL
    and hex strings for matplotlib.
    """
    # Status colors (RGBA for PIL)
    GREEN_RGBA: Tuple[int, int, int, int] = (52, 199, 89, 255)    # macOS green
    YELLOW_RGBA: Tuple[int, int, int, int] = (255, 204, 0, 255)   # macOS yellow
    RED_RGBA: Tuple[int, int, int, int] = (255, 59, 48, 255)      # macOS red
    GRAY_RGBA: Tuple[int, int, int, int] = (142, 142, 147, 255)   # macOS gray
    BLUE_RGBA: Tuple[int, int, int, int] = (0, 122, 255, 255)     # macOS blue

    # Hex colors for matplotlib
    GREEN_HEX: str = "#34C759"
    YELLOW_HEX: str = "#FF9500"
    RED_HEX: str = "#FF3B30"
    GRAY_HEX: str = "#8E8E93"
    BLUE_HEX: str = "#007AFF"

    # Sparkline colors
    UPLOAD_COLOR: str = "#34C759"    # Green
    DOWNLOAD_COLOR: str = "#007AFF"  # Blue
    LATENCY_COLOR: str = "#FF9500"   # Orange
    QUALITY_COLOR: str = "#AF52DE"   # Purple
    TOTAL_COLOR: str = "#FF2D55"     # Pink/Magenta (distinct from purple)


@dataclass(frozen=True)
class NetworkConfig:
    """Network-related configuration."""
    # Ping targets
    DEFAULT_PING_HOST: str = "8.8.8.8"
    BACKUP_PING_HOSTS: Tuple[str, ...] = ("1.1.1.1", "208.67.222.222")

    # Device scanning
    ARP_SCAN_TIMEOUT: float = 5.0
    HOSTNAME_RESOLVE_TIMEOUT: float = 2.0
    MDNS_BROWSE_TIMEOUT: float = 0.5
    
    # DNS monitoring
    DNS_CHECK_INTERVAL: float = 30.0  # Check DNS every 30 seconds
    DNS_SLOW_THRESHOLD_MS: float = 200.0  # Alert if DNS > 200ms

    # Common mDNS services to discover
    MDNS_SERVICES: Tuple[str, ...] = (
        "_airplay._tcp",
        "_raop._tcp",
        "_googlecast._tcp",
        "_hap._tcp",
        "_printer._tcp",
        "_ipp._tcp",
        "_smb._tcp",
        "_companion-link._tcp",
    )


@dataclass(frozen=True)
class UIConfig:
    """UI-related configuration."""
    # Icon sizes
    STATUS_ICON_SIZE: int = 18
    SPARKLINE_WIDTH: int = 120
    SPARKLINE_HEIGHT: int = 16

    # Menu item limits
    MAX_DEVICES_SHOWN: int = 5
    MAX_APPS_SHOWN: int = 5
    MAX_EVENTS_SHOWN: int = 10
    MAX_CONNECTIONS_SHOWN: int = 10

    # Text truncation
    MAX_CONNECTION_NAME_LENGTH: int = 25
    MAX_DEVICE_NAME_LENGTH: int = 25
    MAX_EVENT_DESCRIPTION_LENGTH: int = 35

    # Progress bar
    PROGRESS_BAR_WIDTH: int = 12


@dataclass(frozen=True)
class LaunchAgentConfig:
    """Launch agent configuration."""
    AGENT_LABEL: str = "com.networkmonitor.app"
    AGENT_FILENAME: str = "com.networkmonitor.app.plist"


# Global instances - import these
INTERVALS = Intervals()
THRESHOLDS = Thresholds()
STORAGE = StorageConfig()
COLORS = Colors()
NETWORK = NetworkConfig()
UI = UIConfig()
LAUNCH_AGENT = LaunchAgentConfig()


# Allowed commands for subprocess safety
ALLOWED_SUBPROCESS_COMMANDS = frozenset({
    'arp',
    'ping',
    'networksetup',
    'lsof',
    'nettop',
    'dns-sd',
    'ipconfig',
    'launchctl',
    'which',
    'open',
})
