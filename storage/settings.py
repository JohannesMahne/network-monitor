"""Settings and budget management for Network Monitor."""
import json
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
import threading


class BudgetPeriod(Enum):
    """Budget period options."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TitleDisplayMode(Enum):
    """What to show in the menu bar title."""
    LATENCY = "latency"           # Current latency (e.g., "15ms")
    SESSION_DATA = "session"      # Session up/down (e.g., "↑12MB ↓45MB")
    SPEED = "speed"               # Current speed (e.g., "↑1.2KB/s ↓5.4KB/s")
    DEVICES = "devices"           # Device count (e.g., "17 devices")


@dataclass
class ConnectionBudget:
    """Budget settings for a specific connection."""
    enabled: bool = False
    limit_bytes: int = 0          # Total bytes (up + down) limit
    period: str = "monthly"       # daily, weekly, monthly
    warn_at_percent: int = 80     # Warn when this % is reached
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ConnectionBudget':
        return cls(
            enabled=data.get("enabled", False),
            limit_bytes=data.get("limit_bytes", 0),
            period=data.get("period", "monthly"),
            warn_at_percent=data.get("warn_at_percent", 80)
        )


@dataclass  
class AppSettings:
    """Application settings."""
    title_display: str = "latency"    # What to show in menu bar
    budgets: Dict[str, dict] = field(default_factory=dict)  # connection_key -> budget
    
    # Latency thresholds (industry standard)
    # https://www.pingdom.com/blog/latency-benchmarks/
    latency_good: int = 50        # < 50ms = good (green)
    latency_ok: int = 100         # 50-100ms = acceptable (yellow)
    latency_poor: int = 150       # > 100ms = poor (red)
    
    def to_dict(self) -> dict:
        return {
            "title_display": self.title_display,
            "budgets": self.budgets,
            "latency_good": self.latency_good,
            "latency_ok": self.latency_ok,
            "latency_poor": self.latency_poor,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AppSettings':
        return cls(
            title_display=data.get("title_display", "latency"),
            budgets=data.get("budgets", {}),
            latency_good=data.get("latency_good", 50),
            latency_ok=data.get("latency_ok", 100),
            latency_poor=data.get("latency_poor", 150),
        )


class SettingsManager:
    """Manages application settings and budgets."""
    
    DEFAULT_SETTINGS_FILE = "settings.json"
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.settings_file = data_dir / self.DEFAULT_SETTINGS_FILE
        self._lock = threading.Lock()
        self._settings: AppSettings = AppSettings()
        self._load()
    
    def _load(self) -> None:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    data = json.load(f)
                    self._settings = AppSettings.from_dict(data)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load settings: {e}")
                self._settings = AppSettings()
        else:
            self._settings = AppSettings()
    
    def _save(self) -> None:
        """Save settings to file."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings.to_dict(), f, indent=2)
        except IOError as e:
            print(f"Error saving settings: {e}")
    
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
            key: ConnectionBudget.from_dict(data)
            for key, data in self._settings.budgets.items()
        }
    
    def check_budget_status(self, connection_key: str, 
                           current_usage: int, period_usage: int) -> dict:
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
                "remaining_bytes": 0
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
            "period": budget.period
        }


def get_settings_manager(data_dir: Optional[Path] = None) -> SettingsManager:
    """Get or create settings manager singleton."""
    if data_dir is None:
        data_dir = Path.home() / ".network-monitor"
    return SettingsManager(data_dir)
