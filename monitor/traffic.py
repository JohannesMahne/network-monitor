"""Traffic breakdown by process/service."""
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import psutil

from config import INTERVALS, get_logger
from config.subprocess_cache import get_subprocess_cache
from monitor.utils import format_bytes

logger = get_logger(__name__)


@dataclass
class ProcessTraffic:
    """Traffic statistics for a single process."""
    pid: int
    name: str
    bytes_in: int = 0
    bytes_out: int = 0
    connections: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def total_bytes(self) -> int:
        return self.bytes_in + self.bytes_out

    @property
    def display_name(self) -> str:
        """Get a clean display name for the process."""
        # Clean up common process names
        name_lower = self.name.lower()

        # Map common process names to friendly names
        name_map = {
            'google chrome': 'Chrome',
            'google chrome helper': 'Chrome',
            'chrome': 'Chrome',
            'firefox': 'Firefox',
            'safari': 'Safari',
            'safarinetworkingprivacy': 'Safari',
            'safarilaunchchecker': 'Safari',
            'microsoft edge': 'Edge',
            'msedge': 'Edge',
            'slack': 'Slack',
            'slack helper': 'Slack',
            'zoom.us': 'Zoom',
            'spotify': 'Spotify',
            'spotify helper': 'Spotify',
            'discord': 'Discord',
            'discord helper': 'Discord',
            'telegram': 'Telegram',
            'whatsapp': 'WhatsApp',
            'signal': 'Signal',
            'messages': 'Messages',
            'facetime': 'FaceTime',
            'mail': 'Mail',
            'outlook': 'Outlook',
            'microsoft outlook': 'Outlook',
            'thunderbird': 'Thunderbird',
            'dropbox': 'Dropbox',
            'onedrive': 'OneDrive',
            'google drive': 'Google Drive',
            'icloud': 'iCloud',
            'cloudd': 'iCloud',
            'bird': 'iCloud',
            'code': 'VS Code',
            'code helper': 'VS Code',
            'cursor': 'Cursor',
            'cursor helper': 'Cursor',
            'node': 'Node.js',
            'python': 'Python',
            'python3': 'Python',
            'java': 'Java',
            'docker': 'Docker',
            'com.docker': 'Docker',
            'vpnkit': 'Docker',
            'ssh': 'SSH',
            'sshd': 'SSH',
            'git': 'Git',
            'git-remote-https': 'Git',
            'curl': 'curl',
            'wget': 'wget',
            'brew': 'Homebrew',
            'softwareupdated': 'Software Update',
            'apsd': 'Apple Push',
            'appstoreagent': 'App Store',
            'storedownloadd': 'App Store',
            'nsurlsessiond': 'System Downloads',
            'com.apple.nsurlsessiond': 'System Downloads',
            'trustd': 'System Security',
            'syspolicyd': 'System Security',
            'networkserviceproxy': 'Network Proxy',
            'rapportd': 'Rapport (Handoff)',
            'sharingd': 'AirDrop/Sharing',
            'identityservicesd': 'Apple ID',
            'parsecd': 'Siri',
            'assistantd': 'Siri',
            'mediaremoted': 'Media Remote',
            'itunescloudd': 'iTunes/Music',
            'music': 'Music',
            'podcasts': 'Podcasts',
            'tv': 'Apple TV',
            'netflix': 'Netflix',
            'prime video': 'Prime Video',
            'vlc': 'VLC',
            'iina': 'IINA',
            'transmit': 'Transmit',
            'filezilla': 'FileZilla',
            'cyberduck': 'Cyberduck',
            'tower': 'Tower (Git)',
            'sourcetree': 'SourceTree',
            'postman': 'Postman',
            'insomnia': 'Insomnia',
            'charles': 'Charles Proxy',
            'wireshark': 'Wireshark',
            'little snitch': 'Little Snitch',
            'lulu': 'Lulu Firewall',
            'tunnelblick': 'Tunnelblick VPN',
            'openvpn': 'OpenVPN',
            'wireguard': 'WireGuard',
            'nordvpn': 'NordVPN',
            'expressvpn': 'ExpressVPN',
            'steam': 'Steam',
            'steam helper': 'Steam',
            'epic games': 'Epic Games',
            'battle.net': 'Battle.net',
        }

        for key, friendly_name in name_map.items():
            if key in name_lower:
                return friendly_name

        # Capitalize first letter if not mapped
        return self.name.split()[0].capitalize() if self.name else 'Unknown'


