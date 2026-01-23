"""Connection tracker for external IP addresses.

Tracks external connections per app and provides geolocation information.
"""

import ipaddress
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import psutil

from config import get_logger

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

    def get_external_connections(self) -> Dict[str, List[ConnectionInfo]]:
        """Get external connections grouped by app.

        Returns:
            Dict mapping app_name -> List[ConnectionInfo]
        """
        try:
            connections = psutil.net_connections(kind="inet")
            current_connections: Dict[str, List[ConnectionInfo]] = defaultdict(list)

            for conn in connections:
                if conn.status != "ESTABLISHED" or not conn.raddr:
                    continue

                remote_ip = conn.raddr.ip
                if not self._is_external_ip(remote_ip):
                    continue

                # Get process name
                app_name = "Unknown"
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        app_name = proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # Lookup country if geolocation service available
                country_code = None
                if self._geolocation and remote_ip not in self._seen_ips:
                    country_code = self._geolocation.lookup_country(remote_ip)
                    if country_code:
                        self._seen_ips.add(remote_ip)

                conn_info = ConnectionInfo(
                    remote_ip=remote_ip,
                    remote_port=conn.raddr.port,
                    local_port=conn.laddr.port if conn.laddr else 0,
                    country_code=country_code,
                )

                current_connections[app_name].append(conn_info)

            # Update tracked connections
            self._app_connections = current_connections

            return dict(current_connections)
        except (psutil.AccessDenied, Exception) as e:
            logger.debug(f"Connection tracking error: {e}")
            return {}

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
