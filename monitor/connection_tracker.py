"""Connection tracker for external IP addresses.

Tracks external connections per app and provides geolocation information.
"""

import ipaddress
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import psutil

from config import INTERVALS, get_logger
from config.subprocess_cache import get_subprocess_cache

logger = get_logger(__name__)


@dataclass
class ConnectionInfo:
    """Information about an external connection."""

    remote_ip: str
    remote_port: int
    local_port: int
    country_code: Optional[str] = None
    bytes_transferred: int = 0
    last_seen: float = 0


class ConnectionTracker:
    """Tracks external network connections per app.

    Identifies external IPs (not local/private) and tracks them
    per application process.
    """

    def __init__(self, geolocation_service=None):
        """Initialize the connection tracker.

        Args:
            geolocation_service: Optional GeolocationService for country lookup
        """
        self._geolocation = geolocation_service
        # Track connections: app_name -> List[ConnectionInfo]
        self._app_connections: Dict[str, List[ConnectionInfo]] = defaultdict(list)
        # Track seen IPs to avoid duplicate lookups
        self._seen_ips: Set[str] = set()
        logger.debug("ConnectionTracker initialized")

    def _is_external_ip(self, ip: str) -> bool:
        """Check if IP is external (not local/private).

        Args:
            ip: IP address string

        Returns:
            True if IP is external
        """
        try:
            addr = ipaddress.ip_address(ip)
            return not addr.is_private and not addr.is_loopback and not addr.is_link_local
        except ValueError:
            return False

    def _parse_endpoint(self, endpoint: str) -> Tuple[Optional[str], int]:
        """Parse IPv4 'ip:port' or IPv6 '[ip]:port' into (ip, port)."""
        endpoint = endpoint.strip()
        if endpoint.startswith("["):
            match = re.match(r"^\[([^\]]+)\]:(\d+)$", endpoint)
            if match:
                return match.group(1), int(match.group(2))
            return None, 0
        if ":" in endpoint:
            ip, port_str = endpoint.rsplit(":", 1)
            if port_str.isdigit():
                return ip, int(port_str)
        return None, 0

    def _get_raw_connections_via_lsof(self) -> List[Tuple[str, str, int, int]]:
        """Get established TCP connections using lsof (works without root on macOS).

        Returns list of (app_name, remote_ip, remote_port, local_port).
        """
        results: List[Tuple[str, str, int, int]] = []
        try:
            cache = get_subprocess_cache()
            proc = cache.run(
                ["lsof", "+c", "0", "-iTCP", "-sTCP:ESTABLISHED", "-n", "-P"],
                ttl=5.0,
                timeout=INTERVALS.LSOF_TIMEOUT_SECONDS,
            )
            if proc.returncode != 0 or not proc.stdout:
                return results

            for line in proc.stdout.strip().split("\n")[1:]:
                if "->" not in line:
                    continue
                parts = line.split()
                if len(parts) < 9:
                    continue
                app_name = parts[0].replace("\\x20", " ").strip()
                # Find the "local->remote" token
                arrow_token = next((p for p in parts if "->" in p), None)
                if not arrow_token:
                    continue
                local_ep, remote_ep = arrow_token.split("->", 1)
                _, local_port = self._parse_endpoint(local_ep)
                remote_ip, remote_port = self._parse_endpoint(remote_ep)
                if remote_ip and self._is_external_ip(remote_ip):
                    results.append((app_name, remote_ip, remote_port, local_port))
        except Exception as e:
            logger.debug(f"lsof connection tracking error: {e}")
        return results

    def get_external_connections(self) -> Dict[str, List[ConnectionInfo]]:
        """Get external connections grouped by app.

        Uses psutil when permitted, falling back to lsof on macOS without root.

        Returns:
            Dict mapping app_name -> List[ConnectionInfo]
        """
        current_connections: Dict[str, List[ConnectionInfo]] = defaultdict(list)
        raw_connections: List[Tuple[str, str, int, int]] = []

        try:
            connections = psutil.net_connections(kind="inet")
            for conn in connections:
                if conn.status != "ESTABLISHED" or not conn.raddr:
                    continue
                remote_ip = conn.raddr.ip
                if not self._is_external_ip(remote_ip):
                    continue
                app_name = "Unknown"
                if conn.pid:
                    try:
                        app_name = psutil.Process(conn.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                local_port = conn.laddr.port if conn.laddr else 0
                raw_connections.append((app_name, remote_ip, conn.raddr.port, local_port))
        except psutil.AccessDenied:
            # Non-root on macOS: fall back to lsof for current user's processes
            raw_connections = self._get_raw_connections_via_lsof()
        except Exception as e:
            logger.debug(f"Connection tracking error: {e}")
            return {}

        new_lookups = 0
        max_new_lookups = 10  # Cap uncached HTTP lookups per cycle to stay fast

        for app_name, remote_ip, remote_port, local_port in raw_connections:
            country_code = None
            if self._geolocation:
                cached = remote_ip in getattr(self._geolocation, "_cache", {})
                if cached or new_lookups < max_new_lookups:
                    if not cached:
                        new_lookups += 1
                    country_code = self._geolocation.lookup_country(remote_ip)
                    if country_code:
                        self._seen_ips.add(remote_ip)

            conn_info = ConnectionInfo(
                remote_ip=remote_ip,
                remote_port=remote_port,
                local_port=local_port,
                country_code=country_code,
            )
            current_connections[app_name].append(conn_info)

        self._app_connections = current_connections
        return dict(current_connections)

    def get_countries_per_app(self) -> Dict[str, List[str]]:
        """Get list of countries each app connects to.

        Returns:
            Dict mapping app_name -> List[country_codes]
        """
        connections = self.get_external_connections()
        result = {}

        for app_name, conns in connections.items():
            countries = set()
            for conn in conns:
                if conn.country_code:
                    countries.add(conn.country_code)
            result[app_name] = sorted(list(countries))

        return result
