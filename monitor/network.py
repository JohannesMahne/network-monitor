"""Network statistics collection using psutil.

This module provides real-time network statistics including upload/download
speeds, session totals, and peak speed tracking. It uses psutil for
cross-platform network I/O counter collection.

Example:
    >>> stats = NetworkStats()
    >>> stats.initialize()
    >>> current = stats.get_current_stats()
    >>> if current:
    ...     print(f"Download: {current.download_speed:.0f} B/s")
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import psutil

from config import THRESHOLDS, get_logger
from monitor.utils import format_bytes

logger = get_logger(__name__)


@dataclass
class SpeedStats:
    """Current network speed statistics.

    Attributes:
        upload_speed: Current upload speed in bytes per second.
        download_speed: Current download speed in bytes per second.
        total_sent: Total bytes sent since system boot.
        total_recv: Total bytes received since system boot.
    """

    upload_speed: float
    download_speed: float
    total_sent: int
    total_recv: int


class NetworkStats:
    """Collects and calculates network statistics.

    This class tracks network I/O counters over time to calculate
    current speeds, session totals, peak speeds, and running averages.

    Attributes:
        SPEED_SAMPLE_COUNT: Number of samples to keep for averaging.

    Example:
        >>> stats = NetworkStats()
        >>> stats.initialize()
        >>> # Get current stats periodically
        >>> current = stats.get_current_stats()
        >>> sent, recv = stats.get_session_totals()
    """

    def __init__(self) -> None:
        """Initialize the NetworkStats collector."""
        self._last_bytes_sent: int = 0
        self._last_bytes_recv: int = 0
        self._last_time: float = 0
        self._session_start_sent: int = 0
        self._session_start_recv: int = 0
        self._session_start_time: float = 0
        self._peak_upload: float = 0
        self._peak_download: float = 0
        self._speed_samples: List[Tuple[float, float]] = []
        self._initialized: bool = False

    def _get_total_bytes(self) -> Tuple[int, int]:
        """Get total bytes sent and received across all interfaces.

        Returns:
            Tuple of (bytes_sent, bytes_received) since system boot.
        """
        counters = psutil.net_io_counters()
        return counters.bytes_sent, counters.bytes_recv

    def initialize(self) -> None:
        """Initialize the baseline measurements.

        Call this once before collecting stats. Automatically called
        by get_current_stats() if not already initialized.
        """
        sent, recv = self._get_total_bytes()
        current_time = time.time()

        self._last_bytes_sent = sent
        self._last_bytes_recv = recv
        self._last_time = current_time
        self._session_start_sent = sent
        self._session_start_recv = recv
        self._session_start_time = current_time
        self._initialized = True
        logger.debug("NetworkStats initialized")

    def get_current_stats(self) -> Optional[SpeedStats]:
        """Get current network statistics including speed.

        Calculates upload/download speeds based on bytes transferred
        since the last call. Updates peak speeds and rolling averages.

        Returns:
            SpeedStats with current speeds and totals, or None if
            not enough time has passed since last measurement.

        Note:
            Call this periodically (e.g., every 1-2 seconds) for
            accurate speed measurements.
        """
        if not self._initialized:
            self.initialize()
            return None

        current_time = time.time()
        sent, recv = self._get_total_bytes()

        time_delta = current_time - self._last_time
        if time_delta < 0.1:  # Avoid division by very small numbers
            return None

        # Calculate speeds
        bytes_sent_delta = sent - self._last_bytes_sent
        bytes_recv_delta = recv - self._last_bytes_recv

        upload_speed = bytes_sent_delta / time_delta
        download_speed = bytes_recv_delta / time_delta

        # Update peak speeds
        self._peak_upload = max(self._peak_upload, upload_speed)
        self._peak_download = max(self._peak_download, download_speed)

        # Store for averaging
        self._speed_samples.append((upload_speed, download_speed))
        # Keep last N samples for average calculation
        if len(self._speed_samples) > THRESHOLDS.SPEED_SAMPLE_COUNT:
            self._speed_samples.pop(0)

        # Update last values
        self._last_bytes_sent = sent
        self._last_bytes_recv = recv
        self._last_time = current_time

        return SpeedStats(
            upload_speed=upload_speed,
            download_speed=download_speed,
            total_sent=sent,
            total_recv=recv,
        )

    def get_session_totals(self) -> Tuple[int, int]:
        """Get bytes sent/received since session start.

        Returns:
            Tuple of (bytes_sent, bytes_received) for current session.
        """
        sent, recv = self._get_total_bytes()
        return (
            sent - self._session_start_sent,
            recv - self._session_start_recv,
        )

    def get_peak_speeds(self) -> Tuple[float, float]:
        """Get peak upload and download speeds for the session.

        Returns:
            Tuple of (peak_upload, peak_download) in bytes per second.
        """
        return self._peak_upload, self._peak_download

    def get_average_speeds(self) -> Tuple[float, float]:
        """Get average upload and download speeds.

        Calculates average from the last N speed samples, where N
        is configured by THRESHOLDS.SPEED_SAMPLE_COUNT.

        Returns:
            Tuple of (avg_upload, avg_download) in bytes per second.
        """
        if not self._speed_samples:
            return 0.0, 0.0

        avg_upload = sum(s[0] for s in self._speed_samples) / len(self._speed_samples)
        avg_download = sum(s[1] for s in self._speed_samples) / len(self._speed_samples)
        return avg_upload, avg_download

    def reset_session(self) -> None:
        """Reset session statistics.

        Clears session totals, peak speeds, and speed samples.
        Does not affect the initialized state.
        """
        self._session_start_sent, self._session_start_recv = self._get_total_bytes()
        self._session_start_time = time.time()
        self._peak_upload = 0
        self._peak_download = 0
        self._speed_samples = []


# Re-export format_bytes for backwards compatibility
__all__ = ["NetworkStats", "SpeedStats", "format_bytes"]
