"""Network device scanner - discovers devices on the local network.

Uses multiple sources for device identification:
1. arp-scan (fast, provides MAC vendor from IEEE database)
2. dns-sd / mDNS / Bonjour (service discovery, device names)
3. nmap (OS detection, service fingerprinting - optional, needs sudo)
4. ARP table fallback (built-in, no extra tools needed)
5. Custom device names (user-assigned, persisted)
"""
import subprocess
import re
import socket
import time
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime
import threading

from config import get_logger, INTERVALS, STORAGE, NETWORK
from config.subprocess_cache import get_subprocess_cache, safe_run

logger = get_logger(__name__)


class DeviceType:
    """Device type classifications."""
    UNKNOWN = "unknown"
    DESKTOP = "desktop"
    LAPTOP = "laptop"
    PHONE = "phone"
    TABLET = "tablet"
    TV = "tv"
    SPEAKER = "speaker"
    IOT = "iot"
    ROUTER = "router"
    PRINTER = "printer"
    CAMERA = "camera"
    GAMING = "gaming"
    WATCH = "watch"
    
    # Icons for each type
    ICONS = {
        UNKNOWN: "❓",
        DESKTOP: "🖥️",
        LAPTOP: "💻",
        PHONE: "📱",
        TABLET: "📱",
        TV: "📺",
        SPEAKER: "🔊",
        IOT: "🔌",
        ROUTER: "📡",
        PRINTER: "🖨️",
        CAMERA: "📷",
        GAMING: "🎮",
        WATCH: "⌚",
    }


@dataclass
class NetworkDevice:
    """Represents a device on the network."""
    ip_address: str
    mac_address: str
    hostname: Optional[str] = None
    vendor: Optional[str] = None
    device_type: str = DeviceType.UNKNOWN
    os_hint: Optional[str] = None
    model_hint: Optional[str] = None
    custom_name: Optional[str] = None
    mdns_name: Optional[str] = None  # Name from Bonjour/mDNS
    services: List[str] = field(default_factory=list)
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)
    is_online: bool = True
    
    def __hash__(self):
        return hash(self.mac_address)
    
    def __eq__(self, other):
        if isinstance(other, NetworkDevice):
            return self.mac_address == other.mac_address
        return False
    
    @property
    def type_icon(self) -> str:
        """Get icon for device type."""
        return DeviceType.ICONS.get(self.device_type, "❓")
    
    @property
    def display_name(self) -> str:
        """Get best display name for the device.
        
        Priority: Custom > mDNS > Model > Hostname > Vendor > IP
        """
        if self.custom_name:
            return self.custom_name
        if self.mdns_name:
            return self.mdns_name
        if self.model_hint:
            return self.model_hint
        if self.hostname and self.hostname != self.ip_address:
            return self.hostname.split('.')[0]
        if self.vendor:
            return f"{self.vendor}"
        return self.ip_address


# ============================================================================
# Vendor to Device Type Mapping
# ============================================================================

