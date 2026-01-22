"""Pytest configuration and shared fixtures."""
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_stats_data():
    """Sample statistics data for testing."""
    return {
        "2026-01-20": {
            "WiFi:TestNetwork": {
                "bytes_sent": 1000000,
                "bytes_recv": 5000000,
                "peak_upload": 100000,
                "peak_download": 500000,
                "issues": []
            }
        }
    }
