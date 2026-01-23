"""Settings and budget management for Network Monitor."""

import json
import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

from config import STORAGE, get_logger

logger = get_logger(__name__)


class BudgetPeriod(Enum):
    """Budget period options."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TitleDisplayMode(Enum):
    """What to show in the menu bar title."""

    LATENCY = "latency"  # Current latency (e.g., "15ms")
    SESSION_DATA = "session"  # Session up/down (e.g., "↑12MB ↓45MB")
    SPEED = "speed"  # Current speed (e.g., "↑1.2KB/s ↓5.4KB/s")
    DEVICES = "devices"  # Device count (e.g., "17 devices")
    QUALITY = "quality"  # Network quality score (e.g., "85/100")


@dataclass
class ConnectionBudget:
    """Budget settings for a specific connection."""

    enabled: bool = False
    limit_bytes: int = 0  # Total bytes (up + down) limit
    period: str = "monthly"  # daily, weekly, monthly
    warn_at_percent: int = 80  # Warn when this % is reached

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ConnectionBudget":
        return cls(
            enabled=data.get("enabled", False),
            limit_bytes=data.get("limit_bytes", 0),
            period=data.get("period", "monthly"),
            warn_at_percent=data.get("warn_at_percent", 80),
        )


@dataclass
class BandwidthAlertSettings:
    """Settings for bandwidth throttling alerts."""

    enabled: bool = False
    threshold_mbps: float = 10.0  # Default 10 Mbps per app
    window_seconds: int = 30  # Time window for averaging
    per_app_thresholds: Dict[str, float] = field(default_factory=dict)  # app_name -> threshold_mbps


@dataclass
class NotificationSettings:
    """Settings for network change notifications."""

    notify_new_device: bool = True
    notify_quality_degraded: bool = True
    notify_vpn_disconnect: bool = True
    quality_degraded_threshold: int = 30  # Quality score below this triggers notification


@dataclass
class AppSettings:
    """Application settings."""

    title_display: str = "latency"  # What to show in menu bar
    budgets: Dict[str, dict] = field(default_factory=dict)  # connection_key -> budget
    bandwidth_alerts: dict = field(default_factory=dict)  # Bandwidth alert settings
    notifications: dict = field(default_factory=dict)  # Notification preferences

    # Latency thresholds (industry standard)
    # https://www.pingdom.com/blog/latency-benchmarks/
    latency_good: int = 50  # < 50ms = good (green)
    latency_ok: int = 100  # 50-100ms = acceptable (yellow)
    latency_poor: int = 150  # > 100ms = poor (red)

    def to_dict(self) -> dict:
        return {
            "title_display": self.title_display,
            "budgets": self.budgets,
            "bandwidth_alerts": self.bandwidth_alerts,
            "notifications": self.notifications,
            "latency_good": self.latency_good,
            "latency_ok": self.latency_ok,
            "latency_poor": self.latency_poor,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        return cls(
            title_display=data.get("title_display", "latency"),
            budgets=data.get("budgets", {}),
            bandwidth_alerts=data.get("bandwidth_alerts", {}),
            notifications=data.get("notifications", {}),
            latency_good=data.get("latency_good", 50),
            latency_ok=data.get("latency_ok", 100),
            latency_poor=data.get("latency_poor", 150),
        )


class SettingsManager:
    """Manages application settings and budgets."""

    DEFAULT_SETTINGS_FILE = STORAGE.SETTINGS_FILE

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.settings_file = data_dir / self.DEFAULT_SETTINGS_FILE
        self._lock = threading.Lock()
        self._settings: AppSettings = AppSettings()
        self._load()
        logger.debug(f"SettingsManager initialized at {self.settings_file}")

    def _load(self) -> None:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file) as f:
                    data = json.load(f)
                    self._settings = AppSettings.from_dict(data)
                logger.debug("Settings loaded successfully")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not load settings: {e}")
                self._settings = AppSettings()
        else:
            self._settings = AppSettings()
            logger.debug("No existing settings file, using defaults")

    def _save(self) -> None:
        """Save settings to file."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w") as f:
                json.dump(self._settings.to_dict(), f, indent=2)
            logger.debug("Settings saved successfully")
        except OSError as e:
            logger.error(f"Error saving settings: {e}")

    # === Title Display ===

    def get_title_display(self) -> str:
        """Get current title display mode."""
        return self._settings.title_display

    def set_title_display(self, mode: str) -> None:
        """Set title display mode."""
        with self._lock:
            self._settings.title_display = mode
            self._save()

    def get_title_display_options(self) -> list:
        """Get available title display options."""
        return [
            ("latency", "Latency (e.g., 15ms)"),
            ("session", "Session Data (e.g., ↑12MB ↓45MB)"),
            ("speed", "Current Speed (e.g., ↑1.2KB/s)"),
            ("devices", "Device Count (e.g., 17 devices)"),
            ("quality", "Quality Score (e.g., 85%)"),
        ]

    # === Latency Thresholds ===

    def get_latency_color(self, latency_ms: float) -> str:
        """Get color for latency value based on thresholds."""
        if latency_ms < self._settings.latency_good:
            return "green"
        elif latency_ms < self._settings.latency_ok:
            return "yellow"
        else:
            return "red"

    # === Budget Management ===

    def get_budget(self, connection_key: str) -> Optional[ConnectionBudget]:
        """Get budget for a connection."""
        if connection_key in self._settings.budgets:
            return ConnectionBudget.from_dict(self._settings.budgets[connection_key])
        return None

    def set_budget(self, connection_key: str, budget: ConnectionBudget) -> None:
        """Set budget for a connection."""
        with self._lock:
            self._settings.budgets[connection_key] = budget.to_dict()
            self._save()

    def remove_budget(self, connection_key: str) -> None:
        """Remove budget for a connection."""
        with self._lock:
            if connection_key in self._settings.budgets:
                del self._settings.budgets[connection_key]
                self._save()

    def get_all_budgets(self) -> Dict[str, ConnectionBudget]:
        """Get all connection budgets."""
        return {
            key: ConnectionBudget.from_dict(data) for key, data in self._settings.budgets.items()
        }

    def check_budget_status(
        self, connection_key: str, current_usage: int, period_usage: int
    ) -> dict:
        """Check budget status for a connection.

        Args:
            connection_key: Connection identifier
            current_usage: Current period's total bytes (up + down)
            period_usage: Usage for the budget period (day/week/month)

        Returns:
            dict with: exceeded, warning, percent_used, limit_bytes, remaining_bytes
        """
        budget = self.get_budget(connection_key)

        if not budget or not budget.enabled or budget.limit_bytes <= 0:
            return {
                "has_budget": False,
                "exceeded": False,
                "warning": False,
                "percent_used": 0,
                "limit_bytes": 0,
                "remaining_bytes": 0,
            }

        percent_used = (period_usage / budget.limit_bytes) * 100 if budget.limit_bytes > 0 else 0
        remaining = max(0, budget.limit_bytes - period_usage)

        return {
            "has_budget": True,
            "exceeded": period_usage >= budget.limit_bytes,
            "warning": percent_used >= budget.warn_at_percent,
            "percent_used": min(100, percent_used),
            "limit_bytes": budget.limit_bytes,
            "remaining_bytes": remaining,
            "period": budget.period,
        }

    # === Bandwidth Alerts ===

    def get_bandwidth_alert_settings(self) -> BandwidthAlertSettings:
        """Get bandwidth alert settings."""
        alerts_data = self._settings.bandwidth_alerts
        if not alerts_data:
            return BandwidthAlertSettings()

        return BandwidthAlertSettings(
            enabled=alerts_data.get("enabled", False),
            threshold_mbps=alerts_data.get("threshold_mbps", 10.0),
            window_seconds=alerts_data.get("window_seconds", 30),
            per_app_thresholds=alerts_data.get("per_app_thresholds", {}),
        )

    def set_bandwidth_alert_settings(self, settings: BandwidthAlertSettings) -> None:
        """Set bandwidth alert settings."""
        with self._lock:
            self._settings.bandwidth_alerts = {
                "enabled": settings.enabled,
                "threshold_mbps": settings.threshold_mbps,
                "window_seconds": settings.window_seconds,
                "per_app_thresholds": settings.per_app_thresholds,
            }
            self._save()

    def get_bandwidth_thresholds(self) -> Dict[str, float]:
        """Get bandwidth thresholds for all apps.

        Returns dict mapping app_name -> threshold_mbps.
        Uses per-app thresholds if set, otherwise default threshold.
        """
        alerts = self.get_bandwidth_alert_settings()
        if not alerts.enabled:
            return {}

        thresholds = {}
        # Start with default threshold for all apps
        default_threshold = alerts.threshold_mbps

        # Override with per-app thresholds
        for app_name, threshold in alerts.per_app_thresholds.items():
            thresholds[app_name] = threshold

        return thresholds

    def set_app_bandwidth_threshold(self, app_name: str, threshold_mbps: float) -> None:
        """Set bandwidth threshold for a specific app."""
        alerts = self.get_bandwidth_alert_settings()
        alerts.per_app_thresholds[app_name] = threshold_mbps
        self.set_bandwidth_alert_settings(alerts)

    # === Notification Settings ===

    def get_notification_settings(self) -> NotificationSettings:
        """Get notification settings."""
        notif_data = self._settings.notifications
        if not notif_data:
            return NotificationSettings()

        return NotificationSettings(
            notify_new_device=notif_data.get("notify_new_device", True),
            notify_quality_degraded=notif_data.get("notify_quality_degraded", True),
            notify_vpn_disconnect=notif_data.get("notify_vpn_disconnect", True),
            quality_degraded_threshold=notif_data.get("quality_degraded_threshold", 30),
        )

    def set_notification_settings(self, settings: NotificationSettings) -> None:
        """Set notification settings."""
        with self._lock:
            self._settings.notifications = {
                "notify_new_device": settings.notify_new_device,
                "notify_quality_degraded": settings.notify_quality_degraded,
                "notify_vpn_disconnect": settings.notify_vpn_disconnect,
                "quality_degraded_threshold": settings.quality_degraded_threshold,
            }
            self._save()

    # === Keyboard Shortcuts ===

    def get_keyboard_shortcut(self) -> str:
        """Get current keyboard shortcut.

        Returns:
            Shortcut string (e.g., "cmd+shift+n")
        """
        shortcuts = self._settings.notifications.get("keyboard_shortcut", "cmd+shift+n")
        return shortcuts

    def set_keyboard_shortcut(self, shortcut: str) -> None:
        """Set keyboard shortcut."""
        with self._lock:
            if "notifications" not in self._settings.notifications:
                self._settings.notifications = {}
            self._settings.notifications["keyboard_shortcut"] = shortcut
            self._save()


def get_settings_manager(data_dir: Optional[Path] = None) -> SettingsManager:
    """Get or create settings manager singleton."""
    if data_dir is None:
        data_dir = Path.home() / STORAGE.DATA_DIR_NAME
    return SettingsManager(data_dir)