VENDOR_TYPE_MAP = {
    # Routers / Network equipment
    "huawei": DeviceType.ROUTER,
    "cisco": DeviceType.ROUTER,
    "netgear": DeviceType.ROUTER,
    "tp-link": DeviceType.ROUTER,
    "linksys": DeviceType.ROUTER,
    "asus": DeviceType.ROUTER,
    "d-link": DeviceType.ROUTER,
    "ubiquiti": DeviceType.ROUTER,
    "aruba": DeviceType.ROUTER,
    "mikrotik": DeviceType.ROUTER,
    "zyxel": DeviceType.ROUTER,
    
    # IoT / Smart Home
    "espressif": DeviceType.IOT,
    "tuya": DeviceType.IOT,
    "shelly": DeviceType.IOT,
    "sonoff": DeviceType.IOT,
    "ewelink": DeviceType.IOT,
    "xiaomi": DeviceType.IOT,
    "philips": DeviceType.IOT,  # Hue
    "signify": DeviceType.IOT,  # Philips Hue
    "nest": DeviceType.IOT,
    "ring": DeviceType.CAMERA,
    "wyze": DeviceType.CAMERA,
    "eufy": DeviceType.CAMERA,
    "arlo": DeviceType.CAMERA,
    "shanghai high-flying": DeviceType.IOT,  # WiFi modules
    
    # Phones (default for these brands)
    "samsung": DeviceType.PHONE,
    "oneplus": DeviceType.PHONE,
    "oppo": DeviceType.PHONE,
    "vivo": DeviceType.PHONE,
    "motorola": DeviceType.PHONE,
    "google": DeviceType.PHONE,
    
    # TVs / Media
    "roku": DeviceType.TV,
    "lg electronics": DeviceType.TV,
    "tcl": DeviceType.TV,
    "vizio": DeviceType.TV,
    "hisense": DeviceType.TV,
    "samsung electro": DeviceType.TV,
    
    # Speakers
    "sonos": DeviceType.SPEAKER,
    "bose": DeviceType.SPEAKER,
    "harman": DeviceType.SPEAKER,
    
    # Gaming
    "sony": DeviceType.GAMING,  # PlayStation
    "microsoft": DeviceType.GAMING,  # Xbox
    "nintendo": DeviceType.GAMING,
    "valve": DeviceType.GAMING,
    
    # Printers
    "epson": DeviceType.PRINTER,
    "seiko epson": DeviceType.PRINTER,
    "hp inc": DeviceType.PRINTER,
    "hewlett": DeviceType.PRINTER,
    "canon": DeviceType.PRINTER,
    "brother": DeviceType.PRINTER,
    "xerox": DeviceType.PRINTER,
    
    # Computers
    "intel": DeviceType.DESKTOP,
    "dell": DeviceType.DESKTOP,
    "lenovo": DeviceType.DESKTOP,
    "asrock": DeviceType.DESKTOP,
    "gigabyte": DeviceType.DESKTOP,
    "amd": DeviceType.DESKTOP,
    
    # Apple - special handling needed
    "apple": DeviceType.LAPTOP,  # Default, refined by hostname/services
}

# Service to device type mapping (from mDNS)
SERVICE_TYPE_MAP = {
    "_airplay._tcp": DeviceType.TV,
    "_raop._tcp": DeviceType.SPEAKER,
    "_googlecast._tcp": DeviceType.TV,
    "_spotify-connect._tcp": DeviceType.SPEAKER,
    "_printer._tcp": DeviceType.PRINTER,
    "_ipp._tcp": DeviceType.PRINTER,
    "_ipps._tcp": DeviceType.PRINTER,
    "_scanner._tcp": DeviceType.PRINTER,
    "_hap._tcp": DeviceType.IOT,  # HomeKit
    "_homekit._tcp": DeviceType.IOT,
    "_smb._tcp": DeviceType.DESKTOP,
    "_afpovertcp._tcp": DeviceType.DESKTOP,
    "_ssh._tcp": DeviceType.DESKTOP,
    "_companion-link._tcp": DeviceType.PHONE,  # iOS Continuity
    "_apple-mobdev2._tcp": DeviceType.PHONE,
}

# Hostname patterns for device type inference
HOSTNAME_PATTERNS = [
    (r"(?i)(iphone|ios)", DeviceType.PHONE, "iOS", "iPhone"),
    (r"(?i)(ipad)", DeviceType.TABLET, "iPadOS", "iPad"),
    (r"(?i)(macbook|mbp|mba)", DeviceType.LAPTOP, "macOS", "MacBook"),
    (r"(?i)(imac|mac-?pro|mac-?mini|mac-?studio)", DeviceType.DESKTOP, "macOS", None),
    (r"(?i)(apple-?watch|watch)", DeviceType.WATCH, "watchOS", "Apple Watch"),
    (r"(?i)(apple-?tv|appletv)", DeviceType.TV, "tvOS", "Apple TV"),
    (r"(?i)(homepod)", DeviceType.SPEAKER, None, "HomePod"),
    (r"(?i)(android|pixel|galaxy|oneplus|xiaomi|redmi)", DeviceType.PHONE, "Android", None),
    (r"(?i)(echo|alexa)", DeviceType.SPEAKER, None, "Amazon Echo"),
    (r"(?i)(fire-?tv|firestick)", DeviceType.TV, None, "Fire TV"),
    (r"(?i)(chromecast)", DeviceType.TV, None, "Chromecast"),
    (r"(?i)(roku)", DeviceType.TV, None, "Roku"),
    (r"(?i)(playstation|ps[345])", DeviceType.GAMING, None, "PlayStation"),
    (r"(?i)(xbox)", DeviceType.GAMING, None, "Xbox"),
    (r"(?i)(switch)", DeviceType.GAMING, None, "Nintendo Switch"),
    (r"(?i)(printer|print|laserjet|deskjet)", DeviceType.PRINTER, None, None),
    (r"(?i)(cam|camera|doorbell)", DeviceType.CAMERA, None, None),
    (r"(?i)(tv|television|smarttv|bravia|webos|tizen)", DeviceType.TV, None, None),
    (r"(?i)(sonos|speaker)", DeviceType.SPEAKER, None, None),
    (r"(?i)(desktop|workstation|pc)", DeviceType.DESKTOP, "Windows", None),
    (r"(?i)(laptop|notebook|surface)", DeviceType.LAPTOP, "Windows", None),
    (r"(?i)(raspberry|raspi|pi\d)", DeviceType.IOT, "Linux", "Raspberry Pi"),
]


