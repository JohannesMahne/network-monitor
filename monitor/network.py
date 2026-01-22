"""Network statistics collection using psutil."""
import time
from dataclasses import dataclass
from typing import Optional, Tuple
import psutil

from monitor.utils import format_bytes


@dataclass
class SpeedStats:
    """Current network speed statistics."""
    upload_speed: float  # bytes per second
    download_speed: float  # bytes per second
    total_sent: int  # total bytes sent
    total_recv: int  # total bytes received


class NetworkStats:
    """Collects and calculates network statistics."""
    
    def __init__(self):
        self._last_bytes_sent: int = 0
        self._last_bytes_recv: int = 0
        self._last_time: float = 0
        self._session_start_sent: int = 0
        self._session_start_recv: int = 0
        self._session_start_time: float = 0
        self._peak_upload: float = 0
        self._peak_download: float = 0
        self._speed_samples: list = []
        self._initialized = False
    
    def _get_total_bytes(self) -> Tuple[int, int]:
        """Get total bytes sent and received across all interfaces."""
        counters = psutil.net_io_counters()
        return counters.bytes_sent, counters.bytes_recv
    
    def initialize(self) -> None:
        """Initialize the baseline measurements."""
        sent, recv = self._get_total_bytes()
        current_time = time.time()
        
        self._last_bytes_sent = sent
        self._last_bytes_recv = recv
        self._last_time = current_time
        self._session_start_sent = sent
        self._session_start_recv = recv
        self._session_start_time = current_time
        self._initialized = True
    
    def get_current_stats(self) -> Optional[SpeedStats]:
        """Get current network statistics including speed."""
        if not self._initialized:
            self.initialize()
            return None
        
        current_time = time.time()
        sent, recv = self._get_total_bytes()
        
        time_delta = current_time - self._last_time
        if time_delta < 0.1:  # Avoid division by very small numbers
            return None
        
        # Calculate speeds
        bytes_sent_delta = sent - self._last_bytes_sent
        bytes_recv_delta = recv - self._last_bytes_recv
        
        upload_speed = bytes_sent_delta / time_delta
        download_speed = bytes_recv_delta / time_delta
        
        # Update peak speeds
        if upload_speed > self._peak_upload:
            self._peak_upload = upload_speed
        if download_speed > self._peak_download:
            self._peak_download = download_speed
        
        # Store for averaging
        self._speed_samples.append((upload_speed, download_speed))
        # Keep last 100 samples for average calculation
        if len(self._speed_samples) > 100:
            self._speed_samples.pop(0)
        
        # Update last values
        self._last_bytes_sent = sent
        self._last_bytes_recv = recv
        self._last_time = current_time
        
        return SpeedStats(
            upload_speed=upload_speed,
            download_speed=download_speed,
            total_sent=sent,
            total_recv=recv
        )
    
    def get_session_totals(self) -> Tuple[int, int]:
        """Get bytes sent/received since session start."""
        sent, recv = self._get_total_bytes()
        return (
            sent - self._session_start_sent,
            recv - self._session_start_recv
        )
    
    def get_peak_speeds(self) -> Tuple[float, float]:
        """Get peak upload and download speeds."""
        return self._peak_upload, self._peak_download
    
    def get_average_speeds(self) -> Tuple[float, float]:
        """Get average upload and download speeds."""
        if not self._speed_samples:
            return 0.0, 0.0
        
        avg_upload = sum(s[0] for s in self._speed_samples) / len(self._speed_samples)
        avg_download = sum(s[1] for s in self._speed_samples) / len(self._speed_samples)
        return avg_upload, avg_download
    
    def reset_session(self) -> None:
        """Reset session statistics."""
        self._session_start_sent, self._session_start_recv = self._get_total_bytes()
        self._session_start_time = time.time()
        self._peak_upload = 0
        self._peak_download = 0
        self._speed_samples = []


# Re-export format_bytes for backwards compatibility
__all__ = ['NetworkStats', 'SpeedStats', 'format_bytes']
