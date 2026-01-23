"""JSON-based data persistence for network statistics."""
import json
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import INTERVALS, STORAGE, get_logger
from config.exceptions import StorageError

logger = get_logger(__name__)


@dataclass
class ConnectionStats:
    """Statistics for a single connection."""
    bytes_sent: int = 0
    bytes_recv: int = 0
    peak_upload: float = 0
    peak_download: float = 0
    issues: List[dict] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []

    def to_dict(self) -> dict:
        return {
            "bytes_sent": self.bytes_sent,
            "bytes_recv": self.bytes_recv,
            "peak_upload": self.peak_upload,
            "peak_download": self.peak_download,
            "issues": self.issues
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ConnectionStats':
        return cls(
            bytes_sent=data.get("bytes_sent", 0),
            bytes_recv=data.get("bytes_recv", 0),
            peak_upload=data.get("peak_upload", 0),
            peak_download=data.get("peak_download", 0),
            issues=data.get("issues", [])
        )


class JsonStore:
    """Handles persistence of network statistics to JSON file."""

    DEFAULT_DATA_DIR = Path.home() / STORAGE.DATA_DIR_NAME
    DEFAULT_DATA_FILE = STORAGE.STATS_FILE

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or self.DEFAULT_DATA_DIR
        self.data_file = self.data_dir / self.DEFAULT_DATA_FILE
        self._lock = threading.Lock()
        self._data: Dict[str, Dict[str, Any]] = {}
        self._dirty = False  # Track if data needs saving
        self._last_save_time: float = 0  # Last save timestamp
        self._save_interval: float = INTERVALS.SAVE_INTERVAL_SECONDS
        self._ensure_data_dir()
        self._load()
        logger.info(f"JsonStore initialized at {self.data_file}")

    def _ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Load data from JSON file."""
        if self.data_file.exists():
            try:
                with open(self.data_file) as f:
                    self._data = json.load(f)
                logger.debug(f"Loaded {len(self._data)} days of data")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not load data file: {e}")
                self._data = {}
        else:
            self._data = {}
            logger.debug("No existing data file, starting fresh")

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
            logger.debug("Data saved successfully")
        except OSError as e:
            logger.error(f"Error saving data: {e}")
            raise StorageError(f"Failed to save data: {e}", {"path": str(self.data_file)})

    def flush(self) -> None:
        """Force save any pending changes. Call on application shutdown."""
        with self._lock:
            self._save(force=True)

    def _get_today_key(self) -> str:
        """Get today's date as a key."""
        return date.today().isoformat()

    def _ensure_today_exists(self) -> str:
        """Ensure today's entry exists and return the key."""
        today = self._get_today_key()
        if today not in self._data:
            self._data[today] = {}
        return today

    def update_stats(self, connection_key: str, bytes_sent: int, bytes_recv: int,
                     peak_upload: float = 0, peak_download: float = 0) -> None:
        """Update statistics for a connection by ADDING to existing values.
        
        Args:
            connection_key: Connection identifier (e.g., SSID or interface name)
            bytes_sent: Bytes sent since last update (delta, not total)
            bytes_recv: Bytes received since last update (delta, not total)
            peak_upload: Peak upload speed in bytes/sec
            peak_download: Peak download speed in bytes/sec
        """
        with self._lock:
            today = self._ensure_today_exists()

            if connection_key not in self._data[today]:
                self._data[today][connection_key] = ConnectionStats().to_dict()

            stats = self._data[today][connection_key]
            # Add to existing values (accumulate deltas, don't replace)
            stats["bytes_sent"] = stats.get("bytes_sent", 0) + bytes_sent
            stats["bytes_recv"] = stats.get("bytes_recv", 0) + bytes_recv

            # Update peaks if higher
            if peak_upload > stats.get("peak_upload", 0):
                stats["peak_upload"] = peak_upload
            if peak_download > stats.get("peak_download", 0):
                stats["peak_download"] = peak_download

            self._dirty = True
            self._save()  # Will only actually save if interval passed

    def add_issue(self, connection_key: str, issue: dict) -> None:
        """Add an issue to the connection's log."""
        with self._lock:
            today = self._ensure_today_exists()

            if connection_key not in self._data[today]:
                self._data[today][connection_key] = ConnectionStats().to_dict()

            self._data[today][connection_key]["issues"].append(issue)
            self._dirty = True
            self._save()  # Will only actually save if interval passed

    def get_today_stats(self, connection_key: str) -> Optional[ConnectionStats]:
        """Get today's stats for a connection."""
        today = self._get_today_key()
        if today in self._data and connection_key in self._data[today]:
            return ConnectionStats.from_dict(self._data[today][connection_key])
        return None

    def get_today_all_connections(self) -> Dict[str, ConnectionStats]:
        """Get today's stats for all connections."""
        today = self._get_today_key()
        if today not in self._data:
            return {}

        return {
            key: ConnectionStats.from_dict(data)
            for key, data in self._data[today].items()
        }

    def get_today_totals(self) -> tuple:
        """Get today's total bytes sent and received across all connections."""
        connections = self.get_today_all_connections()
        total_sent = sum(c.bytes_sent for c in connections.values())
        total_recv = sum(c.bytes_recv for c in connections.values())
        return total_sent, total_recv

    def get_today_issues(self) -> List[dict]:
        """Get all issues logged today across all connections."""
        today = self._get_today_key()
        if today not in self._data:
            return []

        all_issues = []
        for conn_data in self._data[today].values():
            all_issues.extend(conn_data.get("issues", []))

        # Sort by timestamp
        all_issues.sort(key=lambda x: x.get("timestamp", ""))
        return all_issues

    def get_history(self, days: int = 7) -> Dict[str, Dict[str, ConnectionStats]]:
        """Get statistics history for the past N days."""
        from datetime import timedelta

        result = {}
        for i in range(days):
            day = (date.today() - timedelta(days=i)).isoformat()
            if day in self._data:
                result[day] = {
                    key: ConnectionStats.from_dict(data)
                    for key, data in self._data[day].items()
                }
        return result

    def reset_today(self) -> None:
        """Reset today's statistics."""
        with self._lock:
            today = self._get_today_key()
            if today in self._data:
                del self._data[today]
            self._save(force=True)  # Force save for user-initiated action

    def cleanup_old_data(self, keep_days: int = None) -> None:
        """Remove data older than specified days."""
        from datetime import timedelta

        keep_days = keep_days or STORAGE.RETENTION_DAYS

        with self._lock:
            cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
            keys_to_remove = [key for key in self._data.keys() if key < cutoff]

            for key in keys_to_remove:
                del self._data[key]

            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} old data entries")
                self._save(force=True)  # Force save for cleanup action

    def get_data_file_path(self) -> str:
        """Get the path to the data file."""
        return str(self.data_file)

    def get_daily_totals(self, days: int = 7) -> List[Dict]:
        """Get daily totals for the past N days.
        
        Returns list of {date, sent, recv, connections} dicts.
        """
        from datetime import timedelta

        result = []
        for i in range(days):
            day = (date.today() - timedelta(days=i)).isoformat()
            if day in self._data:
                day_data = self._data[day]
                total_sent = sum(c.get("bytes_sent", 0) for c in day_data.values())
                total_recv = sum(c.get("bytes_recv", 0) for c in day_data.values())
                connections = list(day_data.keys())
                result.append({
                    "date": day,
                    "sent": total_sent,
                    "recv": total_recv,
                    "connections": connections
                })
            else:
                result.append({
                    "date": day,
                    "sent": 0,
                    "recv": 0,
                    "connections": []
                })
        return result

    def get_weekly_totals(self) -> Dict:
        """Get totals for the past 7 days.
        
        Returns {sent, recv, by_connection: {conn: {sent, recv}}}
        """
        from datetime import timedelta

        total_sent = 0
        total_recv = 0
        by_connection: Dict[str, Dict[str, int]] = {}

        for i in range(7):
            day = (date.today() - timedelta(days=i)).isoformat()
            if day in self._data:
                for conn_key, stats in self._data[day].items():
                    sent = stats.get("bytes_sent", 0)
                    recv = stats.get("bytes_recv", 0)
                    total_sent += sent
                    total_recv += recv

                    if conn_key not in by_connection:
                        by_connection[conn_key] = {"sent": 0, "recv": 0}
                    by_connection[conn_key]["sent"] += sent
                    by_connection[conn_key]["recv"] += recv

        return {
            "sent": total_sent,
            "recv": total_recv,
            "by_connection": by_connection
        }

    def get_monthly_totals(self) -> Dict:
        """Get totals for the past 30 days.
        
        Returns {sent, recv, by_connection: {conn: {sent, recv}}}
        """
        from datetime import timedelta

        total_sent = 0
        total_recv = 0
        by_connection: Dict[str, Dict[str, int]] = {}

        for i in range(30):
            day = (date.today() - timedelta(days=i)).isoformat()
            if day in self._data:
                for conn_key, stats in self._data[day].items():
                    sent = stats.get("bytes_sent", 0)
                    recv = stats.get("bytes_recv", 0)
                    total_sent += sent
                    total_recv += recv

                    if conn_key not in by_connection:
                        by_connection[conn_key] = {"sent": 0, "recv": 0}
                    by_connection[conn_key]["sent"] += sent
                    by_connection[conn_key]["recv"] += recv

        return {
            "sent": total_sent,
            "recv": total_recv,
            "by_connection": by_connection
        }

    def get_connection_history(self, connection_key: str, days: int = 30) -> List[Dict]:
        """Get daily stats for a specific connection.
        
        Returns list of {date, sent, recv} dicts.
        """
        from datetime import timedelta

        result = []
        for i in range(days):
            day = (date.today() - timedelta(days=i)).isoformat()
            if day in self._data and connection_key in self._data[day]:
                stats = self._data[day][connection_key]
                result.append({
                    "date": day,
                    "sent": stats.get("bytes_sent", 0),
                    "recv": stats.get("bytes_recv", 0)
                })
            else:
                result.append({
                    "date": day,
                    "sent": 0,
                    "recv": 0
                })
        return result
