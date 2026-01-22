"""Tests for the config module."""
import pytest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from config.constants import INTERVALS, THRESHOLDS, STORAGE, COLORS, NETWORK
from config.exceptions import (
    NetworkMonitorError,
    ConnectionError,
    StorageError,
    ScannerError,
    SubprocessError,
)
from config.logging_config import setup_logging, get_logger, LogContext
from config.subprocess_cache import SubprocessCache, safe_run, get_subprocess_cache


class TestConstants:
    """Tests for constants module."""
    
    def test_intervals_are_positive(self):
        """All interval values should be positive."""
        assert INTERVALS.UPDATE_SECONDS > 0
        assert INTERVALS.DEVICE_SCAN_SECONDS > 0
        assert INTERVALS.LATENCY_CHECK_SECONDS > 0
        assert INTERVALS.SAVE_INTERVAL_SECONDS > 0
    
    def test_thresholds_latency_ordering(self):
        """Latency thresholds should be in ascending order."""
        assert THRESHOLDS.LATENCY_GOOD_MS < THRESHOLDS.LATENCY_OK_MS
        assert THRESHOLDS.LATENCY_OK_MS < THRESHOLDS.LATENCY_POOR_MS
        assert THRESHOLDS.LATENCY_POOR_MS < THRESHOLDS.HIGH_LATENCY_MS
    
    def test_storage_config_has_required_fields(self):
        """Storage config should have all required fields."""
        assert STORAGE.DATA_DIR_NAME
        assert STORAGE.STATS_FILE
        assert STORAGE.SETTINGS_FILE
        assert STORAGE.LOG_FILE
    
    def test_colors_rgba_format(self):
        """RGBA colors should be 4-tuples with values 0-255."""
        for color in [COLORS.GREEN_RGBA, COLORS.YELLOW_RGBA, COLORS.RED_RGBA]:
            assert len(color) == 4
            assert all(0 <= c <= 255 for c in color)
    
    def test_colors_hex_format(self):
        """Hex colors should start with # and be 7 chars."""
        for color in [COLORS.GREEN_HEX, COLORS.YELLOW_HEX, COLORS.RED_HEX]:
            assert color.startswith('#')
            assert len(color) == 7


class TestExceptions:
    """Tests for custom exceptions."""
    
    def test_base_exception(self):
        """NetworkMonitorError should work with message and details."""
        exc = NetworkMonitorError("Test error", {"key": "value"})
        assert exc.message == "Test error"
        assert exc.details == {"key": "value"}
        assert "Test error" in str(exc)
        assert "key" in str(exc)
    
    def test_exception_without_details(self):
        """Exceptions should work without details."""
        exc = StorageError("Storage failed")
        assert exc.message == "Storage failed"
        assert exc.details == {}
        assert str(exc) == "Storage failed"
    
    def test_subprocess_error_with_full_info(self):
        """SubprocessError should capture command details."""
        exc = SubprocessError(
            "Command failed",
            command=["ping", "-c", "1", "8.8.8.8"],
            returncode=1,
            stdout="output",
            stderr="error"
        )
        assert exc.command == ["ping", "-c", "1", "8.8.8.8"]
        assert exc.returncode == 1
        assert "command" in exc.details
    
    def test_exception_inheritance(self):
        """All custom exceptions should inherit from NetworkMonitorError."""
        assert issubclass(ConnectionError, NetworkMonitorError)
        assert issubclass(StorageError, NetworkMonitorError)
        assert issubclass(ScannerError, NetworkMonitorError)
        assert issubclass(SubprocessError, NetworkMonitorError)


class TestLogging:
    """Tests for logging configuration."""
    
    def test_setup_logging_creates_logger(self, temp_data_dir):
        """setup_logging should return a configured logger."""
        logger = setup_logging(data_dir=temp_data_dir, console_output=False)
        assert logger is not None
        assert logger.name == 'netmon'
    
    def test_get_logger_returns_child(self, temp_data_dir):
        """get_logger should return child of root logger."""
        setup_logging(data_dir=temp_data_dir, console_output=False)
        logger = get_logger("test.module")
        assert 'netmon' in logger.name
    
    def test_log_context_measures_duration(self, temp_data_dir):
        """LogContext should measure operation duration."""
        import time
        setup_logging(data_dir=temp_data_dir, console_output=False)
        logger = get_logger(__name__)
        
        with LogContext(logger, "Test operation") as ctx:
            time.sleep(0.01)  # Sleep 10ms
        
        # Context should have recorded start time
        assert ctx.start_time is not None


class TestSubprocessCache:
    """Tests for subprocess caching."""
    
    def test_cache_stores_results(self):
        """Cache should store and return cached results."""
        cache = SubprocessCache(default_ttl=60.0)
        
        # Run a simple command
        result1 = cache.run(['echo', 'hello'], check_allowed=False)
        assert result1.returncode == 0
        
        # Second call should be cached
        stats_before = cache.get_stats()
        result2 = cache.run(['echo', 'hello'], check_allowed=False)
        stats_after = cache.get_stats()
        
        assert stats_after['hits'] > stats_before['hits']
    
    def test_cache_expires(self):
        """Cache entries should expire after TTL."""
        cache = SubprocessCache(default_ttl=0.01)  # 10ms TTL
        
        result1 = cache.run(['echo', 'test'], check_allowed=False)
        
        import time
        time.sleep(0.02)  # Wait for expiry
        
        # Should be a cache miss
        stats_before = cache.get_stats()
        result2 = cache.run(['echo', 'test'], check_allowed=False)
        stats_after = cache.get_stats()
        
        assert stats_after['misses'] > stats_before['misses']
    
    def test_cache_bypass(self):
        """bypass_cache should skip caching."""
        cache = SubprocessCache(default_ttl=60.0)
        
        result1 = cache.run(['echo', 'bypass'], bypass_cache=True, check_allowed=False)
        result2 = cache.run(['echo', 'bypass'], bypass_cache=True, check_allowed=False)
        
        # Both should be misses
        stats = cache.get_stats()
        assert stats['hits'] == 0
    
    def test_invalidate_specific_command(self):
        """invalidate should clear specific cached command."""
        cache = SubprocessCache(default_ttl=60.0)
        
        cache.run(['echo', 'a'], check_allowed=False)
        cache.run(['echo', 'b'], check_allowed=False)
        
        cache.invalidate(['echo', 'a'])
        
        # 'a' should be a miss, 'b' should be a hit
        stats_before = cache.get_stats()
        cache.run(['echo', 'a'], check_allowed=False)
        stats_after = cache.get_stats()
        
        assert stats_after['misses'] == stats_before['misses'] + 1
    
    def test_safe_run_validates_command(self):
        """safe_run should reject commands not in allowlist."""
        with pytest.raises(SubprocessError) as exc_info:
            safe_run(['rm', '-rf', '/'], check_allowed=True)
        
        assert "not in allowlist" in str(exc_info.value)
    
    def test_safe_run_allows_known_commands(self):
        """safe_run should allow commands in allowlist."""
        # 'which' should be in the allowlist
        result = safe_run(['which', 'python3'], check_allowed=True)
        # Should complete without raising
        assert result is not None
    
    def test_global_cache_is_singleton(self):
        """get_subprocess_cache should return same instance."""
        cache1 = get_subprocess_cache()
        cache2 = get_subprocess_cache()
        assert cache1 is cache2


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
