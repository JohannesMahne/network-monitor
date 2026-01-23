"""Bandwidth throttling detection and alerts.

Monitors per-app bandwidth usage and alerts when thresholds are exceeded.
"""

import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Tuple

from config import get_logger

logger = get_logger(__name__)


@dataclass
class BandwidthAlert:
    """Represents a bandwidth threshold alert."""

    app_name: str
    current_mbps: float
    threshold_mbps: float
    window_seconds: int
    timestamp: float


@dataclass
class BandwidthSample:
    """A single bandwidth sample for an app."""

    timestamp: float
    bytes_in: int
    bytes_out: int


class BandwidthMonitor:
    """Monitors bandwidth usage per app and detects threshold violations.

    Tracks bandwidth over time windows and compares against configurable
    per-app thresholds.
    """

    def __init__(self):
        """Initialize the bandwidth monitor."""
        # Track bandwidth samples per app: app_name -> deque of BandwidthSample
        self._app_samples: Dict[str, deque] = {}
        # Track previous total bytes for delta calculation: app_name -> (bytes_in, bytes_out)
        self._previous_bytes: Dict[str, Tuple[int, int]] = {}
        # Track which apps have already triggered alerts (to avoid spam)
        self._alerted_apps: Dict[str, float] = {}  # app_name -> last_alert_time
        self._alert_cooldown: float = 300.0  # 5 minutes between alerts for same app
        logger.debug("BandwidthMonitor initialized")

    def check_thresholds(
        self, process_traffic: List[tuple], thresholds: Dict[str, float], window_seconds: int = 30
    ) -> List[BandwidthAlert]:
        """Check if any apps exceed their bandwidth thresholds.

        Args:
            process_traffic: List of (display_name, bytes_in, bytes_out, connections)
            thresholds: Dict mapping app_name -> threshold_mbps
            window_seconds: Time window for averaging bandwidth

        Returns:
            List of BandwidthAlert objects for apps exceeding thresholds
        """
        if not thresholds:
            return []

        current_time = time.time()
        alerts = []

        # Process each app's traffic
        for display_name, bytes_in, bytes_out, _ in process_traffic:
            if display_name not in thresholds:
                continue

            threshold_mbps = thresholds[display_name]
            if threshold_mbps <= 0:
                continue  # Threshold disabled

            # Initialize deque for this app if needed
            if display_name not in self._app_samples:
                self._app_samples[display_name] = deque(maxlen=window_seconds)
                self._previous_bytes[display_name] = (bytes_in, bytes_out)
                continue

            # Calculate delta from previous sample
            prev_bytes_in, prev_bytes_out = self._previous_bytes.get(display_name, (0, 0))
            delta_in = max(0, bytes_in - prev_bytes_in)
            delta_out = max(0, bytes_out - prev_bytes_out)

            # Store sample
            sample = BandwidthSample(timestamp=current_time, bytes_in=delta_in, bytes_out=delta_out)
            self._app_samples[display_name].append(sample)
            self._previous_bytes[display_name] = (bytes_in, bytes_out)

            # Calculate average bandwidth over window
            samples = self._app_samples[display_name]
            if len(samples) < 2:
                continue

            # Calculate total bytes transferred and time span
            oldest_sample = samples[0]
            newest_sample = samples[-1]

            time_delta = newest_sample.timestamp - oldest_sample.timestamp
            if time_delta < 1.0:  # Need at least 1 second of data
                continue

            # Sum all bytes in the window
            total_bytes = sum(s.bytes_in + s.bytes_out for s in samples)
            avg_bytes_per_second = total_bytes / time_delta
            avg_mbps = (avg_bytes_per_second * 8) / 1_000_000  # Convert to Mbps

            # Check if threshold exceeded
            if avg_mbps > threshold_mbps:
                # Check cooldown to avoid alert spam
                last_alert = self._alerted_apps.get(display_name, 0)
                if current_time - last_alert < self._alert_cooldown:
                    continue

                alert = BandwidthAlert(
                    app_name=display_name,
                    current_mbps=avg_mbps,
                    threshold_mbps=threshold_mbps,
                    window_seconds=window_seconds,
                    timestamp=current_time,
                )
                alerts.append(alert)
                self._alerted_apps[display_name] = current_time
                logger.warning(
                    f"Bandwidth threshold exceeded: {display_name} "
                    f"({avg_mbps:.2f} Mbps > {threshold_mbps:.2f} Mbps)"
                )

        return alerts

    def reset_alert_cooldown(self, app_name: str) -> None:
        """Reset the alert cooldown for an app (e.g., after user acknowledges)."""
        if app_name in self._alerted_apps:
            del self._alerted_apps[app_name]

    def clear_samples(self) -> None:
        """Clear all bandwidth samples (e.g., on session reset)."""
        self._app_samples.clear()
        self._previous_bytes.clear()
        self._alerted_apps.clear()