# ============================================================================
# Custom Device Names Storage
# ============================================================================

class DeviceNameStore:
    """Stores user-assigned custom names for devices."""
    
    _instance = None
    _names: Dict[str, str] = {}
    _store_path: Optional[Path] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance
    
    def _get_store_path(self) -> Path:
        if self._store_path is None:
            store_dir = Path.home() / ".network-monitor"
            store_dir.mkdir(exist_ok=True)
            self._store_path = store_dir / "device_names.json"
        return self._store_path
    
    def _load(self) -> None:
        try:
            path = self._get_store_path()
            if path.exists():
                with open(path, 'r') as f:
                    self._names = json.load(f)
        except Exception:
            self._names = {}
    
    def _save(self) -> None:
        try:
            with open(self._get_store_path(), 'w') as f:
                json.dump(self._names, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving device names: {e}")
    
    def get_name(self, mac_address: str) -> Optional[str]:
        mac = mac_address.upper().replace('-', ':')
        return self._names.get(mac)
    
    def set_name(self, mac_address: str, name: str) -> None:
        mac = mac_address.upper().replace('-', ':')
        self._names[mac] = name
        self._save()
    
    def remove_name(self, mac_address: str) -> None:
        mac = mac_address.upper().replace('-', ':')
        if mac in self._names:
            del self._names[mac]
            self._save()


# ============================================================================
# OUI Vendor Database
# ============================================================================

class OUIDatabase:
    """IEEE OUI database for MAC vendor lookup.
    
    Uses the database from arp-scan if available, otherwise falls back
    to a built-in subset.
    """
    
    _instance = None
    _vendors: Dict[str, str] = {}
    _loaded = False
    
    # Possible paths for OUI database
    OUI_PATHS = [
        "/opt/homebrew/Cellar/arp-scan/1.10.0/share/arp-scan/ieee-oui.txt",
        "/opt/homebrew/share/arp-scan/ieee-oui.txt",
        "/usr/local/share/arp-scan/ieee-oui.txt",
        "/usr/share/arp-scan/ieee-oui.txt",
    ]
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance
    
    def _load(self) -> None:
        """Load OUI database from file."""
        if self._loaded:
            return
        
        for path in self.OUI_PATHS:
            try:
                if Path(path).exists():
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            parts = line.split('\t', 1)
                            if len(parts) == 2:
                                prefix = parts[0].upper().replace(':', '').replace('-', '')
                                vendor = parts[1].strip()
                                self._vendors[prefix] = vendor
                    
                    self._loaded = True
                    logger.info(f"Loaded {len(self._vendors)} OUI entries from {path}")
                    return
            except Exception as e:
                logger.debug(f"Failed to load OUI from {path}: {e}")
        
        # Fallback: basic built-in database
        self._vendors = {
            "000C29": "VMware",
            "001C42": "Parallels",
            "080027": "Oracle VirtualBox",
            "0050F2": "Microsoft",
        }
        logger.warning("Using fallback OUI database (install arp-scan for better vendor detection)")
        self._loaded = True
    
    def lookup(self, mac_address: str) -> Optional[str]:
        """Look up vendor from MAC address."""
        mac_clean = mac_address.upper().replace(':', '').replace('-', '').replace('.', '')
        
        # Try progressively shorter prefixes (6, 5, 4, 3 bytes)
        for length in [12, 10, 8, 6]:
            prefix = mac_clean[:length]
            if prefix in self._vendors:
                return self._vendors[prefix]
        
        return None


# ============================================================================
# Tool Availability Check
# ============================================================================

class ToolChecker:
    """Check availability of network scanning tools.
    
    Results are cached indefinitely since installed tools don't change during runtime.
    """
    
    _cache: Dict[str, bool] = {}
    _subprocess_cache = None
    
    @classmethod
    def _get_subprocess_cache(cls):
        """Get subprocess cache lazily."""
        if cls._subprocess_cache is None:
            cls._subprocess_cache = get_subprocess_cache()
        return cls._subprocess_cache
    
    @classmethod
    def _check_tool(cls, tool_name: str) -> bool:
        """Check if a tool is available using cached subprocess."""
        if tool_name not in cls._cache:
            try:
                # Tool availability is static - cache for a very long time
                result = cls._get_subprocess_cache().run(
                    ['which', tool_name],
                    ttl=3600.0,  # Cache for 1 hour
                    timeout=2.0
                )
                cls._cache[tool_name] = result.returncode == 0
            except Exception:
                cls._cache[tool_name] = False
        return cls._cache[tool_name]
    
    @classmethod
    def has_arp_scan(cls) -> bool:
        return cls._check_tool('arp-scan')
    
    @classmethod
    def has_nmap(cls) -> bool:
        return cls._check_tool('nmap')
    
    @classmethod
    def has_dns_sd(cls) -> bool:
        return cls._check_tool('dns-sd')


# ============================================================================
# Device Type Inference
# ============================================================================

def infer_device_type(vendor: Optional[str], hostname: Optional[str],
                      services: List[str] = None, mdns_name: Optional[str] = None
                      ) -> Tuple[str, Optional[str], Optional[str]]:
    """Infer device type, OS, and model from available information.
    
    Returns: (device_type, os_hint, model_hint)
    """
    device_type = DeviceType.UNKNOWN
    os_hint = None
    model_hint = None
    
    # Check hostname patterns first (most specific)
    for pattern, dtype, os_h, model_h in HOSTNAME_PATTERNS:
        check_strings = [s for s in [hostname, mdns_name] if s]
        for s in check_strings:
            if re.search(pattern, s):
                device_type = dtype
                os_hint = os_h
                model_hint = model_h
                break
        if device_type != DeviceType.UNKNOWN:
            break
    
    # Check services (mDNS)
    if services and device_type == DeviceType.UNKNOWN:
        for service in services:
            if service in SERVICE_TYPE_MAP:
                device_type = SERVICE_TYPE_MAP[service]
                break
    
    # Check vendor
    if device_type == DeviceType.UNKNOWN and vendor:
        vendor_lower = vendor.lower()
        for vendor_key, dtype in VENDOR_TYPE_MAP.items():
            if vendor_key in vendor_lower:
                device_type = dtype
                break
    
    return device_type, os_hint, model_hint


def normalize_mac(mac_address: str) -> str:
    """Normalize MAC address to XX:XX:XX:XX:XX:XX format."""
    mac_clean = mac_address.upper().replace("-", ":").replace(".", ":")
    parts = mac_clean.split(":")
    if len(parts) == 6:
        return ":".join(p.zfill(2) for p in parts)
    return mac_address.upper()


# ============================================================================
# Network Scanner
# ============================================================================

class NetworkScanner:
    """Scans the local network for connected devices.
    
    Uses:
    1. ARP table - Device discovery (built-in, no privileges needed)
    2. IEEE OUI database - Vendor lookup from MAC address
    3. dns-sd / Bonjour - Service discovery for device names
    4. Hostname resolution - DNS names
    5. Custom names - User-assigned, persisted
    """
    
    def __init__(self):
        self._devices: Dict[str, NetworkDevice] = {}
        self._lock = threading.Lock()
        self._last_scan: float = 0
        self._last_mdns_scan: float = 0
        self._scan_interval = INTERVALS.DEVICE_SCAN_SECONDS * 2  # Less frequent than UI update
        self._mdns_scan_interval = INTERVALS.MDNS_SCAN_SECONDS
        self._own_mac_addresses: Set[str] = self._get_own_mac_addresses()
        self._name_store = DeviceNameStore()
        self._oui_db = OUIDatabase()
        self._mdns_names: Dict[str, str] = {}
        self._subprocess_cache = get_subprocess_cache()
        
        # Lazy hostname resolution
        self._pending_hostname_resolution: Set[str] = set()  # MACs pending resolution
        self._hostname_resolution_in_progress: bool = False
        self._hostname_resolve_lock = threading.Lock()
        
        # Check tool availability
        self._has_dns_sd = ToolChecker.has_dns_sd()
        self._has_nmap = ToolChecker.has_nmap()
        
        logger.info(f"Scanner initialized: OUI entries={len(self._oui_db._vendors)}, "
                   f"dns-sd={self._has_dns_sd}, nmap={self._has_nmap}")
    
    def _get_own_mac_addresses(self) -> Set[str]:
        """Get MAC addresses of our own interfaces."""
        own_macs = set()
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family.name == 'AF_LINK':
                        mac = normalize_mac(addr.address)
                        if mac and mac != "00:00:00:00:00:00":
                            own_macs.add(mac)
        except Exception:
            pass
        return own_macs
    
    def set_device_name(self, mac_address: str, name: str) -> None:
        """Set a custom name for a device."""
        self._name_store.set_name(mac_address, name)
        mac = normalize_mac(mac_address)
        with self._lock:
            if mac in self._devices:
                self._devices[mac].custom_name = name
    
    def get_device_name(self, mac_address: str) -> Optional[str]:
        """Get custom name for a device."""
        return self._name_store.get_name(mac_address)
    
    # ========================================================================
    # ARP Table Scan with OUI Lookup
    # ========================================================================
    
    def _run_arp_with_oui(self) -> List[Tuple[str, str, str]]:
        """Scan ARP table and look up vendors from OUI database.
        
        Returns list of (ip, mac, vendor).
        """
        devices = []
        
        try:
            # Use cached subprocess for ARP (changes slowly)
            result = self._subprocess_cache.run(
                ['arp', '-an'],
                ttl=10.0,  # Cache for 10 seconds
                timeout=NETWORK.ARP_SCAN_TIMEOUT
            )
            
            if result.returncode == 0:
                # Parse: ? (192.168.1.1) at 00:11:22:33:44:55 on en0 ...
                pattern = r'\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+)'
                
                for line in result.stdout.split('\n'):
                    match = re.search(pattern, line)
                    if match:
                        ip = match.group(1)
                        mac = normalize_mac(match.group(2))
                        
                        # Skip invalid
                        if mac == "(INCOMPLETE)" or mac == "FF:FF:FF:FF:FF:FF":
                            continue
                        if mac in self._own_mac_addresses:
                            continue
                        
                        # Skip multicast/broadcast
                        first_octet = int(ip.split('.')[0])
                        if 224 <= first_octet <= 239 or ip.endswith('.255'):
                            continue
                        
                        # Look up vendor from OUI database
                        vendor = self._oui_db.lookup(mac)
                        
                        devices.append((ip, mac, vendor))
        
        except Exception as e:
            logger.error(f"ARP scan error: {e}", exc_info=True)
        
        return devices
    
    # ========================================================================
    # dns-sd / mDNS / Bonjour
    # ========================================================================
    
    def _run_mdns_discovery(self) -> Dict[str, Tuple[str, List[str]]]:
        """Run mDNS service discovery.
        
        Returns: {hostname: (mdns_name, [services])}
        """
        discovered = {}
        
        if not self._has_dns_sd:
            return discovered
        
        # Services to discover
        services_to_check = [
            "_airplay._tcp",
            "_raop._tcp",
            "_googlecast._tcp",
            "_hap._tcp",
            "_printer._tcp",
            "_ipp._tcp",
            "_smb._tcp",
            "_companion-link._tcp",
        ]
        
        for service_type in services_to_check:
            try:
                # Run dns-sd with a short timeout via background process
                proc = subprocess.Popen(
                    ['dns-sd', '-B', service_type, 'local.'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                
                # Wait briefly and kill
                time.sleep(0.5)
                proc.terminate()
                
                try:
                    stdout, _ = proc.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stdout, _ = proc.communicate()
                
                # Parse output
                for line in stdout.split('\n'):
                    if 'Add' in line and 'local.' in line:
                        # Extract instance name (last column)
                        parts = line.split()
                        if len(parts) >= 7:
                            instance_name = ' '.join(parts[6:])
                            if instance_name and instance_name != '...STARTING...':
                                if instance_name not in discovered:
                                    discovered[instance_name] = (instance_name, [])
                                discovered[instance_name][1].append(service_type)
            
            except Exception:
                pass
        
        return discovered
    
    def _resolve_mdns_to_ip(self, mdns_name: str) -> Optional[str]:
        """Resolve mDNS name to IP address."""
        try:
            # Try standard resolution first
            hostname = f"{mdns_name}.local"
            ip = socket.gethostbyname(hostname)
            return ip
        except Exception:
            pass
        return None
    
    
    # ========================================================================
    # Hostname resolution
    # ========================================================================
    
    def _resolve_hostname(self, ip: str, timeout: float = None) -> Optional[str]:
        """Try to resolve hostname for an IP address."""
        timeout = timeout or NETWORK.HOSTNAME_RESOLVE_TIMEOUT
        try:
            socket.setdefaulttimeout(timeout)
            hostname, _, _ = socket.gethostbyaddr(ip)
            return hostname
        except Exception:
            return None
        finally:
            socket.setdefaulttimeout(None)
    
    def resolve_missing_hostnames(self) -> None:
        """Resolve hostnames for devices that don't have one yet.
        
        This is a batch operation - prefer using request_hostname_resolution()
        for lazy/on-demand resolution.
        """
        with self._lock:
            devices_to_resolve = [
                d for d in self._devices.values()
                if d.is_online and d.hostname is None
            ]
        
        for device in devices_to_resolve:
            hostname = self._resolve_hostname(device.ip_address, timeout=2.0)
            if hostname:
                self._apply_hostname_to_device(device.mac_address, hostname)
    
    def _apply_hostname_to_device(self, mac_address: str, hostname: str) -> None:
        """Apply resolved hostname to a device and update type inference."""
        with self._lock:
            if mac_address in self._devices:
                dev = self._devices[mac_address]
                dev.hostname = hostname
                
                # Re-infer device type with hostname
                device_type, os_hint, model_hint = infer_device_type(
                    dev.vendor, hostname, dev.services, dev.mdns_name
                )
                if device_type != DeviceType.UNKNOWN:
                    dev.device_type = device_type
                if os_hint:
                    dev.os_hint = os_hint
                if model_hint:
                    dev.model_hint = model_hint
    
    def request_hostname_resolution(self, mac_address: str) -> None:
        """Request lazy hostname resolution for a specific device.
        
        This is non-blocking - the hostname will be resolved in the background
        and the device will be updated when complete. Use this when you need
        a device's hostname but don't want to block the UI.
        """
        mac = normalize_mac(mac_address)
        
        with self._lock:
            # Check if device exists and needs resolution
            if mac not in self._devices:
                return
            device = self._devices[mac]
            if device.hostname is not None:
                return  # Already resolved
        
        # Add to pending queue
        with self._hostname_resolve_lock:
            self._pending_hostname_resolution.add(mac)
            
            # Start background resolution if not already running
            if not self._hostname_resolution_in_progress:
                self._hostname_resolution_in_progress = True
                threading.Thread(
                    target=self._process_hostname_queue,
                    daemon=True
                ).start()
    
    def _process_hostname_queue(self) -> None:
        """Process pending hostname resolution requests in the background.
        
        This is lazy resolution - devices are resolved one at a time with
        a small delay to avoid overwhelming DNS.
        """
        try:
            while True:
                # Get next MAC to resolve
                with self._hostname_resolve_lock:
                    if not self._pending_hostname_resolution:
                        self._hostname_resolution_in_progress = False
                        return
                    mac = self._pending_hostname_resolution.pop()
                
                # Get device IP
                with self._lock:
                    if mac not in self._devices:
                        continue
                    device = self._devices[mac]
                    if device.hostname is not None:
                        continue  # Already resolved
                    ip = device.ip_address
                
                # Resolve hostname (blocking but in background thread)
                hostname = self._resolve_hostname(ip, timeout=2.0)
                if hostname:
                    self._apply_hostname_to_device(mac, hostname)
                    logger.debug(f"Lazy resolved {ip} -> {hostname}")
                
                # Small delay between resolutions to be nice to DNS
                time.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Hostname resolution queue error: {e}", exc_info=True)
            with self._hostname_resolve_lock:
                self._hostname_resolution_in_progress = False
    
    def request_resolution_for_visible(self, macs: List[str]) -> None:
        """Request hostname resolution for a list of visible devices.
        
        Use this when displaying a list of devices - it will prioritize
        resolving hostnames for the visible devices first.
        """
        for mac in macs:
            self.request_hostname_resolution(mac)
    
    # ========================================================================
    # Main scan
    # ========================================================================
    
    def scan(self, force: bool = False, quick: bool = False) -> List[NetworkDevice]:
        """Scan the network for devices.
        
        Args:
            force: Force scan even if interval hasn't elapsed
            quick: Skip slow operations (mDNS, hostname resolution)
        
        Optimization: Only triggers mDNS/hostname resolution when new devices
        are detected, not on every scan interval.
        """
        current_time = time.time()
        
        if not force and (current_time - self._last_scan) < self._scan_interval:
            with self._lock:
                return list(self._devices.values())
        
        self._last_scan = current_time
        discovered = []
        new_devices_found = False
        
        # Scan ARP table with OUI vendor lookup
        arp_results = self._run_arp_with_oui()
        
        with self._lock:
            seen_macs = set()
            
            for ip, mac, vendor in arp_results:
                seen_macs.add(mac)
                custom_name = self._name_store.get_name(mac)
                mdns_name = self._mdns_names.get(mac)
                
                if mac in self._devices:
                    # Update existing device
                    device = self._devices[mac]
                    device.ip_address = ip
                    device.last_seen = datetime.now()
                    device.is_online = True
                    if vendor and not device.vendor:
                        device.vendor = vendor
                    if custom_name:
                        device.custom_name = custom_name
                    if mdns_name:
                        device.mdns_name = mdns_name
                else:
                    # New device detected!
                    new_devices_found = True
                    
                    device_type, os_hint, model_hint = infer_device_type(
                        vendor, None, [], mdns_name
                    )
                    
                    device = NetworkDevice(
                        ip_address=ip,
                        mac_address=mac,
                        vendor=vendor,
                        device_type=device_type,
                        os_hint=os_hint,
                        model_hint=model_hint,
                        custom_name=custom_name,
                        mdns_name=mdns_name,
                        first_seen=datetime.now(),
                        last_seen=datetime.now(),
                        is_online=True
                    )
                    self._devices[mac] = device
                
                discovered.append(self._devices[mac])
            
            # Mark unseen devices as offline
            for mac, device in self._devices.items():
                if mac not in seen_macs:
                    device.is_online = False
        
        # Only run expensive discovery when new devices are found (or forced)
        if not quick and (new_devices_found or force):
            # Run mDNS discovery in background
            threading.Thread(target=self._background_mdns_scan, daemon=True).start()
            # Resolve hostnames for new devices
            threading.Thread(target=self.resolve_missing_hostnames, daemon=True).start()
        
        return discovered
    
    def _background_mdns_scan(self) -> None:
        """Run mDNS discovery in background and update devices."""
        try:
            mdns_results = self._run_mdns_discovery()
            
            # Try to match mDNS names to devices by resolving to IP
            for mdns_name, (display_name, services) in mdns_results.items():
                ip = self._resolve_mdns_to_ip(mdns_name)
                if ip:
                    with self._lock:
                        # Find device with this IP
                        for device in self._devices.values():
                            if device.ip_address == ip:
                                device.mdns_name = display_name
                                device.services = list(set(device.services + services))
                                self._mdns_names[device.mac_address] = display_name
                                
                                # Re-infer device type with services
                                device_type, os_hint, model_hint = infer_device_type(
                                    device.vendor, device.hostname, 
                                    device.services, display_name
                                )
                                if device_type != DeviceType.UNKNOWN:
                                    device.device_type = device_type
                                if os_hint:
                                    device.os_hint = os_hint
                                if model_hint:
                                    device.model_hint = model_hint
                                break
        except Exception as e:
            logger.error(f"mDNS scan error: {e}", exc_info=True)
    
    # ========================================================================
    # Accessors
    # ========================================================================
    
    def get_all_devices(self) -> List[NetworkDevice]:
        """Get all known devices."""
        with self._lock:
            return list(self._devices.values())
    
    def get_online_devices(self) -> List[NetworkDevice]:
        """Get only online devices."""
        with self._lock:
            return [d for d in self._devices.values() if d.is_online]
    
    def get_device_count(self) -> Tuple[int, int]:
        """Get (online_count, total_count) of devices."""
        with self._lock:
            total = len(self._devices)
            online = sum(1 for d in self._devices.values() if d.is_online)
            return online, total
    
    def clear_devices(self) -> None:
        """Clear all known devices."""
        with self._lock:
            self._devices.clear()
