"""Shared utility functions for network monitoring.

This module provides common utilities used across the network monitoring
application, including formatting functions for human-readable output.

Example:
    >>> from monitor.utils import format_bytes
    >>> format_bytes(1500000)
    '1.4 MB'
    >>> format_bytes(1500000, speed=True)
    '1.4 MB/s'
"""

from __future__ import annotations

from typing import Union

# Type alias for numeric values
NumericValue = Union[int, float]


def format_bytes(bytes_value: NumericValue, speed: bool = False) -> str:
    """Format bytes to human-readable string.

    Converts a byte count to a human-readable string using appropriate
    units (B, KB, MB, GB, TB, PB). Uses 1024 as the base for conversion.

    Args:
        bytes_value: The number of bytes to format. Can be int or float.
        speed: If True, append '/s' suffix for speed display.

    Returns:
        Human-readable string like "1.4 MB" or "1.4 MB/s".

    Examples:
        >>> format_bytes(0)
        '0 B'
        >>> format_bytes(1024)
        '1.0 KB'
        >>> format_bytes(1500000)
        '1.4 MB'
        >>> format_bytes(1500000, speed=True)
        '1.4 MB/s'
        >>> format_bytes(1099511627776)
        '1.0 TB'
    """
    if bytes_value == 0:
        suffix = "/s" if speed else ""
        return f"0 B{suffix}"

    suffix = "/s" if speed else ""
    value = float(bytes_value)

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}{suffix}"
        value /= 1024.0
    return f"{value:.1f} PB{suffix}"


def format_duration(seconds: NumericValue) -> str:
    """Format seconds to human-readable duration string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable string like "5s", "2m 30s", "1h 15m".

    Examples:
        >>> format_duration(45)
        '45s'
        >>> format_duration(150)
        '2m 30s'
        >>> format_duration(3665)
        '1h 1m'
    """
    seconds = int(seconds)

    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"


__all__ = ["NumericValue", "format_bytes", "format_duration"]
