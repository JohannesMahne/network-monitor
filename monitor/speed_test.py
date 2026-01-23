"""Network speed test functionality.

Provides on-demand speed testing using HTTP downloads/uploads to measure
actual network throughput.
"""
import ssl
import time
from typing import Dict, Optional
from urllib.request import urlopen, Request

from config import get_logger

logger = get_logger(__name__)


class SpeedTest:
    """Performs network speed tests using HTTP transfers."""

    # Test download URLs - multiple fallbacks
    DOWNLOAD_URLS = [
        # Cloudflare speed test (reliable, worldwide CDN)
        ("https://speed.cloudflare.com/__down?bytes={size}", True),
        # Fast.com (Netflix) - smaller chunks
        ("https://api.fast.com/netflix/speedtest", False),
    ]

    # Upload test URL (Cloudflare accepts POST)
    UPLOAD_URL = "https://speed.cloudflare.com/__up"

    def __init__(self):
        """Initialize the speed test."""
        self._running = False
        # Create SSL context that doesn't verify (for speed test reliability)
        self._ssl_context = ssl.create_default_context()

    def run_test(self, duration_seconds: int = 10) -> Optional[Dict[str, float]]:
        """Run a speed test.
        
        Args:
            duration_seconds: How long to run the test (download phase)
            
        Returns:
            Dictionary with 'download_mbps', 'upload_mbps', and 'latency_ms'
            Returns None if test fails completely
        """
        if self._running:
            logger.warning("Speed test already running")
            return None

        self._running = True
        try:
            logger.info("Starting speed test...")
            
            # Test latency first
            latency = self._test_latency()
            logger.info(f"Latency test complete: {latency:.1f}ms")
            
            # Test download speed
            download_mbps = self._test_download(duration_seconds)
            logger.info(f"Download test complete: {download_mbps:.1f} Mbps")
            
            # Test upload speed
            upload_mbps = self._test_upload(max(3, duration_seconds // 3))
            logger.info(f"Upload test complete: {upload_mbps:.1f} Mbps")
            
            # If all tests failed, return None
            if download_mbps == 0 and upload_mbps == 0 and latency == 0:
                logger.error("All speed tests failed")
                return None
            
            return {
                'download_mbps': download_mbps,
                'upload_mbps': upload_mbps,
                'latency_ms': latency,
            }
        except Exception as e:
            logger.error(f"Speed test error: {e}", exc_info=True)
            return None
        finally:
            self._running = False

    def _test_latency(self) -> float:
        """Test latency to test server."""
        latencies = []
        test_urls = [
            "https://www.google.com/generate_204",
            "https://www.cloudflare.com/cdn-cgi/trace",
            "https://1.1.1.1/cdn-cgi/trace",
        ]
        
        for url in test_urls:
            try:
                start = time.time()
                req = Request(url, headers={'User-Agent': 'NetworkMonitor/1.0'})
                urlopen(req, timeout=5, context=self._ssl_context)
                latency = (time.time() - start) * 1000  # Convert to ms
                latencies.append(latency)
            except Exception as e:
                logger.debug(f"Latency test to {url} failed: {e}")
                continue
        
        if latencies:
            # Return median latency
            latencies.sort()
            return latencies[len(latencies) // 2]
        return 0.0

    def _test_download(self, duration_seconds: int) -> float:
        """Test download speed using multiple methods."""
        # Try Cloudflare first (most reliable)
        for url_template, supports_size in self.DOWNLOAD_URLS:
            try:
                if supports_size:
                    # Request 100MB for longer tests, 25MB for shorter
                    test_size = 100 * 1024 * 1024 if duration_seconds >= 10 else 25 * 1024 * 1024
                    url = url_template.format(size=test_size)
                else:
                    url = url_template
                
                logger.debug(f"Testing download from: {url}")
                
                req = Request(url, headers={
                    'User-Agent': 'NetworkMonitor/1.0',
                    'Accept': '*/*',
                })
                
                start_time = time.time()
                bytes_downloaded = 0
                
                with urlopen(req, timeout=duration_seconds + 10, context=self._ssl_context) as response:
                    # Read in larger chunks for better throughput measurement
                    chunk_size = 64 * 1024  # 64 KB chunks
                    while time.time() - start_time < duration_seconds:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        bytes_downloaded += len(chunk)
                
                elapsed = time.time() - start_time
                if elapsed > 0 and bytes_downloaded > 0:
                    mbps = (bytes_downloaded * 8) / (elapsed * 1_000_000)  # Convert to Mbps
                    logger.debug(f"Downloaded {bytes_downloaded / 1024 / 1024:.1f} MB in {elapsed:.1f}s = {mbps:.1f} Mbps")
                    return mbps
                    
            except Exception as e:
                logger.debug(f"Download test failed with {url_template}: {e}")
                continue
        
        logger.warning("All download tests failed")
        return 0.0

    def _test_upload(self, duration_seconds: int) -> float:
        """Test upload speed by POSTing data to Cloudflare."""
        try:
            # Generate test data (1MB chunks)
            chunk_size = 1024 * 1024  # 1 MB
            test_data = b'0' * chunk_size
            
            start_time = time.time()
            bytes_uploaded = 0
            
            # Upload multiple chunks within duration
            while time.time() - start_time < duration_seconds:
                try:
                    req = Request(
                        self.UPLOAD_URL,
                        data=test_data,
                        headers={
                            'User-Agent': 'NetworkMonitor/1.0',
                            'Content-Type': 'application/octet-stream',
                        },
                        method='POST'
                    )
                    with urlopen(req, timeout=10, context=self._ssl_context) as response:
                        response.read()  # Read response to complete the request
                    bytes_uploaded += chunk_size
                except Exception as e:
                    logger.debug(f"Upload chunk failed: {e}")
                    break
            
            elapsed = time.time() - start_time
            if elapsed > 0 and bytes_uploaded > 0:
                mbps = (bytes_uploaded * 8) / (elapsed * 1_000_000)
                logger.debug(f"Uploaded {bytes_uploaded / 1024 / 1024:.1f} MB in {elapsed:.1f}s = {mbps:.1f} Mbps")
                return mbps
                
        except Exception as e:
            logger.debug(f"Upload test failed: {e}")
        
        return 0.0

    @property
    def is_running(self) -> bool:
        """Check if a speed test is currently running."""
        return self._running
