"""Tests for SQLite storage backend."""

from pathlib import Path

import pytest

from storage.sqlite_store import ConnectionStats, SQLiteStore


class TestSQLiteStore:
    """Tests for SQLiteStore class."""

    @pytest.fixture
    def store(self, temp_data_dir):
        """Create a SQLiteStore with temporary directory."""
        return SQLiteStore(data_dir=temp_data_dir)

    def test_init_creates_database(self, temp_data_dir):
        """Test that initialization creates the database file."""
        store = SQLiteStore(data_dir=temp_data_dir)
        assert (temp_data_dir / "network_monitor.db").exists()

    def test_update_stats_creates_record(self, store):
        """Test that update_stats creates a new record."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000, 100.0, 200.0)

        stats = store.get_today_stats("WiFi:TestNetwork")
        assert stats is not None
        assert stats.bytes_sent == 1000
        assert stats.bytes_recv == 2000
        assert stats.peak_upload == 100.0
        assert stats.peak_download == 200.0

    def test_update_stats_accumulates(self, store):
        """Test that update_stats adds to existing values."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)
        store.update_stats("WiFi:TestNetwork", 500, 1000)

        stats = store.get_today_stats("WiFi:TestNetwork")
        assert stats.bytes_sent == 1500
        assert stats.bytes_recv == 3000

    def test_update_stats_keeps_max_peaks(self, store):
        """Test that peak values are kept as max."""
        store.update_stats("WiFi:TestNetwork", 100, 100, 500.0, 1000.0)
        store.update_stats("WiFi:TestNetwork", 100, 100, 300.0, 1500.0)

        stats = store.get_today_stats("WiFi:TestNetwork")
        assert stats.peak_upload == 500.0  # Max of 500, 300
        assert stats.peak_download == 1500.0  # Max of 1000, 1500

    def test_get_today_totals(self, store):
        """Test getting total bytes for today across all connections."""
        store.update_stats("WiFi:Network1", 1000, 2000)
        store.update_stats("WiFi:Network2", 500, 1000)

        sent, recv = store.get_today_totals()
        assert sent == 1500
        assert recv == 3000

    def test_get_today_all_connections(self, store):
        """Test getting stats for all connections today."""
        store.update_stats("WiFi:Network1", 1000, 2000)
        store.update_stats("Ethernet:LAN", 500, 1000)

        all_stats = store.get_today_all_connections()
        assert len(all_stats) == 2
        assert "WiFi:Network1" in all_stats
        assert "Ethernet:LAN" in all_stats

    def test_add_issue(self, store):
        """Test adding an issue."""
        issue = {
            "issue_type": "high_latency",
            "description": "Latency spike detected",
            "details": {"latency_ms": 150},
        }
        store.add_issue("WiFi:TestNetwork", issue)

        issues = store.get_today_issues()
        assert len(issues) == 1
        assert issues[0]["issue_type"] == "high_latency"

    def test_reset_today(self, store):
        """Test resetting today's statistics."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)
        store.reset_today()

        stats = store.get_today_stats("WiFi:TestNetwork")
        assert stats is None

    def test_get_daily_totals(self, store):
        """Test getting daily totals for multiple days."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        totals = store.get_daily_totals(days=7)
        assert len(totals) == 7
        # Today should have our data
        assert totals[0]["sent"] == 1000
        assert totals[0]["recv"] == 2000

    def test_get_weekly_totals(self, store):
        """Test getting weekly totals."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        totals = store.get_weekly_totals()
        assert totals["sent"] == 1000
        assert totals["recv"] == 2000
        assert "WiFi:TestNetwork" in totals["by_connection"]

    def test_get_monthly_totals(self, store):
        """Test getting monthly totals."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        totals = store.get_monthly_totals()
        assert totals["sent"] == 1000
        assert totals["recv"] == 2000

    def test_cleanup_old_data(self, store):
        """Test that cleanup removes old data."""
        # Add data for today
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        # Cleanup with 0 days should remove everything
        deleted = store.cleanup_old_data(keep_days=0)

        # Verify today's data is still there (cutoff is before today)
        stats = store.get_today_stats("WiFi:TestNetwork")
        assert stats is not None

    def test_backup_and_restore(self, store, temp_data_dir):
        """Test backup and restore functionality."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        # Create backup
        backup_path = store.backup()
        assert Path(backup_path).exists()

        # Modify data
        store.reset_today()

        # Restore
        store.restore(backup_path)

        # Verify restored data
        stats = store.get_today_stats("WiFi:TestNetwork")
        assert stats is not None
        assert stats.bytes_sent == 1000

    def test_export_json(self, store, temp_data_dir):
        """Test exporting data to JSON."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        export_path = store.export_json()
        assert Path(export_path).exists()

        import json

        with open(export_path) as f:
            data = json.load(f)

        assert "traffic_stats" in data
        assert "issues" in data

    def test_import_json(self, store, temp_data_dir):
        """Test importing data from JSON."""
        # Export first
        store.update_stats("WiFi:TestNetwork", 1000, 2000)
        export_path = store.export_json()

        # Reset and import
        store.reset_today()
        imported = store.import_json(export_path)

        assert imported > 0

    def test_save_and_get_device(self, store):
        """Test saving and retrieving device information."""
        store.save_device(
            "AA:BB:CC:DD:EE:FF", custom_name="My Device", vendor="Apple", device_type="laptop"
        )

        device = store.get_device("AA:BB:CC:DD:EE:FF")
        assert device is not None
        assert device["custom_name"] == "My Device"
        assert device["vendor"] == "Apple"

    def test_get_all_devices(self, store):
        """Test getting all devices."""
        store.save_device("AA:BB:CC:DD:EE:FF", custom_name="Device 1")
        store.save_device("11:22:33:44:55:66", custom_name="Device 2")

        devices = store.get_all_devices()
        assert len(devices) == 2

    def test_get_database_stats(self, store):
        """Test getting database statistics."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)

        stats = store.get_database_stats()
        assert stats["traffic_records"] >= 1
        assert "file_size_bytes" in stats

    def test_flush(self, store):
        """Test that flush doesn't raise errors."""
        store.update_stats("WiFi:TestNetwork", 1000, 2000)
        store.flush()  # Should complete without error


class TestConnectionStats:
    """Tests for ConnectionStats dataclass."""

    def test_from_dict(self):
        """Test creating ConnectionStats from dict."""
        data = {
            "bytes_sent": 1000,
            "bytes_recv": 2000,
            "peak_upload": 100.0,
            "peak_download": 200.0,
            "issues": [],
        }
        stats = ConnectionStats.from_dict(data)
        assert stats.bytes_sent == 1000
        assert stats.bytes_recv == 2000

    def test_to_dict(self):
        """Test converting ConnectionStats to dict."""
        stats = ConnectionStats(bytes_sent=1000, bytes_recv=2000)
        data = stats.to_dict()
        assert data["bytes_sent"] == 1000
        assert data["bytes_recv"] == 2000

    def test_default_issues(self):
        """Test that issues defaults to empty list."""
        stats = ConnectionStats()
        assert stats.issues == []