@dataclass
class ServiceCategory:
    """Traffic grouped by service category."""
    name: str
    bytes_in: int = 0
    bytes_out: int = 0
    processes: List[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return self.bytes_in + self.bytes_out


# Port to service category mapping
PORT_CATEGORIES = {
    # Web browsing
    80: 'Web',
    443: 'Web (HTTPS)',
    8080: 'Web',
    8443: 'Web',
    # Email
    25: 'Email',
    465: 'Email',
    587: 'Email',
    993: 'Email (IMAP)',
    995: 'Email (POP)',
    # File transfer
    20: 'FTP',
    21: 'FTP',
    22: 'SSH/SFTP',
    # Streaming
    554: 'Streaming (RTSP)',
    1935: 'Streaming (RTMP)',
    # Gaming
    3478: 'Gaming/Voice',
    3479: 'Gaming/Voice',
    3480: 'Gaming/Voice',
    # Cloud services
    5222: 'Messaging (XMPP)',
    5223: 'Apple Push',
    # DNS
    53: 'DNS',
    853: 'DNS (TLS)',
    # VPN
    500: 'VPN (IKE)',
    1194: 'VPN (OpenVPN)',
    1701: 'VPN (L2TP)',
    4500: 'VPN (NAT-T)',
    51820: 'VPN (WireGuard)',
}


class TrafficMonitor:
    """Monitors network traffic by process."""

    def __init__(self):
        self._process_traffic: Dict[int, ProcessTraffic] = {}
        self._last_nettop_data: Dict[str, Tuple[int, int]] = {}  # process -> (bytes_in, bytes_out)
        self._lock = None  # Will use threading lock if needed
        self._subprocess_cache = get_subprocess_cache()
        logger.debug("TrafficMonitor initialized")

    def _get_process_name(self, pid: int) -> Optional[str]:
        """Get process name from PID."""
        try:
            proc = psutil.Process(pid)
            return proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _get_active_connections(self) -> Dict[int, List[tuple]]:
        """Get active network connections grouped by PID."""
        connections_by_pid: Dict[int, List[tuple]] = defaultdict(list)

        try:
            connections = psutil.net_connections(kind='inet')
            for conn in connections:
                if conn.pid and conn.status == 'ESTABLISHED':
                    local_port = conn.laddr.port if conn.laddr else 0
                    remote_port = conn.raddr.port if conn.raddr else 0
                    connections_by_pid[conn.pid].append((local_port, remote_port))
        except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
            # On macOS, net_connections needs root - fall back to lsof
            pass

        return connections_by_pid

    def _run_nettop(self) -> Dict[str, Tuple[int, int]]:
        """Run nettop to get per-process traffic data."""
        result = {}

        try:
            # Run nettop for one sample in delta mode
            # -P: show by process, -L 1: 1 sample, -d: delta mode, -J bytes
            proc = self._subprocess_cache.run(
                ['nettop', '-P', '-L', '1', '-J', 'bytes_in,bytes_out'],
                ttl=2.0,  # Cache briefly
                timeout=INTERVALS.NETTOP_TIMEOUT_SECONDS
            )

            if proc.returncode == 0:
                # Parse nettop output
                # Format: process_name      bytes_in    bytes_out
                lines = proc.stdout.strip().split('\n')

                for line in lines:
                    # Skip header and empty lines
                    if not line.strip() or 'bytes_in' in line.lower() or line.startswith('time'):
                        continue

                    # Split by whitespace
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            # First part is process name (may include .pid suffix)
                            proc_info = parts[0].strip()

                            # Skip time-like entries
                            if ':' in proc_info and proc_info.count(':') >= 1:
                                # Might be timestamp like "17:40:29"
                                if all(c.isdigit() or c == ':' for c in proc_info):
                                    continue

                            # Extract process name (remove .pid suffix if present)
                            if '.' in proc_info:
                                # Check if last part is a number (PID)
                                name_parts = proc_info.rsplit('.', 1)
                                if name_parts[-1].isdigit():
                                    proc_name = name_parts[0]
                                else:
                                    proc_name = proc_info
                            else:
                                proc_name = proc_info

                            # Skip system/empty names
                            if not proc_name or proc_name in ('time', 'interface', '-'):
                                continue

                            # Last two numeric values are usually bytes_in and bytes_out
                            bytes_in = 0
                            bytes_out = 0

                            numeric_values = []
                            for part in parts[1:]:
                                part = part.strip()
                                if part.isdigit():
                                    numeric_values.append(int(part))

                            if len(numeric_values) >= 2:
                                bytes_in = numeric_values[0]
                                bytes_out = numeric_values[1]
                            elif len(numeric_values) == 1:
                                bytes_in = numeric_values[0]

                            if proc_name and (bytes_in > 0 or bytes_out > 0):
                                if proc_name in result:
                                    result[proc_name] = (
                                        result[proc_name][0] + bytes_in,
                                        result[proc_name][1] + bytes_out
                                    )
                                else:
                                    result[proc_name] = (bytes_in, bytes_out)
                        except (ValueError, IndexError):
                            continue
        except Exception as e:
            # Log but don't fail - nettop may not be available
            logger.debug(f"nettop error (may be unavailable): {e}")

        return result

    def _run_netstat_processes(self) -> Dict[str, int]:
        """Get connection counts by process using lsof (works without root on macOS)."""
        process_connections: Dict[str, int] = defaultdict(int)

        try:
            # Use lsof with short timeout - this works without root on macOS
            # -i: network connections, -n: no DNS, -P: port numbers, +c0: full command
            result = self._subprocess_cache.run(
                ['lsof', '+c', '0', '-i', '-n', '-P'],
                ttl=3.0,  # Cache briefly
                timeout=INTERVALS.LSOF_TIMEOUT_SECONDS
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 1:
                        # Clean up process name
                        proc_name = parts[0].replace('\\x20', ' ').strip()
                        # Skip kernel and system
                        if proc_name in ('kernel', 'launchd', 'mDNSRespo', 'mDNSResponder'):
                            continue
                        # Count connections (ESTABLISHED or has remote address)
                        if 'ESTABLISHED' in line or '->' in line or 'LISTEN' not in line:
                            process_connections[proc_name] += 1
        except subprocess.TimeoutExpired:
            pass  # nosec B110 - lsof timeout expected
        except Exception:
            pass  # nosec B110 - Connection enumeration is best-effort

        return process_connections

    def get_traffic_by_process(self) -> List[ProcessTraffic]:
        """Get current traffic breakdown by process."""
        traffic_list = []
        seen_names = set()

        # Primary method: Use psutil for fast connection data
        connections_by_pid = self._get_active_connections()

        for pid, conns in connections_by_pid.items():
            name = self._get_process_name(pid)
            if name and name not in seen_names:
                seen_names.add(name)
                traffic = ProcessTraffic(
                    pid=pid,
                    name=name,
                    connections=len(conns)
                )
                traffic_list.append(traffic)

        # Add any additional from connection scan
        additional_counts = self._run_netstat_processes()
        for proc_name, conn_count in additional_counts.items():
            if proc_name not in seen_names:
                seen_names.add(proc_name)
                traffic = ProcessTraffic(
                    pid=0,
                    name=proc_name,
                    connections=conn_count
                )
                traffic_list.append(traffic)

        # Sort by connections (most active first)
        traffic_list.sort(
            key=lambda t: t.connections,
            reverse=True
        )

        return traffic_list

    def get_traffic_summary(self) -> List[Tuple[str, int, int, int]]:
        """Get a summary of traffic by process.
        
        Returns list of (display_name, bytes_in, bytes_out, connections)
        """
        traffic = self.get_traffic_by_process()

        # Aggregate by display name (combines helpers with main process)
        aggregated: Dict[str, Tuple[int, int, int]] = {}

        for t in traffic:
            name = t.display_name
            if name in aggregated:
                prev = aggregated[name]
                aggregated[name] = (
                    prev[0] + t.bytes_in,
                    prev[1] + t.bytes_out,
                    prev[2] + t.connections
                )
            else:
                aggregated[name] = (t.bytes_in, t.bytes_out, t.connections)

        # Convert to list and sort
        result = [
            (name, data[0], data[1], data[2])
            for name, data in aggregated.items()
        ]

        # Sort by total bytes, then connections
        result.sort(key=lambda x: (x[1] + x[2], x[3]), reverse=True)

        return result

    def get_top_processes(self, limit: int = 10) -> List[Tuple[str, int, int, int]]:
        """Get top N processes by traffic.
        
        Returns list of (display_name, bytes_in, bytes_out, connections)
        """
        summary = self.get_traffic_summary()
        return summary[:limit]

    def categorize_traffic(self) -> Dict[str, ServiceCategory]:
        """Categorize traffic by service type."""
        categories: Dict[str, ServiceCategory] = {}

        # Get connections and categorize by port
        try:
            connections = psutil.net_connections(kind='inet')

            for conn in connections:
                if conn.status != 'ESTABLISHED':
                    continue

                # Determine category from port
                remote_port = conn.raddr.port if conn.raddr else 0
                local_port = conn.laddr.port if conn.laddr else 0

                category_name = PORT_CATEGORIES.get(
                    remote_port,
                    PORT_CATEGORIES.get(local_port, 'Other')
                )

                # Get process name
                proc_name = None
                if conn.pid:
                    proc_name = self._get_process_name(conn.pid)

                if category_name not in categories:
                    categories[category_name] = ServiceCategory(name=category_name)

                cat = categories[category_name]
                if proc_name and proc_name not in cat.processes:
                    cat.processes.append(proc_name)

        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        return categories


# Alias for backwards compatibility
format_traffic_bytes = format_bytes
