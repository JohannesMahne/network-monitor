"""Connection detection for WiFi and Ethernet on macOS."""
import subprocess
import re
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path
import psutil

from config import get_logger, INTERVALS
from config.subprocess_cache import get_subprocess_cache

logger = get_logger(__name__)


@dataclass
class ConnectionInfo:
    """Information about the current network connection."""
    connection_type: str  # "WiFi", "Ethernet", "Unknown"
    name: str  # SSID for WiFi, interface name for others
    interface: str  # e.g., "en0", "en1"
    is_connected: bool
    ip_address: Optional[str] = None
    vpn_active: bool = False
    vpn_name: Optional[str] = None


class ConnectionDetector:
    """Detects and monitors network connection type and details."""
    
    # Airport command path (removed in newer macOS versions)
    AIRPORT_PATH = '/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport'
    
    def __init__(self):
        self._last_connection: Optional[ConnectionInfo] = None
        self._subprocess_cache = get_subprocess_cache()
        self._wifi_interface = self._find_wifi_interface()
        # Check once at startup if airport command exists
        self._has_airport = Path(self.AIRPORT_PATH).exists()
        logger.debug(f"ConnectionDetector initialized, WiFi interface: {self._wifi_interface}, airport={self._has_airport}")
    
    def _find_wifi_interface(self) -> str:
        """Find the WiFi interface name (usually en0 or en1)."""
        try:
            # Hardware ports change very rarely - cache for 60 seconds
            result = self._subprocess_cache.run(
                ['networksetup', '-listallhardwareports'],
                ttl=60.0,
                timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
            )
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if 'Wi-Fi' in line or 'AirPort' in line:
                    # Next line should have "Device: enX"
                    if i + 1 < len(lines):
                        match = re.search(r'Device:\s*(\w+)', lines[i + 1])
                        if match:
                            return match.group(1)
        except Exception as e:
            logger.debug(f"Error finding WiFi interface: {e}")
        return 'en0'  # Default fallback
    
    def _get_wifi_ssid(self) -> Optional[str]:
        """Get the current WiFi SSID using CoreWLAN or command-line tools."""
        
        # Method 1: Try CoreWLAN framework (works if Location Services enabled)
        try:
            import objc
            from Foundation import NSBundle
            
            CoreWLAN = NSBundle.bundleWithPath_('/System/Library/Frameworks/CoreWLAN.framework')
            if CoreWLAN and CoreWLAN.load():
                CWWiFiClient = objc.lookUpClass('CWWiFiClient')
                client = CWWiFiClient.sharedWiFiClient()
                interface = client.interface()
                
                if interface:
                    ssid = interface.ssid()
                    if ssid and ssid != '<redacted>':
                        return ssid
        except Exception:
            pass
        
        # Method 2: Try networksetup command (cached for 2 seconds - SSID changes slowly)
        try:
            result = self._subprocess_cache.run(
                ['networksetup', '-getairportnetwork', self._wifi_interface],
                ttl=2.0,
                timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
            )
            if result.returncode == 0:
                # Output: "Current Wi-Fi Network: NetworkName"
                match = re.search(r'Current Wi-Fi Network:\s*(.+)', result.stdout)
                if match:
                    ssid = match.group(1).strip()
                    if ssid and ssid not in ("You are not associated with an AirPort network.", "<redacted>"):
                        return ssid
        except Exception:
            pass
        
        # Method 3: Try airport command (only if it exists - removed in newer macOS)
        if self._has_airport:
            try:
                result = self._subprocess_cache.run(
                    [self.AIRPORT_PATH, '-I'],
                    ttl=2.0,
                    timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS,
                    check_allowed=False  # Special path, not in allowlist
                )
                if result.returncode == 0:
                    match = re.search(r'\s+SSID:\s*(.+)', result.stdout)
                    if match:
                        ssid = match.group(1).strip()
                        if ssid and ssid != '<redacted>':
                            return ssid
            except Exception:
                pass
        
        # Method 4: Check if we're connected to WiFi but SSID is private
        # (macOS 14+ hides SSID without Location Services permission)
        try:
            result = self._subprocess_cache.run(
                ['ipconfig', 'getsummary', self._wifi_interface],
                ttl=2.0,
                timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
            )
            if 'SSID' in result.stdout:
                # WiFi is connected but SSID is hidden due to privacy
                return "[Private Network]"
        except Exception:
            pass
        
        return None
    
    def _get_active_interfaces(self) -> List[str]:
        """Get list of active network interfaces with IP addresses."""
        active = []
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        
        for iface, addr_list in addrs.items():
            # Skip loopback and inactive interfaces
            if iface == 'lo0' or iface.startswith('lo'):
                continue
            if iface not in stats or not stats[iface].isup:
                continue
            
            # Check for IPv4 address
            for addr in addr_list:
                if addr.family.name == 'AF_INET' and not addr.address.startswith('127.'):
                    active.append(iface)
                    break
        
        return active
    
    def _get_ip_address(self, interface: str) -> Optional[str]:
        """Get IP address for an interface."""
        addrs = psutil.net_if_addrs()
        if interface in addrs:
            for addr in addrs[interface]:
                if addr.family.name == 'AF_INET':
                    return addr.address
        return None
    
    def _get_interface_type(self, interface: str) -> str:
        """Determine the type of network interface."""
        try:
            # Hardware ports change very rarely - cache for 60 seconds
            result = self._subprocess_cache.run(
                ['networksetup', '-listallhardwareports'],
                ttl=60.0,
                timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
            )
            lines = result.stdout.split('\n')
            current_port = ""
            for line in lines:
                if line.startswith('Hardware Port:'):
                    current_port = line.replace('Hardware Port:', '').strip()
                elif f'Device: {interface}' in line:
                    return current_port
        except Exception:
            pass
        return "Unknown"
    
    def get_current_connection(self) -> ConnectionInfo:
        """Get information about the current network connection."""
        active_interfaces = self._get_active_interfaces()
        
        if not active_interfaces:
            return ConnectionInfo(
                connection_type="None",
                name="Disconnected",
                interface="",
                is_connected=False
            )
        
        # Check if WiFi is active and connected to a network
        if self._wifi_interface in active_interfaces:
            ssid = self._get_wifi_ssid()
            if ssid:
                # Clean up display name for private networks
                display_name = ssid if ssid != "[Private Network]" else "WiFi (Private - enable Location)"
                return ConnectionInfo(
                    connection_type="WiFi",
                    name=display_name,
                    interface=self._wifi_interface,
                    is_connected=True,
                    ip_address=self._get_ip_address(self._wifi_interface)
                )
        
        # Check each active interface and determine its type
        for iface in active_interfaces:
            iface_type = self._get_interface_type(iface)
            
            # WiFi interface but no SSID (might be sharing, bridge, etc.)
            if iface == self._wifi_interface:
                return ConnectionInfo(
                    connection_type="WiFi",
                    name="WiFi (No SSID)",
                    interface=iface,
                    is_connected=True,
                    ip_address=self._get_ip_address(iface)
                )
            
            # Ethernet-type connections
            if 'Ethernet' in iface_type or 'LAN' in iface_type:
                return ConnectionInfo(
                    connection_type="Ethernet",
                    name=iface_type,
                    interface=iface,
                    is_connected=True,
                    ip_address=self._get_ip_address(iface)
                )
            
            # Thunderbolt connections (often docks with Ethernet)
            if 'Thunderbolt' in iface_type:
                return ConnectionInfo(
                    connection_type="Thunderbolt",
                    name=f"Thunderbolt Network ({iface})",
                    interface=iface,
                    is_connected=True,
                    ip_address=self._get_ip_address(iface)
                )
            
            # Bridge connections
            if iface.startswith('bridge'):
                return ConnectionInfo(
                    connection_type="Bridge",
                    name=f"Bridge ({iface})",
                    interface=iface,
                    is_connected=True,
                    ip_address=self._get_ip_address(iface)
                )
        
        # Fallback: use first active interface
        iface = active_interfaces[0]
        iface_type = self._get_interface_type(iface)
        return ConnectionInfo(
            connection_type="Network",
            name=f"{iface_type} ({iface})" if iface_type != "Unknown" else iface,
            interface=iface,
            is_connected=True,
            ip_address=self._get_ip_address(iface)
        )
    
    def has_connection_changed(self) -> bool:
        """Check if the connection has changed since last check."""
        current = self.get_current_connection()
        
        if self._last_connection is None:
            self._last_connection = current
            return True
        
        changed = (
            current.connection_type != self._last_connection.connection_type or
            current.name != self._last_connection.name or
            current.is_connected != self._last_connection.is_connected
        )
        
        self._last_connection = current
        return changed
    
    def get_connection_key(self) -> str:
        """Get a unique key for the current connection (for storage)."""
        conn = self.get_current_connection()
        if not conn.is_connected:
            return "Disconnected"
        return f"{conn.connection_type}:{conn.name}"
    
    # === VPN Detection ===
    
    # Known VPN interface prefixes
    VPN_INTERFACE_PREFIXES = ('utun', 'tun', 'tap', 'ppp', 'ipsec', 'gif')
    
    # Known VPN process names (partial matches)
    VPN_PROCESS_NAMES = (
        'openvpn', 'wireguard', 'nordvpn', 'expressvpn', 'surfshark',
        'protonvpn', 'mullvad', 'privateinternetaccess', 'pia', 'tunnelblick',
        'viscosity', 'cisco', 'anyconnect', 'globalprotect', 'forticlient',
        'pulse', 'f5', 'zscaler', 'netskope', 'cloudflare', 'warp'
    )
    
    def detect_vpn(self) -> tuple:
        """Detect if a VPN connection is active.
        
        Returns:
            Tuple of (vpn_active: bool, vpn_name: Optional[str])
        """
        # Method 1: Check for VPN-related network interfaces
        vpn_interface = self._check_vpn_interfaces()
        if vpn_interface:
            return True, vpn_interface
        
        # Method 2: Check for running VPN processes
        vpn_process = self._check_vpn_processes()
        if vpn_process:
            return True, vpn_process
        
        # Method 3: Check for VPN configuration in network services
        vpn_service = self._check_vpn_services()
        if vpn_service:
            return True, vpn_service
        
        return False, None
    
    def _check_vpn_interfaces(self) -> Optional[str]:
        """Check for active VPN network interfaces."""
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
            
            for iface_name, iface_stats in stats.items():
                # Check if interface is up and matches VPN patterns
                if iface_stats.isup:
                    for prefix in self.VPN_INTERFACE_PREFIXES:
                        if iface_name.lower().startswith(prefix):
                            # Verify it has an IP address assigned
                            if iface_name in addrs:
                                for addr in addrs[iface_name]:
                                    if addr.family.name == 'AF_INET':
                                        return f"VPN ({iface_name})"
        except Exception as e:
            logger.debug(f"VPN interface check error: {e}")
        return None
    
    def _check_vpn_processes(self) -> Optional[str]:
        """Check for running VPN processes."""
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name'].lower()
                    for vpn_name in self.VPN_PROCESS_NAMES:
                        if vpn_name in proc_name:
                            # Return a cleaned up name
                            return proc.info['name']
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.debug(f"VPN process check error: {e}")
        return None
    
    def _check_vpn_services(self) -> Optional[str]:
        """Check macOS network services for active VPN."""
        try:
            result = self._subprocess_cache.run(
                ['networksetup', '-listnetworkserviceorder'],
                ttl=30.0,
                timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
            )
            
            if result.returncode == 0:
                # Look for VPN-related services that are active
                lines = result.stdout.split('\n')
                for i, line in enumerate(lines):
                    line_lower = line.lower()
                    if 'vpn' in line_lower or 'ipsec' in line_lower or 'l2tp' in line_lower:
                        # Extract service name
                        match = re.search(r'\(\d+\)\s+(.+)', line)
                        if match:
                            service_name = match.group(1).strip()
                            # Check if this service is connected
                            if self._is_service_active(service_name):
                                return service_name
        except Exception as e:
            logger.debug(f"VPN service check error: {e}")
        return None
    
    def _is_service_active(self, service_name: str) -> bool:
        """Check if a network service is currently active."""
        try:
            result = self._subprocess_cache.run(
                ['networksetup', '-getinfo', service_name],
                ttl=5.0,
                timeout=INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
            )
            if result.returncode == 0:
                # If it has an IP address, it's active
                return 'IP address:' in result.stdout and 'IP address: none' not in result.stdout.lower()
        except Exception:
            pass
        return False
