"""Configuration module for Network Monitor.

Provides centralized configuration, logging, exceptions, and utilities.
"""
from config.constants import (
    INTERVALS, THRESHOLDS, STORAGE, COLORS, NETWORK, UI, LAUNCH_AGENT,
    Intervals, Thresholds, StorageConfig, Colors, NetworkConfig, UIConfig, LaunchAgentConfig,
    ALLOWED_SUBPROCESS_COMMANDS,
)
from config.exceptions import (
    NetworkMonitorError,
    ConnectionError,
    StorageError,
    ScannerError,
    ConfigurationError,
    SubprocessError,
)
from config.logging_config import setup_logging, get_logger
from config.subprocess_cache import SubprocessCache, safe_run, get_subprocess_cache

__all__ = [
    # Constants
    "INTERVALS",
    "THRESHOLDS", 
    "STORAGE",
    "COLORS",
    "NETWORK",
    "UI",
    "LAUNCH_AGENT",
    "Intervals",
    "Thresholds",
    "StorageConfig",
    "Colors",
    "NetworkConfig",
    "UIConfig",
    "LaunchAgentConfig",
    "ALLOWED_SUBPROCESS_COMMANDS",
    # Exceptions
    "NetworkMonitorError",
    "ConnectionError",
    "StorageError",
    "ScannerError",
    "ConfigurationError",
    "SubprocessError",
    # Logging
    "setup_logging",
    "get_logger",
    # Subprocess
    "SubprocessCache",
    "safe_run",
    "get_subprocess_cache",
]
