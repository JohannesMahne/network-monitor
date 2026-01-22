"""Tests for monitor/network.py"""
import pytest
from monitor.network import NetworkStats, format_bytes


class TestFormatBytes:
    """Tests for the format_bytes function."""
    
    def test_format_zero_bytes(self):
        result = format_bytes(0)
        assert "0" in result or result == "0.0 B"
    
    def test_format_bytes_basic(self):
        assert format_bytes(500) == "500.0 B"
    
    def test_format_kilobytes(self):
        assert format_bytes(1024) == "1.0 KB"
        assert format_bytes(1536) == "1.5 KB"
    
    def test_format_megabytes(self):
        assert format_bytes(1024 * 1024) == "1.0 MB"
    
    def test_format_gigabytes(self):
        assert format_bytes(1024 * 1024 * 1024) == "1.0 GB"
    
    def test_format_speed(self):
        assert format_bytes(1024, speed=True) == "1.0 KB/s"
        assert format_bytes(1024 * 1024, speed=True) == "1.0 MB/s"


class TestNetworkStats:
    """Tests for the NetworkStats class."""
    
    def test_initialization(self):
        stats = NetworkStats()
        assert stats._initialized is False
    
    def test_initialize(self):
        stats = NetworkStats()
        stats.initialize()
        assert stats._initialized is True
    
    def test_reset_session(self):
        stats = NetworkStats()
        stats.initialize()
        stats._peak_upload = 1000
        stats._peak_download = 2000
        
        stats.reset_session()
        
        assert stats._peak_upload == 0
        assert stats._peak_download == 0
    
    def test_get_peak_speeds(self):
        stats = NetworkStats()
        stats._peak_upload = 1000
        stats._peak_download = 2000
        
        up, down = stats.get_peak_speeds()
        assert up == 1000
        assert down == 2000
    
    def test_get_average_speeds_empty(self):
        stats = NetworkStats()
        up, down = stats.get_average_speeds()
        assert up == 0.0
        assert down == 0.0
