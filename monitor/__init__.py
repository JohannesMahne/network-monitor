"""Network monitoring components.

This package provides modules for collecting network statistics,
detecting connections, scanning for devices, and monitoring traffic.

Modules:
    network: Network I/O statistics collection
    connection: WiFi/Ethernet/VPN connection detection
    issues: Network issue detection and logging
    scanner: Network device discovery (Fing-like)
    traffic: Per-process traffic monitoring
    utils: Shared utility functions

Example:
    >>> from monitor import NetworkStats, ConnectionDetector
    >>> stats = NetworkStats()
    >>> stats.initialize()
    >>> detector = ConnectionDetector()
    >>> conn = detector.get_current_connection()
    >>> print(f"Connected to: {conn.name}")
"""
from .connection import ConnectionDetector, ConnectionInfo
from .issues import IssueDetector, IssueType, NetworkIssue
from .network import NetworkStats, SpeedStats
from .scanner import NetworkDevice, NetworkScanner
from .traffic import ProcessTraffic, TrafficMonitor, format_traffic_bytes
from .utils import format_bytes, format_duration

__all__ = [
    # Network stats
    "NetworkStats",
    "SpeedStats",
    # Connection detection
    "ConnectionDetector",
    "ConnectionInfo",
    # Issue detection
    "IssueDetector",
    "IssueType",
    "NetworkIssue",
    # Device scanning
    "NetworkScanner",
    "NetworkDevice",
    # Traffic monitoring
    "TrafficMonitor",
    "ProcessTraffic",
    # Utilities
    "format_bytes",
    "format_traffic_bytes",
    "format_duration",
]
