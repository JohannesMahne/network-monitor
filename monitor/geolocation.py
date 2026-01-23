"""IP geolocation service for external connections.

Provides country lookup for IP addresses using free geolocation APIs.
Results are cached to minimize API calls.
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from config import STORAGE, get_logger

logger = get_logger(__name__)


class GeolocationService:
    """Provides IP geolocation lookup with caching.

    Uses free APIs (ip-api.com) with rate limiting and caching
    to minimize API calls.
    """

    # Free API endpoint (45 requests/minute limit)
    API_URL = "http://ip-api.com/json/{ip}?fields=status,country,countryCode"

    # Cache file location
    CACHE_FILE = "geolocation_cache.json"

    # Cache expiration (7 days)
    CACHE_EXPIRY_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize the geolocation service.

        Args:
            data_dir: Directory for cache file (defaults to ~/.network-monitor/)
        """
        if data_dir is None:
            data_dir = Path.home() / STORAGE.DATA_DIR_NAME
        self.data_dir = data_dir
        self.cache_file = data_dir / self.CACHE_FILE
        self._cache: Dict[str, dict] = {}
        self._load_cache()
        logger.debug(f"GeolocationService initialized, cache: {len(self._cache)} entries")

    def _load_cache(self) -> None:
        """Load geolocation cache from disk."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file) as f:
                    data = json.load(f)
                    # Filter expired entries
                    current_time = time.time()
                    self._cache = {
                        ip: entry
                        for ip, entry in data.items()
                        if current_time - entry.get("timestamp", 0) < self.CACHE_EXPIRY_SECONDS
                    }
                    logger.debug(f"Loaded {len(self._cache)} valid cache entries")
        except Exception as e:
            logger.debug(f"Could not load geolocation cache: {e}")
            self._cache = {}

    def _save_cache(self) -> None:
        """Save geolocation cache to disk."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save geolocation cache: {e}")

    def _is_private_ip(self, ip: str) -> bool:
        """Check if IP is private/local.

        Args:
            ip: IP address string

        Returns:
            True if IP is private (10.x, 192.168.x, 172.16-31.x, 127.x)
        """
        parts = ip.split(".")
        if len(parts) != 4:
            return True

        try:
            first = int(parts[0])
            second = int(parts[1])

            # Private IP ranges
            if first == 10:
                return True
            if first == 192 and second == 168:
                return True
            if first == 172 and 16 <= second <= 31:
                return True
            if first == 127:
                return True
            if first == 169 and second == 254:  # Link-local
                return True
        except ValueError:
            return True

        return False

    def lookup_country(self, ip: str) -> Optional[str]:
        """Look up country for an IP address.

        Args:
            ip: IP address to look up

        Returns:
            Country code (e.g., 'US', 'GB') or None if lookup failed
        """
        if not ip or self._is_private_ip(ip):
            return None

        # Check cache first
        if ip in self._cache:
            entry = self._cache[ip]
            if time.time() - entry.get("timestamp", 0) < self.CACHE_EXPIRY_SECONDS:
                return entry.get("country_code")

        # Lookup via API
        try:
            url = self.API_URL.format(ip=ip)
            request = Request(url, headers={"User-Agent": "NetworkMonitor/1.0"})

            with urlopen(request, timeout=3.0) as response:
                data = json.loads(response.read().decode())

                if data.get("status") == "success":
                    country_code = data.get("countryCode")
                    if country_code:
                        # Cache the result
                        self._cache[ip] = {
                            "country_code": country_code,
                            "country": data.get("country", ""),
                            "timestamp": time.time(),
                        }
                        self._save_cache()
                        return country_code
        except (URLError, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.debug(f"Geolocation lookup failed for {ip}: {e}")

        return None

    def get_country_name(self, country_code: str) -> str:
        """Get country name from country code.

        Args:
            country_code: Two-letter country code (e.g., 'US')

        Returns:
            Country name or code if not found
        """
        # Basic mapping for common countries
        country_names = {
            "US": "USA",
            "GB": "UK",
            "DE": "Germany",
            "FR": "France",
            "CA": "Canada",
            "AU": "Australia",
            "JP": "Japan",
            "CN": "China",
            "IN": "India",
            "BR": "Brazil",
            "MX": "Mexico",
            "IT": "Italy",
            "ES": "Spain",
            "NL": "Netherlands",
            "SE": "Sweden",
            "NO": "Norway",
            "DK": "Denmark",
            "FI": "Finland",
            "PL": "Poland",
            "RU": "Russia",
        }
        return country_names.get(country_code, country_code)
