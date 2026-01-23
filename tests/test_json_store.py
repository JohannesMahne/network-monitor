"""Tests for storage/json_store.py"""

import json

from storage.json_store import ConnectionStats, JsonStore


class TestConnectionStats:
    """Tests for the ConnectionStats dataclass."""

    def test_default_values(self):
        stats = ConnectionStats()
        assert stats.bytes_sent == 0
        assert stats.bytes_recv == 0
        assert stats.issues == []

    def test_to_dict(self):
        stats = ConnectionStats(bytes_sent=1000, bytes_recv=2000)
        result = stats.to_dict()
        assert result["bytes_sent"] == 1000
        assert result["bytes_recv"] == 2000

    def test_from_dict(self):
        data = {"bytes_sent": 5000, "bytes_recv": 10000, "issues": []}
        stats = ConnectionStats.from_dict(data)
        assert stats.bytes_sent == 5000
        assert stats.bytes_recv == 10000


class TestJsonStore:
    """Tests for the JsonStore class."""

    def test_init_creates_directory(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        assert temp_data_dir.exists()

    def test_update_stats(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Test", 1000, 2000, 100, 200)
        store.flush()  # Force save

        with open(store.data_file) as f:
            data = json.load(f)

        today = store._get_today_key()
        assert today in data
        assert "WiFi:Test" in data[today]

    def test_get_today_totals(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Home", 1000, 2000)
        store.update_stats("WiFi:Work", 3000, 4000)

        sent, recv = store.get_today_totals()
        assert sent == 4000
        assert recv == 6000

    def test_reset_today(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Test", 1000, 2000)
        store.reset_today()

        sent, recv = store.get_today_totals()
        assert sent == 0
        assert recv == 0

    def test_flush(self, temp_data_dir):
        store = JsonStore(data_dir=temp_data_dir)
        store.update_stats("WiFi:Test", 1000, 2000)
        store.flush()

        # Verify data was written
        assert store.data_file.exists()
        with open(store.data_file) as f:
            data = json.load(f)
        assert len(data) > 0
