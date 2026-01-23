"""Custom exception hierarchy for Network Monitor.

Provides specific exceptions for different error categories,
enabling better error handling and debugging.
"""

from typing import Optional


class NetworkMonitorError(Exception):
    """Base exception for all Network Monitor errors.

    All custom exceptions in this application should inherit from this class.
    This allows catching all application-specific errors with a single except clause.

    Attributes:
        message: Human-readable error description.
        details: Optional dictionary with additional error context.
    """

    def __init__(self, message: str, details: Optional[dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConnectionError(NetworkMonitorError):
    """Network connection related errors.

    Raised when there are issues with:
    - Detecting network connection type
    - Getting WiFi SSID
    - Network interface access

    Examples:
        >>> raise ConnectionError("Failed to detect WiFi SSID", {"interface": "en0"})
    """

    pass


class StorageError(NetworkMonitorError):
    """Data persistence errors.

    Raised when there are issues with:
    - Reading/writing JSON data files
    - Database operations
    - File permissions
    - Data corruption

    Examples:
        >>> raise StorageError("Failed to save statistics", {"path": "/path/to/file"})
    """

    pass


class ScannerError(NetworkMonitorError):
    """Device scanning errors.

    Raised when there are issues with:
    - ARP table scanning
    - mDNS discovery
    - Hostname resolution
    - OUI database lookup

    Examples:
        >>> raise ScannerError("ARP scan timed out", {"timeout": 5})
    """

    pass


class ConfigurationError(NetworkMonitorError):
    """Settings and configuration errors.

    Raised when there are issues with:
    - Invalid configuration values
    - Missing required settings
    - Configuration file parsing

    Examples:
        >>> raise ConfigurationError("Invalid latency threshold", {"value": -10})
    """

    pass


class SubprocessError(NetworkMonitorError):
    """Subprocess execution errors.

    Raised when there are issues with:
    - Command execution failures
    - Timeouts
    - Permission denied
    - Command not found

    Attributes:
        command: The command that failed.
        returncode: Exit code if available.
        stdout: Standard output if available.
        stderr: Standard error if available.

    Examples:
        >>> raise SubprocessError(
        ...     "Command failed",
        ...     details={"command": ["ping", "-c", "1", "8.8.8.8"], "returncode": 1}
        ... )
    """

    def __init__(
        self,
        message: str,
        command: Optional[list] = None,
        returncode: Optional[int] = None,
        stdout: Optional[str] = None,
        stderr: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        details = details or {}
        if command:
            details["command"] = command
        if returncode is not None:
            details["returncode"] = returncode
        if stdout:
            details["stdout"] = stdout[:500]  # Truncate long output
        if stderr:
            details["stderr"] = stderr[:500]

        super().__init__(message, details)
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LatencyError(NetworkMonitorError):
    """Latency measurement errors.

    Raised when ping operations fail or return unexpected results.
    """

    pass


class BudgetError(NetworkMonitorError):
    """Budget-related errors.

    Raised when there are issues with:
    - Invalid budget configuration
    - Budget calculation errors
    """

    pass
