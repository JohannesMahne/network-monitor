"""SQLite-based data persistence for network statistics.

This module provides SQLite storage for network monitoring data,
offering better query performance for historical data compared to JSON.

Features:
- Efficient storage and retrieval of traffic statistics
- Device tracking with vendor information
- Issue/event logging with full-text search capability
- Automatic migration from JSON storage
- Data cleanup and retention policies
- Backup and restore functionality
"""
import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import INTERVALS, STORAGE, get_logger
from config.exceptions import StorageError

logger = get_logger(__name__)


# Schema version for migrations
SCHEMA_VERSION = 1


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


class SQLiteStore:
    """Handles persistence of network statistics to SQLite database.
    
    This class provides the same interface as JsonStore for compatibility,
    but uses SQLite for storage, offering better performance for queries
    and historical data analysis.
    """

    DEFAULT_DATA_DIR = Path.home() / STORAGE.DATA_DIR_NAME
    DEFAULT_DB_FILE = "network_monitor.db"

    # SQL schema for database tables
    SCHEMA = """
    -- Traffic statistics by date and connection
    CREATE TABLE IF NOT EXISTS traffic_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        connection_key TEXT NOT NULL,
        bytes_sent INTEGER DEFAULT 0,
        bytes_recv INTEGER DEFAULT 0,
        peak_upload REAL DEFAULT 0,
        peak_download REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, connection_key)
    );
    
    -- Network issues/events log
    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        connection_key TEXT,
        timestamp TEXT NOT NULL,
        issue_type TEXT NOT NULL,
        description TEXT,
        details TEXT,  -- JSON blob for additional details
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- Known network devices
    CREATE TABLE IF NOT EXISTS devices (
        mac_address TEXT PRIMARY KEY,
        custom_name TEXT,
        hostname TEXT,
        vendor TEXT,
        device_type TEXT,
        model_hint TEXT,
        os_hint TEXT,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP,
        last_ip TEXT
    );
    
    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_info (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    
    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_traffic_date ON traffic_stats(date);
    CREATE INDEX IF NOT EXISTS idx_traffic_connection ON traffic_stats(connection_key);
    CREATE INDEX IF NOT EXISTS idx_issues_date ON issues(date);
    CREATE INDEX IF NOT EXISTS idx_issues_timestamp ON issues(timestamp);
    CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen);
    """

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize SQLite store.
        
        Args:
            data_dir: Directory for database file. Defaults to ~/.network-monitor/
        """
        self.data_dir = data_dir or self.DEFAULT_DATA_DIR
        self.db_path = self.data_dir / self.DEFAULT_DB_FILE
        self._lock = threading.Lock()
        self._dirty = False
        self._last_save_time: float = 0
        self._save_interval: float = INTERVALS.SAVE_INTERVAL_SECONDS
        self._last_cleanup_check: Optional[date] = None

        self._ensure_data_dir()
        self._init_db()
        self._check_migration()
        self._check_cleanup()

        logger.info(f"SQLiteStore initialized at {self.db_path}")

    def _ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self):
        """Context manager for database connections.
        
        Uses WAL mode for better concurrency and enables foreign keys.
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None  # Autocommit mode, we handle transactions manually
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            with self._connection() as conn:
                conn.executescript(self.SCHEMA)
                # Set schema version if not exists
                conn.execute(
                    "INSERT OR IGNORE INTO schema_info (key, value) VALUES (?, ?)",
                    ("version", str(SCHEMA_VERSION))
                )
            logger.debug("Database schema initialized")
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize database: {e}")
            raise StorageError(f"Database initialization failed: {e}")

    def _check_migration(self) -> None:
        """Check if migration from JSON is needed and perform it."""
        json_file = self.data_dir / STORAGE.STATS_FILE

        if json_file.exists():
            # Check if we have any data in SQLite
            with self._connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM traffic_stats")
                count = cursor.fetchone()[0]

            if count == 0:
                logger.info("Found existing JSON data, migrating to SQLite...")
                self._migrate_from_json(json_file)

    def _migrate_from_json(self, json_file: Path) -> None:
        """Migrate data from JSON file to SQLite.
        
        Args:
            json_file: Path to the existing JSON stats file
        """
        try:
            with open(json_file) as f:
                json_data = json.load(f)

            migrated_records = 0
            migrated_issues = 0

            with self._connection() as conn:
                conn.execute("BEGIN TRANSACTION")
                try:
                    for date_key, day_data in json_data.items():
                        for conn_key, stats in day_data.items():
                            # Insert traffic stats
                            conn.execute("""
                                INSERT OR REPLACE INTO traffic_stats 
                                (date, connection_key, bytes_sent, bytes_recv, peak_upload, peak_download)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                date_key,
                                conn_key,
                                stats.get("bytes_sent", 0),
                                stats.get("bytes_recv", 0),
                                stats.get("peak_upload", 0),
                                stats.get("peak_download", 0)
                            ))
                            migrated_records += 1

                            # Migrate issues if present
                            for issue in stats.get("issues", []):
                                conn.execute("""
                                    INSERT INTO issues 
                                    (date, connection_key, timestamp, issue_type, description, details)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                """, (
                                    date_key,
                                    conn_key,
                                    issue.get("timestamp", ""),
                                    issue.get("issue_type", "unknown"),
                                    issue.get("description", ""),
                                    json.dumps(issue.get("details", {}))
                                ))
                                migrated_issues += 1

                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            # Rename old JSON file to backup
            backup_file = json_file.with_suffix('.json.bak')
            json_file.rename(backup_file)

            logger.info(
                f"Migration complete: {migrated_records} traffic records, "
                f"{migrated_issues} issues. Old data backed up to {backup_file}"
            )
        except Exception as e:
            logger.error(f"Migration from JSON failed: {e}")
            raise StorageError(f"Failed to migrate from JSON: {e}")

    def _check_cleanup(self) -> None:
        """Check if automatic cleanup should run (once per day)."""
        today = date.today()

        if self._last_cleanup_check != today:
            self._last_cleanup_check = today
            self.cleanup_old_data()

    def _get_today_key(self) -> str:
        """Get today's date as a key."""
        return date.today().isoformat()

    # === Core Statistics Methods ===

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
            today = self._get_today_key()

            try:
                with self._connection() as conn:
                    # Use UPSERT to ADD to existing values (not replace)
                    # This ensures data persists across app restarts
                    conn.execute("""
                        INSERT INTO traffic_stats 
                        (date, connection_key, bytes_sent, bytes_recv, peak_upload, peak_download, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(date, connection_key) DO UPDATE SET
                            bytes_sent = bytes_sent + excluded.bytes_sent,
                            bytes_recv = bytes_recv + excluded.bytes_recv,
                            peak_upload = MAX(peak_upload, excluded.peak_upload),
                            peak_download = MAX(peak_download, excluded.peak_download),
                            updated_at = CURRENT_TIMESTAMP
                    """, (today, connection_key, bytes_sent, bytes_recv, peak_upload, peak_download))
            except sqlite3.Error as e:
                logger.error(f"Failed to update stats: {e}")
                raise StorageError(f"Failed to update statistics: {e}")

    def add_issue(self, connection_key: str, issue: dict) -> None:
        """Add an issue to the log.
        
        Args:
            connection_key: Connection identifier
            issue: Issue dictionary with timestamp, issue_type, description, details
        """
        with self._lock:
            today = self._get_today_key()

            try:
                with self._connection() as conn:
                    conn.execute("""
                        INSERT INTO issues 
                        (date, connection_key, timestamp, issue_type, description, details)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        today,
                        connection_key,
                        issue.get("timestamp", datetime.now().isoformat()),
                        issue.get("issue_type", "unknown"),
                        issue.get("description", ""),
                        json.dumps(issue.get("details", {}))
                    ))
            except sqlite3.Error as e:
                logger.error(f"Failed to add issue: {e}")
                raise StorageError(f"Failed to add issue: {e}")

    def get_today_stats(self, connection_key: str) -> Optional[ConnectionStats]:
        """Get today's stats for a connection."""
        today = self._get_today_key()

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT bytes_sent, bytes_recv, peak_upload, peak_download
                    FROM traffic_stats
                    WHERE date = ? AND connection_key = ?
                """, (today, connection_key))
                row = cursor.fetchone()

                if row:
                    # Get issues for this connection today
                    issues_cursor = conn.execute("""
                        SELECT timestamp, issue_type, description, details
                        FROM issues
                        WHERE date = ? AND connection_key = ?
                        ORDER BY timestamp
                    """, (today, connection_key))

                    issues = [
                        {
                            "timestamp": r["timestamp"],
                            "issue_type": r["issue_type"],
                            "description": r["description"],
                            "details": json.loads(r["details"]) if r["details"] else {}
                        }
                        for r in issues_cursor
                    ]

                    return ConnectionStats(
                        bytes_sent=row["bytes_sent"],
                        bytes_recv=row["bytes_recv"],
                        peak_upload=row["peak_upload"],
                        peak_download=row["peak_download"],
                        issues=issues
                    )
                return None
        except sqlite3.Error as e:
            logger.error(f"Failed to get today's stats: {e}")
            return None

    def get_today_all_connections(self) -> Dict[str, ConnectionStats]:
        """Get today's stats for all connections."""
        today = self._get_today_key()
        result = {}

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT connection_key, bytes_sent, bytes_recv, peak_upload, peak_download
                    FROM traffic_stats
                    WHERE date = ?
                """, (today,))

                for row in cursor:
                    # Get issues for this connection
                    issues_cursor = conn.execute("""
                        SELECT timestamp, issue_type, description, details
                        FROM issues
                        WHERE date = ? AND connection_key = ?
                        ORDER BY timestamp
                    """, (today, row["connection_key"]))

                    issues = [
                        {
                            "timestamp": r["timestamp"],
                            "issue_type": r["issue_type"],
                            "description": r["description"],
                            "details": json.loads(r["details"]) if r["details"] else {}
                        }
                        for r in issues_cursor
                    ]

                    result[row["connection_key"]] = ConnectionStats(
                        bytes_sent=row["bytes_sent"],
                        bytes_recv=row["bytes_recv"],
                        peak_upload=row["peak_upload"],
                        peak_download=row["peak_download"],
                        issues=issues
                    )
        except sqlite3.Error as e:
            logger.error(f"Failed to get all connections: {e}")

        return result

    def get_today_totals(self) -> Tuple[int, int]:
        """Get today's total bytes sent and received across all connections."""
        today = self._get_today_key()

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT COALESCE(SUM(bytes_sent), 0) as total_sent,
                           COALESCE(SUM(bytes_recv), 0) as total_recv
                    FROM traffic_stats
                    WHERE date = ?
                """, (today,))
                row = cursor.fetchone()
                return (row["total_sent"], row["total_recv"])
        except sqlite3.Error as e:
            logger.error(f"Failed to get today's totals: {e}")
            return (0, 0)

    def get_today_issues(self) -> List[dict]:
        """Get all issues logged today across all connections."""
        today = self._get_today_key()

        try:
            with self._connection() as conn:
                cursor = conn.execute("""
                    SELECT timestamp, issue_type, description, details, connection_key
                    FROM issues
                    WHERE date = ?
                    ORDER BY timestamp
                """, (today,))

                return [
                    {
                        "timestamp": row["timestamp"],
                        "issue_type": row["issue_type"],
                        "description": row["description"],
                        "details": json.loads(row["details"]) if row["details"] else {},
                        "connection_key": row["connection_key"]
                    }
                    for row in cursor
                ]
        except sqlite3.Error as e:
            logger.error(f"Failed to get today's issues: {e}")
            return []

    # === History Methods ===

    def get_history(self, days: int = 7) -> Dict[str, Dict[str, ConnectionStats]]:
        """Get statistics history for the past N days."""
        result = {}

        try:
            with self._connection() as conn:
                # Get all dates in range
                cursor = conn.execute("""
                    SELECT DISTINCT date FROM traffic_stats
                    WHERE date >= date('now', ?)
                    ORDER BY date DESC
                """, (f'-{days} days',))

                dates = [row["date"] for row in cursor]

                for day in dates:
                    # Get stats for this day
                    stats_cursor = conn.execute("""
                        SELECT connection_key, bytes_sent, bytes_recv, peak_upload, peak_download
                        FROM traffic_stats
                        WHERE date = ?
                    """, (day,))

                    day_data = {}
                    for row in stats_cursor:
                        # Get issues
                        issues_cursor = conn.execute("""
                            SELECT timestamp, issue_type, description, details
                            FROM issues
                            WHERE date = ? AND connection_key = ?
                        """, (day, row["connection_key"]))

                        issues = [
                            {
                                "timestamp": r["timestamp"],
                                "issue_type": r["issue_type"],
                                "description": r["description"],
                                "details": json.loads(r["details"]) if r["details"] else {}
                            }
                            for r in issues_cursor
                        ]

                        day_data[row["connection_key"]] = ConnectionStats(
                            bytes_sent=row["bytes_sent"],
                            bytes_recv=row["bytes_recv"],
                            peak_upload=row["peak_upload"],
                            peak_download=row["peak_download"],
                            issues=issues
                        )

                    result[day] = day_data
        except sqlite3.Error as e:
            logger.error(f"Failed to get history: {e}")

        return result

    def get_daily_totals(self, days: int = 7) -> List[Dict]:
        """Get daily totals for the past N days.
        
        Returns list of {date, sent, recv, connections} dicts.
        """
        result = []

        try:
            with self._connection() as conn:
                for i in range(days):
                    day = (date.today() - timedelta(days=i)).isoformat()

                    cursor = conn.execute("""
                        SELECT COALESCE(SUM(bytes_sent), 0) as total_sent,
                               COALESCE(SUM(bytes_recv), 0) as total_recv,
                               GROUP_CONCAT(connection_key) as connections
                        FROM traffic_stats
                        WHERE date = ?
                    """, (day,))
                    row = cursor.fetchone()

                    connections = row["connections"].split(",") if row["connections"] else []

                    result.append({
                        "date": day,
                        "sent": row["total_sent"],
                        "recv": row["total_recv"],
                        "connections": connections
                    })
        except sqlite3.Error as e:
            logger.error(f"Failed to get daily totals: {e}")
            # Return empty results for requested days
            for i in range(days):
                day = (date.today() - timedelta(days=i)).isoformat()
                result.append({"date": day, "sent": 0, "recv": 0, "connections": []})

        return result

    def get_weekly_totals(self) -> Dict:
        """Get totals for the past 7 days.
        
        Returns {sent, recv, by_connection: {conn: {sent, recv}}}
        """
        return self._get_period_totals(7)

    def get_monthly_totals(self) -> Dict:
        """Get totals for the past 30 days.
        
        Returns {sent, recv, by_connection: {conn: {sent, recv}}}
        """
        return self._get_period_totals(30)

    def _get_period_totals(self, days: int) -> Dict:
        """Get totals for a period.
        
        Args:
            days: Number of days to include
            
        Returns:
            Dict with sent, recv, and by_connection breakdown
        """
        try:
            with self._connection() as conn:
                # Get overall totals
                cursor = conn.execute("""
                    SELECT COALESCE(SUM(bytes_sent), 0) as total_sent,
                           COALESCE(SUM(bytes_recv), 0) as total_recv
                    FROM traffic_stats
                    WHERE date >= date('now', ?)
                """, (f'-{days} days',))
                totals = cursor.fetchone()

                # Get per-connection breakdown
                by_connection = {}
                cursor = conn.execute("""
                    SELECT connection_key,
                           SUM(bytes_sent) as sent,
                           SUM(bytes_recv) as recv
                    FROM traffic_stats
                    WHERE date >= date('now', ?)
                    GROUP BY connection_key
                """, (f'-{days} days',))

                for row in cursor:
                    by_connection[row["connection_key"]] = {
                        "sent": row["sent"],
                        "recv": row["recv"]
                    }

                return {
                    "sent": totals["total_sent"],
                    "recv": totals["total_recv"],
                    "by_connection": by_connection
                }
        except sqlite3.Error as e:
            logger.error(f"Failed to get period totals: {e}")
            return {"sent": 0, "recv": 0, "by_connection": {}}

    def get_connection_history(self, connection_key: str, days: int = 30) -> List[Dict]:
        """Get daily stats for a specific connection.
        
        Returns list of {date, sent, recv} dicts.
        """
        result = []

        try:
            with self._connection() as conn:
                for i in range(days):
                    day = (date.today() - timedelta(days=i)).isoformat()

                    cursor = conn.execute("""
                        SELECT COALESCE(bytes_sent, 0) as sent,
                               COALESCE(bytes_recv, 0) as recv
                        FROM traffic_stats
                        WHERE date = ? AND connection_key = ?
                    """, (day, connection_key))
                    row = cursor.fetchone()

                    if row:
                        result.append({
                            "date": day,
                            "sent": row["sent"],
                            "recv": row["recv"]
                        })
                    else:
                        result.append({
                            "date": day,
                            "sent": 0,
                            "recv": 0
                        })
        except sqlite3.Error as e:
            logger.error(f"Failed to get connection history: {e}")
            for i in range(days):
                day = (date.today() - timedelta(days=i)).isoformat()
                result.append({"date": day, "sent": 0, "recv": 0})

        return result

    # === Data Management Methods ===

    def reset_today(self) -> None:
        """Reset today's statistics."""
        with self._lock:
            today = self._get_today_key()

            try:
                with self._connection() as conn:
                    conn.execute("DELETE FROM traffic_stats WHERE date = ?", (today,))
                    conn.execute("DELETE FROM issues WHERE date = ?", (today,))
                logger.info("Today's statistics reset")
            except sqlite3.Error as e:
                logger.error(f"Failed to reset today's stats: {e}")
                raise StorageError(f"Failed to reset statistics: {e}")

    def cleanup_old_data(self, keep_days: int = None) -> int:
        """Remove data older than specified days.
        
        Args:
            keep_days: Number of days to retain. Defaults to STORAGE.RETENTION_DAYS
            
        Returns:
            Number of records deleted
        """
        keep_days = keep_days or STORAGE.RETENTION_DAYS

        with self._lock:
            cutoff = (date.today() - timedelta(days=keep_days)).isoformat()

            try:
                with self._connection() as conn:
                    # Delete old traffic stats
                    cursor = conn.execute(
                        "DELETE FROM traffic_stats WHERE date < ?", (cutoff,)
                    )
                    stats_deleted = cursor.rowcount

                    # Delete old issues
                    cursor = conn.execute(
                        "DELETE FROM issues WHERE date < ?", (cutoff,)
                    )
                    issues_deleted = cursor.rowcount

                    total_deleted = stats_deleted + issues_deleted

                    if total_deleted > 0:
                        logger.info(
                            f"Cleanup: removed {stats_deleted} traffic records, "
                            f"{issues_deleted} issues older than {keep_days} days"
                        )

                        # Optimize database after large deletions
                        conn.execute("VACUUM")

                    return total_deleted
            except sqlite3.Error as e:
                logger.error(f"Cleanup failed: {e}")
                return 0

    def flush(self) -> None:
        """Ensure all data is written to disk.
        
        SQLite with WAL mode generally handles this automatically,
        but this provides explicit synchronization.
        """
        try:
            with self._connection() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.debug("Database flushed")
        except sqlite3.Error as e:
            logger.error(f"Flush failed: {e}")

    # === Backup/Restore Methods ===

    def backup(self, backup_path: Optional[Path] = None) -> Path:
        """Create a backup of the database.
        
        Args:
            backup_path: Optional custom backup path. If not provided,
                        creates backup in data_dir with timestamp.
                        
        Returns:
            Path to the backup file
        """
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.data_dir / f"backup_{timestamp}.db"

        backup_path = Path(backup_path)

        try:
            with self._lock:
                # Ensure WAL is checkpointed before backup
                with self._connection() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

                # Copy the database file
                shutil.copy2(self.db_path, backup_path)

            logger.info(f"Database backed up to {backup_path}")
            return backup_path
        except (OSError, sqlite3.Error) as e:
            logger.error(f"Backup failed: {e}")
            raise StorageError(f"Failed to create backup: {e}")

    def restore(self, backup_path: Path) -> None:
        """Restore database from a backup.
        
        Args:
            backup_path: Path to the backup file to restore
            
        Warning: This will replace all current data!
        """
        backup_path = Path(backup_path)

        if not backup_path.exists():
            raise StorageError(f"Backup file not found: {backup_path}")

        try:
            with self._lock:
                # Verify the backup is a valid SQLite database
                test_conn = sqlite3.connect(backup_path)
                test_conn.execute("SELECT 1 FROM traffic_stats LIMIT 1")
                test_conn.close()

                # Create a backup of current database
                current_backup = self.db_path.with_suffix('.db.pre-restore')
                if self.db_path.exists():
                    shutil.copy2(self.db_path, current_backup)

                # Remove WAL and SHM files if they exist
                wal_path = Path(str(self.db_path) + "-wal")
                shm_path = Path(str(self.db_path) + "-shm")
                if wal_path.exists():
                    wal_path.unlink()
                if shm_path.exists():
                    shm_path.unlink()

                # Copy backup to database path
                shutil.copy2(backup_path, self.db_path)

            logger.info(f"Database restored from {backup_path}")
        except sqlite3.Error as e:
            logger.error(f"Restore failed - invalid backup: {e}")
            raise StorageError(f"Invalid backup file: {e}")
        except OSError as e:
            logger.error(f"Restore failed: {e}")
            raise StorageError(f"Failed to restore backup: {e}")

    def export_json(self, output_path: Optional[Path] = None, days: int = 90) -> Path:
        """Export database to JSON format.
        
        Args:
            output_path: Optional custom output path
            days: Number of days of history to export
            
        Returns:
            Path to the exported JSON file
        """
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"export_{timestamp}.json"

        output_path = Path(output_path)

        try:
            export_data = {
                "export_timestamp": datetime.now().isoformat(),
                "schema_version": SCHEMA_VERSION,
                "traffic_stats": {},
                "issues": [],
                "devices": []
            }

            with self._connection() as conn:
                # Export traffic stats
                cursor = conn.execute("""
                    SELECT date, connection_key, bytes_sent, bytes_recv, 
                           peak_upload, peak_download
                    FROM traffic_stats
                    WHERE date >= date('now', ?)
                    ORDER BY date, connection_key
                """, (f'-{days} days',))

                for row in cursor:
                    date_key = row["date"]
                    if date_key not in export_data["traffic_stats"]:
                        export_data["traffic_stats"][date_key] = {}

                    export_data["traffic_stats"][date_key][row["connection_key"]] = {
                        "bytes_sent": row["bytes_sent"],
                        "bytes_recv": row["bytes_recv"],
                        "peak_upload": row["peak_upload"],
                        "peak_download": row["peak_download"]
                    }

                # Export issues
                cursor = conn.execute("""
                    SELECT date, connection_key, timestamp, issue_type, 
                           description, details
                    FROM issues
                    WHERE date >= date('now', ?)
                    ORDER BY timestamp
                """, (f'-{days} days',))

                for row in cursor:
                    export_data["issues"].append({
                        "date": row["date"],
                        "connection_key": row["connection_key"],
                        "timestamp": row["timestamp"],
                        "issue_type": row["issue_type"],
                        "description": row["description"],
                        "details": json.loads(row["details"]) if row["details"] else {}
                    })

                # Export devices
                cursor = conn.execute("""
                    SELECT mac_address, custom_name, hostname, vendor, 
                           device_type, model_hint, os_hint, first_seen, 
                           last_seen, last_ip
                    FROM devices
                """)

                for row in cursor:
                    export_data["devices"].append(dict(row))

            with open(output_path, 'w') as f:
                json.dump(export_data, f, indent=2)

            logger.info(f"Data exported to {output_path}")
            return output_path
        except (OSError, sqlite3.Error) as e:
            logger.error(f"Export failed: {e}")
            raise StorageError(f"Failed to export data: {e}")

    def import_json(self, input_path: Path) -> int:
        """Import data from JSON file.
        
        Args:
            input_path: Path to JSON file to import
            
        Returns:
            Number of records imported
        """
        input_path = Path(input_path)

        if not input_path.exists():
            raise StorageError(f"Import file not found: {input_path}")

        try:
            with open(input_path) as f:
                import_data = json.load(f)

            imported = 0

            with self._lock, self._connection() as conn:
                conn.execute("BEGIN TRANSACTION")

                try:
                    # Import traffic stats
                    for date_key, day_data in import_data.get("traffic_stats", {}).items():
                        for conn_key, stats in day_data.items():
                            conn.execute("""
                                    INSERT OR REPLACE INTO traffic_stats
                                    (date, connection_key, bytes_sent, bytes_recv, 
                                     peak_upload, peak_download)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                """, (
                                date_key, conn_key,
                                stats.get("bytes_sent", 0),
                                stats.get("bytes_recv", 0),
                                stats.get("peak_upload", 0),
                                stats.get("peak_download", 0)
                            ))
                            imported += 1

                    # Import issues
                    for issue in import_data.get("issues", []):
                        conn.execute("""
                                INSERT INTO issues
                                (date, connection_key, timestamp, issue_type, 
                                 description, details)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                            issue.get("date", ""),
                            issue.get("connection_key", ""),
                            issue.get("timestamp", ""),
                            issue.get("issue_type", "unknown"),
                            issue.get("description", ""),
                            json.dumps(issue.get("details", {}))
                        ))
                        imported += 1

                    # Import devices
                    for device in import_data.get("devices", []):
                        conn.execute("""
                                INSERT OR REPLACE INTO devices
                                (mac_address, custom_name, hostname, vendor,
                                 device_type, model_hint, os_hint, first_seen,
                                 last_seen, last_ip)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                            device.get("mac_address"),
                            device.get("custom_name"),
                            device.get("hostname"),
                            device.get("vendor"),
                            device.get("device_type"),
                            device.get("model_hint"),
                            device.get("os_hint"),
                            device.get("first_seen"),
                            device.get("last_seen"),
                            device.get("last_ip")
                        ))
                        imported += 1

                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            logger.info(f"Imported {imported} records from {input_path}")
            return imported
        except json.JSONDecodeError as e:
            logger.error(f"Import failed - invalid JSON: {e}")
            raise StorageError(f"Invalid JSON file: {e}")
        except (OSError, sqlite3.Error) as e:
            logger.error(f"Import failed: {e}")
            raise StorageError(f"Failed to import data: {e}")

    # === Device Management Methods ===

    # Whitelist of valid device table columns to prevent SQL injection
    _DEVICE_COLUMNS = frozenset({
        'custom_name', 'hostname', 'vendor', 'device_type',
        'model_hint', 'os_hint', 'first_seen', 'last_seen', 'last_ip'
    })

    def save_device(self, mac_address: str, **kwargs) -> None:
        """Save or update a device record.
        
        Args:
            mac_address: Device MAC address (primary key)
            **kwargs: Device attributes to update (must be valid column names)
        
        Raises:
            ValueError: If an invalid column name is provided
        """
        # Validate column names against whitelist to prevent SQL injection
        invalid_cols = set(kwargs.keys()) - self._DEVICE_COLUMNS
        if invalid_cols:
            logger.warning(f"Invalid device columns ignored: {invalid_cols}")
            kwargs = {k: v for k, v in kwargs.items() if k in self._DEVICE_COLUMNS}

        with self._lock:
            try:
                with self._connection() as conn:
                    # Check if device exists
                    cursor = conn.execute(
                        "SELECT 1 FROM devices WHERE mac_address = ?",
                        (mac_address,)
                    )
                    exists = cursor.fetchone() is not None

                    if exists:
                        # Update existing device
                        updates = []
                        values = []
                        for key, value in kwargs.items():
                            if value is not None:
                                # Column names are validated above
                                updates.append(f"{key} = ?")  # nosec B608
                                values.append(value)

                        if updates:
                            values.append(mac_address)
                            conn.execute(
                                f"UPDATE devices SET {', '.join(updates)} WHERE mac_address = ?",  # nosec B608
                                values
                            )
                    else:
                        # Insert new device - column names validated above
                        columns = ["mac_address"] + list(kwargs.keys())
                        placeholders = ["?"] * len(columns)
                        values = [mac_address] + list(kwargs.values())

                        conn.execute(
                            f"INSERT INTO devices ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",  # nosec B608
                            values
                        )
            except sqlite3.Error as e:
                logger.error(f"Failed to save device: {e}")

    def get_device(self, mac_address: str) -> Optional[Dict]:
        """Get a device record by MAC address."""
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM devices WHERE mac_address = ?",
                    (mac_address,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to get device: {e}")
            return None

    def get_all_devices(self) -> List[Dict]:
        """Get all device records."""
        try:
            with self._connection() as conn:
                cursor = conn.execute("SELECT * FROM devices ORDER BY last_seen DESC")
                return [dict(row) for row in cursor]
        except sqlite3.Error as e:
            logger.error(f"Failed to get devices: {e}")
            return []

    # === Utility Methods ===

    def get_data_file_path(self) -> str:
        """Get the path to the database file."""
        return str(self.db_path)

    def get_database_stats(self) -> Dict:
        """Get statistics about the database.
        
        Returns:
            Dict with record counts, date range, and file size
        """
        try:
            with self._connection() as conn:
                # Count records
                stats_count = conn.execute(
                    "SELECT COUNT(*) FROM traffic_stats"
                ).fetchone()[0]
                issues_count = conn.execute(
                    "SELECT COUNT(*) FROM issues"
                ).fetchone()[0]
                devices_count = conn.execute(
                    "SELECT COUNT(*) FROM devices"
                ).fetchone()[0]

                # Get date range
                date_range = conn.execute("""
                    SELECT MIN(date) as oldest, MAX(date) as newest
                    FROM traffic_stats
                """).fetchone()

            # Get file size
            file_size = self.db_path.stat().st_size if self.db_path.exists() else 0

            return {
                "traffic_records": stats_count,
                "issues_count": issues_count,
                "devices_count": devices_count,
                "oldest_date": date_range["oldest"],
                "newest_date": date_range["newest"],
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2)
            }
        except sqlite3.Error as e:
            logger.error(f"Failed to get database stats: {e}")
            return {}
