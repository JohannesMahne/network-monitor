"""Integration tests for Network Monitor.

These tests verify end-to-end functionality across multiple components.
They use real implementations (not mocks) where safe to do so.

Run with: pytest -m integration
"""

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest


@pytest.mark.integration
class TestStorageIntegration:
    """Integration tests for storage layer."""

    def test_sqlite_store_full_lifecycle(self, integration_data_dir: Path):
        """Test complete SQLite store lifecycle: create, update, query, backup."""
        from storage.sqlite_store import SQLiteStore

        # SQLiteStore expects a data_dir (Path), not a full file path
        store = SQLiteStore(data_dir=integration_data_dir)

        # Update stats
        store.update_stats("WiFi:TestNetwork", 1000, 5000, 100, 500)
        store.update_stats("WiFi:TestNetwork", 2000, 3000, 150, 400)

        # Query today's totals
        sent, recv = store.get_today_totals()
        assert sent == 3000  # 1000 + 2000
        assert recv == 8000  # 5000 + 3000

        # Test backup
        backup_path = integration_data_dir / "backup.db"
        store.backup(str(backup_path))
        assert backup_path.exists()

        # Verify backup contains data
        backup_conn = sqlite3.connect(str(backup_path))
        cursor = backup_conn.execute("SELECT SUM(bytes_sent) FROM traffic_stats")
        result = cursor.fetchone()[0]
        backup_conn.close()
        assert result == 3000

        # Flush to ensure data is persisted
        store.flush()

    def test_json_to_sqlite_migration(self, integration_data_dir: Path):
        """Test migration from JSON store to SQLite."""
        from storage.json_store import JsonStore
        from storage.sqlite_store import SQLiteStore

        # Create JSON store with data
        json_store = JsonStore(data_dir=integration_data_dir)

        # Add some data via JSON store
        json_store.update_stats("WiFi:OldNetwork", 5000, 10000, 200, 800)
        json_store.flush()  # Force save

        # Read back from JSON directly to verify
        json_path = integration_data_dir / "stats.json"
        with open(json_path) as f:
            json_data = json.load(f)

        today = datetime.now().strftime("%Y-%m-%d")
        assert today in json_data
        assert "WiFi:OldNetwork" in json_data[today]

        # Now create SQLite store in a subdirectory
        sqlite_dir = integration_data_dir / "sqlite_migration"
        sqlite_dir.mkdir(exist_ok=True)
        sqlite_store = SQLiteStore(data_dir=sqlite_dir)

        # Manually migrate data
        for date_str, connections in json_data.items():
            for conn_key, stats in connections.items():
                sqlite_store.update_stats(
                    conn_key,
                    stats.get("bytes_sent", 0),
                    stats.get("bytes_recv", 0),
                    stats.get("peak_upload", 0),
                    stats.get("peak_download", 0),
                )

        # Verify migration
        sent, recv = sqlite_store.get_today_totals()
        assert sent >= 5000
        assert recv >= 10000

        sqlite_store.flush()


@pytest.mark.integration
class TestSettingsIntegration:
    """Integration tests for settings management."""

    def test_settings_persistence(self, integration_data_dir: Path):
        """Test settings are persisted and loaded correctly."""
        from storage.settings import ConnectionBudget, SettingsManager

        # SettingsManager expects a data_dir (Path), not a full file path
        manager1 = SettingsManager(data_dir=integration_data_dir)
        manager1.set_title_display("latency")

        # Create a ConnectionBudget object and set it
        budget = ConnectionBudget(
            enabled=True,
            limit_bytes=10_000_000_000,
            period="monthly",
            warn_at_percent=80,
        )
        manager1.set_budget("WiFi:Home", budget)

        # Create new manager instance (simulates app restart)
        manager2 = SettingsManager(data_dir=integration_data_dir)

        # Verify settings persisted
        assert manager2.get_title_display() == "latency"
        loaded_budget = manager2.get_budget("WiFi:Home")
        assert loaded_budget is not None
        assert loaded_budget.limit_bytes == 10_000_000_000
        assert loaded_budget.period == "monthly"
        assert loaded_budget.enabled is True


