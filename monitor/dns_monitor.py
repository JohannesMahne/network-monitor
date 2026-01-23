"""DNS performance monitoring.

Tracks DNS resolution times and alerts on slow DNS.
"""
import socket
import time
from collections import deque
from typing import List, Optional

from config import INTERVALS, NETWORK, THRESHOLDS, get_logger

logger = get_logger(__name__)


class DNSMonitor:
    """Monitors DNS resolution performance.
    
    Tracks DNS lookup times for common domains and alerts when
    DNS performance degrades.
    """

    # Test domains for DNS performance
    TEST_DOMAINS = [
        "google.com",
        "cloudflare.com",
        "apple.com",
        "github.com",
    ]

    def __init__(self):
        """Initialize the DNS monitor."""
        self._latency_samples: deque = deque(maxlen=THRESHOLDS.LATENCY_SAMPLE_COUNT)
        self._last_check: float = 0
        self._check_interval: float = NETWORK.DNS_CHECK_INTERVAL
        self._slow_dns_threshold: float = NETWORK.DNS_SLOW_THRESHOLD_MS
        logger.debug("DNSMonitor initialized")

    def check_dns_performance(self, force: bool = False) -> Optional[float]:
        """Check DNS resolution performance.
        
        Args:
            force: Force check even if interval hasn't elapsed
            
        Returns:
            Average DNS latency in milliseconds, or None if check failed
        """
        current_time = time.time()
        
        if not force and (current_time - self._last_check) < self._check_interval:
            return self.get_average_dns_latency()
        
        self._last_check = current_time
        
        latencies = []
        for domain in self.TEST_DOMAINS:
            latency = self._resolve_domain(domain)
            if latency is not None:
                latencies.append(latency)
        
        if not latencies:
            return None
        
        avg_latency = sum(latencies) / len(latencies)
        self._latency_samples.append(avg_latency)
        
        logger.debug(f"DNS check: {avg_latency:.1f}ms average")
        return avg_latency

    def _resolve_domain(self, domain: str) -> Optional[float]:
        """Resolve a domain name and measure the time.
        
        Args:
            domain: Domain name to resolve
            
        Returns:
            Resolution time in milliseconds, or None if failed
        """
        try:
            start = time.time()
            socket.gethostbyname(domain)
            elapsed = (time.time() - start) * 1000  # Convert to ms
            return elapsed
        except Exception as e:
            logger.debug(f"DNS resolution failed for {domain}: {e}")
            return None

    def get_average_dns_latency(self) -> Optional[float]:
        """Get average DNS latency from recent samples.
        
        Returns:
            Average latency in milliseconds, or None if no samples
        """
        if not self._latency_samples:
            return None
        return sum(self._latency_samples) / len(self._latency_samples)

    def get_current_dns_latency(self) -> Optional[float]:
        """Get the most recent DNS latency measurement.
        
        Returns:
            Most recent latency in milliseconds, or None if no measurements
        """
        if not self._latency_samples:
            return None
        return self._latency_samples[-1]

    def is_dns_slow(self) -> bool:
        """Check if DNS is currently slow.
        
        Returns:
            True if average DNS latency exceeds threshold
        """
        avg = self.get_average_dns_latency()
        if avg is None:
            return False
        return avg > self._slow_dns_threshold

    def clear_samples(self) -> None:
        """Clear DNS latency samples (e.g., on session reset)."""
        self._latency_samples.clear()