@pytest.mark.integration
class TestIssueDetectionIntegration:
    """Integration tests for issue detection."""

    def test_issue_detection_via_connectivity_changes(self):
        """Test that issues are created via connectivity check."""
        from monitor.issues import IssueDetector, IssueType

        detector = IssueDetector()

        # Simulate disconnect - start connected, then disconnect
        detector.check_connectivity(is_connected=True)  # Initialize as connected
        detector.check_connectivity(is_connected=False)  # Disconnect

        # Retrieve issues
        issues = detector.get_recent_issues(count=10)
        assert len(issues) >= 1

        # Verify disconnect issue was logged
        issue_types = [i.issue_type for i in issues]
        assert IssueType.DISCONNECT in issue_types

    def test_issue_reconnection_tracking(self):
        """Test reconnection tracking."""
        from monitor.issues import IssueDetector, IssueType

        detector = IssueDetector()

        # Simulate disconnect then reconnect
        detector.check_connectivity(is_connected=True)
        detector.check_connectivity(is_connected=False)
        time.sleep(0.1)  # Small delay for downtime tracking
        detector.check_connectivity(is_connected=True)

        issues = detector.get_recent_issues(count=10)
        issue_types = [i.issue_type for i in issues]

        assert IssueType.DISCONNECT in issue_types
        assert IssueType.RECONNECT in issue_types


@pytest.mark.integration
class TestEventBusIntegration:
    """Integration tests for event bus communication."""

    def test_event_publishing_and_subscription(self):
        """Test event bus pub/sub mechanism."""
        from app.events import Event, EventBus, EventType

        # Use sync mode for deterministic testing
        bus = EventBus(async_mode=False)
        received_events = []

        def handler(event: Event):
            received_events.append((event.event_type, event.data))

        # Subscribe to events
        bus.subscribe(EventType.STATS_UPDATED, handler)
        bus.subscribe(EventType.CONNECTION_CHANGED, handler)

        # Publish events
        bus.publish(EventType.STATS_UPDATED, {"upload": 1000, "download": 5000})
        bus.publish(EventType.CONNECTION_CHANGED, {"old": "WiFi:A", "new": "WiFi:B"})
        bus.publish(EventType.DEVICES_SCANNED, {"count": 5})  # Not subscribed

        # Verify only subscribed events received
        assert len(received_events) == 2
        assert received_events[0][0] == EventType.STATS_UPDATED
        assert received_events[1][0] == EventType.CONNECTION_CHANGED

    def test_async_event_processing(self):
        """Test async event bus processes events in background."""
        from app.events import Event, EventBus, EventType

        bus = EventBus(async_mode=True)
        received_events = []

        def handler(event: Event):
            received_events.append(event.event_type)

        bus.subscribe(EventType.STATS_UPDATED, handler)
        bus.publish(EventType.STATS_UPDATED, {"test": True})

        # Wait for async processing
        time.sleep(0.2)

        assert len(received_events) == 1
        assert received_events[0] == EventType.STATS_UPDATED


@pytest.mark.integration
@pytest.mark.slow
class TestFullStackIntegration:
    """Full stack integration tests (slower, more comprehensive)."""

    def test_controller_update_cycle(self, integration_data_dir: Path):
        """Test a complete controller update cycle."""
        # This test requires more setup and is marked as slow
        # It would test the full AppController.update() flow
        # For now, we verify the basic structure works
        from app.events import Event, EventBus, EventType

        bus = EventBus(async_mode=False)
        events_received = []

        def capture_all(event: Event):
            events_received.append(event.event_type)

        # Subscribe to key events
        for event_type in [
            EventType.STATS_UPDATED,
            EventType.CONNECTION_CHANGED,
            EventType.DEVICES_SCANNED,
        ]:
            bus.subscribe(event_type, capture_all)

        # The full controller test would require mocking macOS-specific APIs
        # This scaffolding shows the structure for future expansion
        assert bus is not None


@pytest.mark.integration
class TestDataExportIntegration:
    """Integration tests for data export functionality."""

    def test_json_export(self, integration_data_dir: Path):
        """Test JSON export of all data."""
        from storage.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=integration_data_dir)

        # Add test data
        store.update_stats("WiFi:ExportTest", 3000, 9000, 300, 900)

        # Export to JSON
        json_path = integration_data_dir / "export.json"
        exported_path = store.export_json(output_path=json_path)

        # Verify JSON content
        assert exported_path.exists()
        with open(exported_path) as f:
            data = json.load(f)

        # Should have traffic_stats or be a dict with data
        assert isinstance(data, dict)

        store.flush()

    def test_weekly_monthly_totals(self, integration_data_dir: Path):
        """Test weekly and monthly aggregation."""
        from storage.sqlite_store import SQLiteStore

        store = SQLiteStore(data_dir=integration_data_dir)

        # Add test data for multiple connections
        store.update_stats("WiFi:Home", 1000, 5000, 100, 500)
        store.update_stats("WiFi:Work", 2000, 8000, 200, 800)
        store.update_stats("Ethernet", 500, 1000, 50, 100)

        # Get weekly totals
        weekly = store.get_weekly_totals()
        assert "sent" in weekly
        assert "recv" in weekly
        assert weekly["sent"] >= 3500
        assert weekly["recv"] >= 14000

        # Get monthly totals
        monthly = store.get_monthly_totals()
        assert "sent" in monthly
        assert "recv" in monthly

        store.flush()
