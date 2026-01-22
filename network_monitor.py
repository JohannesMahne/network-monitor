#!/usr/bin/env python3
"""
Network Monitor - macOS Menu Bar Application
Monitors network traffic, tracks daily usage per connection, and logs issues.
"""
import rumps
import threading
import time
import io
import os
import sys
import fcntl
import tempfile
import atexit
from datetime import datetime
from typing import Optional, List, Tuple
from collections import deque
from pathlib import Path

from monitor.network import NetworkStats, format_bytes
from monitor.connection import ConnectionDetector, ConnectionInfo
from monitor.issues import IssueDetector, IssueType
from monitor.scanner import NetworkScanner, NetworkDevice
from monitor.traffic import TrafficMonitor, format_traffic_bytes
from storage.sqlite_store import SQLiteStore
from storage.settings import get_settings_manager, ConnectionBudget, BudgetPeriod
from service.launch_agent import get_launch_agent_manager
from config import setup_logging, get_logger, INTERVALS, THRESHOLDS, STORAGE, COLORS, UI

# Hide dock icon (menu bar only app)
from Foundation import NSBundle
info = NSBundle.mainBundle().infoDictionary()
info["LSUIElement"] = "1"

# For colored menu bar icons
from PIL import Image, ImageDraw

# Note: matplotlib is only imported if PIL sparklines fail (fallback)
# PIL is much faster and uses less memory for sparklines


class SingletonLock:
    """Ensures only one instance of the application can run at a time.
    
    Uses file locking (fcntl) which is automatically released when the
    process exits, even on crash.
    """
    
    def __init__(self, lock_name: str = "network-monitor"):
        self._lock_file = Path(tempfile.gettempdir()) / f"{lock_name}.lock"
        self._lock_fd = None
    
    def acquire(self) -> bool:
        """Try to acquire the singleton lock.
        
        Returns:
            True if lock acquired (we're the only instance),
            False if another instance is already running.
        """
        try:
            self._lock_fd = open(self._lock_file, 'w')
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write our PID for debugging
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()
            return True
        except (IOError, OSError):
            # Lock is held by another process
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            return False
    
    def release(self):
        """Release the singleton lock."""
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
            except Exception:
                pass  # nosec B110 - Cleanup code, safe to ignore errors
            self._lock_fd = None


# Global singleton lock
_singleton_lock = SingletonLock()


def create_status_icon(color: str, size: int = 18) -> str:
    """Create a colored circle icon for the menu bar. Returns path to temp file."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Color mapping - use constants
    colors = {
        'green': COLORS.GREEN_RGBA,
        'yellow': COLORS.YELLOW_RGBA,
        'red': COLORS.RED_RGBA,
        'gray': COLORS.GRAY_RGBA,
    }
    fill_color = colors.get(color, colors['gray'])
    
    # Draw filled circle with slight padding
    padding = 2
    draw.ellipse([padding, padding, size - padding, size - padding], fill=fill_color)
    
    # Save to temp file
    temp_dir = Path(tempfile.gettempdir()) / STORAGE.ICON_TEMP_DIR
    temp_dir.mkdir(exist_ok=True)
    icon_path = temp_dir / f'status_{color}.png'
    img.save(icon_path, 'PNG')
    
    return str(icon_path)


logger = get_logger(__name__)


class NetworkMonitorApp(rumps.App):
    """Main menu bar application for network monitoring."""
    
    UPDATE_INTERVAL = INTERVALS.UPDATE_SECONDS
    
    # History size for sparkline graph (fits nicely in menu)
    HISTORY_SIZE = THRESHOLDS.SPARKLINE_HISTORY_SIZE
    
    def __init__(self):
        super().__init__(
            name="NetMon",
            title="--",  # Will be updated based on settings
            quit_button=None
        )
        
        # Initialize components
        self.network_stats = NetworkStats()
        self.connection_detector = ConnectionDetector()
        self.issue_detector = IssueDetector()
        self.network_scanner = NetworkScanner()
        self.traffic_monitor = TrafficMonitor()
        self.store = SQLiteStore()
        self.settings = get_settings_manager(self.store.data_dir)
        
        # Track session data
        self._session_bytes_sent = 0
        self._session_bytes_recv = 0
        self._last_connection_key = ""
        self._connection_start_bytes = (0, 0)
        self._last_device_scan = 0
        self._device_scan_interval = INTERVALS.DEVICE_SCAN_SECONDS
        self._last_traffic_update = 0
        self._traffic_update_interval = INTERVALS.TRAFFIC_UPDATE_SECONDS
        self._last_latency_check = 0
        self._latency_check_interval = INTERVALS.LATENCY_CHECK_SECONDS
        self._current_latency = None
        self._latency_samples = []
        
        # History for sparkline graphs
        self._upload_history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._download_history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._latency_history: deque = deque(maxlen=self.HISTORY_SIZE)
        
        # Adaptive update intervals
        self._activity_samples: deque = deque(maxlen=INTERVALS.ACTIVITY_CHECK_SAMPLES)
        self._current_update_interval: float = INTERVALS.UPDATE_NORMAL_SECONDS
        
        # Budget notification tracking (avoid repeated notifications)
        self._budget_warning_notified: set = set()  # connection keys that got warning
        self._budget_exceeded_notified: set = set()  # connection keys that got exceeded
        
        # VPN detection
        self._vpn_active: bool = False
        self._vpn_name: Optional[str] = None
        self._last_vpn_check: float = 0
        self._vpn_check_interval: float = 10.0  # Check every 10 seconds
        
        # Network quality score tracking
        self._packet_loss_samples: deque = deque(maxlen=10)
        self._quality_score: Optional[int] = None
        
        # Track temp directories for cleanup
        self._temp_dirs = [
            Path(tempfile.gettempdir()) / STORAGE.ICON_TEMP_DIR,
            Path(tempfile.gettempdir()) / STORAGE.SPARKLINE_TEMP_DIR,
        ]
        
        logger.info("NetworkMonitorApp initializing...")
        
        # Register cleanup on exit
        atexit.register(self._cleanup_temp_files)
        
        # Build menu
        self._build_menu()
        
        # Start monitoring
        self._running = True
        self._start_monitoring()
        
        # Trigger initial device scan immediately
        threading.Thread(target=self._initial_device_scan, daemon=True).start()
    
    def _build_menu(self):
        """Build the dropdown menu - standard macOS style."""
        
        # === SPARKLINE GRAPHS (no header, graphs speak for themselves) ===
        self.menu_graph_upload = rumps.MenuItem("↑ ─────────────────────")
        self.menu_graph_download = rumps.MenuItem("↓ ─────────────────────")
        self.menu_graph_latency = rumps.MenuItem("● ─────────────────────")
        
        # === CURRENT STATS ===
        self.menu_connection = rumps.MenuItem("Detecting")
        self.menu_speed = rumps.MenuItem("↑ --  ↓ --")
        self.menu_latency = rumps.MenuItem("Latency: --")
        self.menu_quality = rumps.MenuItem("Quality: --")  # Network quality score
        self.menu_today = rumps.MenuItem("Today: ↑ --  ↓ --")
        
        # === BUDGET STATUS (shown when budget is set) ===
        self.menu_budget = rumps.MenuItem("Budget: Not set")
        
        # === NETWORK DEVICES (dynamically populated) ===
        self.menu_devices = rumps.MenuItem("Devices")
        
        # === TOP APPS (dynamically populated) ===
        self.menu_apps = rumps.MenuItem("Apps")
        
        # === HISTORY SUBMENU ===
        self.menu_history = rumps.MenuItem("History")
        self.menu_week = rumps.MenuItem("Week: ↑ --  ↓ --")
        self.menu_month = rumps.MenuItem("Month: ↑ --  ↓ --")
        self.menu_daily_history = rumps.MenuItem("Daily Breakdown")
        self.menu_connection_history = rumps.MenuItem("By Connection")
        
        self.menu_history.add(self.menu_week)
        self.menu_history.add(self.menu_month)
        self.menu_history.add(rumps.separator)
        self.menu_history.add(self.menu_daily_history)
        self.menu_history.add(self.menu_connection_history)
        
        # === RECENT EVENTS ===
        self.menu_events = rumps.MenuItem("Recent Events")
        
        # === SETTINGS SUBMENU ===
        self.menu_settings = rumps.MenuItem("Settings")
        
        # Launch at login
        self.launch_manager = get_launch_agent_manager()
        self.menu_launch_login = rumps.MenuItem(
            self.launch_manager.get_status(),
            callback=self._toggle_launch_at_login
        )
        self.menu_settings.add(self.menu_launch_login)
        self.menu_settings.add(rumps.separator)
        
        # Title display options
        self.menu_title_display = rumps.MenuItem("Menu Bar Display")
        current_mode = self.settings.get_title_display()
        for mode, label in self.settings.get_title_display_options():
            check = "✓ " if mode == current_mode else "   "
            item = rumps.MenuItem(f"{check}{label}", callback=lambda s, m=mode: self._set_title_display(m))
            self.menu_title_display.add(item)
        self.menu_settings.add(self.menu_title_display)
        self.menu_settings.add(rumps.separator)
        
        # Budget management - will be built dynamically
        self.menu_budgets = rumps.MenuItem("Data Budgets")
        self._build_budget_menu()
        self.menu_settings.add(self.menu_budgets)
        
        # === ACTIONS SUBMENU ===
        self.menu_actions = rumps.MenuItem("Actions")
        self.menu_rescan = rumps.MenuItem("Rescan Network", callback=self._rescan_network)
        self.menu_reset_session = rumps.MenuItem("Reset Session", callback=self._reset_session)
        self.menu_reset_today = rumps.MenuItem("Reset Today", callback=self._reset_today)
        self.menu_data_location = rumps.MenuItem("Open Data Folder", callback=self._open_data_folder)
        
        # Export submenu
        self.menu_export = rumps.MenuItem("Export Data")
        self.menu_export.add(rumps.MenuItem("Export as CSV...", callback=self._export_csv))
        self.menu_export.add(rumps.MenuItem("Export as JSON...", callback=self._export_json))
        
        # Backup/Restore submenu
        self.menu_backup = rumps.MenuItem("Backup & Restore")
        self.menu_backup.add(rumps.MenuItem("Create Backup...", callback=self._create_backup))
        self.menu_backup.add(rumps.MenuItem("Restore from Backup...", callback=self._restore_backup))
        self.menu_backup.add(rumps.separator)
        self.menu_backup.add(rumps.MenuItem("Database Info...", callback=self._show_database_info))
        self.menu_backup.add(rumps.MenuItem("Run Cleanup Now", callback=self._run_cleanup))
        
        self.menu_actions.add(self.menu_rescan)
        self.menu_actions.add(rumps.separator)
        self.menu_actions.add(self.menu_reset_session)
        self.menu_actions.add(self.menu_reset_today)
        self.menu_actions.add(rumps.separator)
        self.menu_actions.add(self.menu_export)
        self.menu_actions.add(self.menu_backup)
        self.menu_actions.add(self.menu_data_location)
        
        # === BUILD MENU (standard macOS layout) ===
        # Note: VPN status is added dynamically when VPN is detected
        self.menu = [
            self.menu_graph_upload,
            self.menu_graph_download,
            self.menu_graph_latency,
            rumps.separator,
            self.menu_connection,
            self.menu_speed,
            self.menu_latency,
            self.menu_quality,
            self.menu_today,
            self.menu_budget,
            rumps.separator,
            self.menu_devices,
            self.menu_apps,
            self.menu_history,
            self.menu_events,
            rumps.separator,
            self.menu_settings,
            self.menu_actions,
            rumps.separator,
            rumps.MenuItem("About", callback=self._show_about),
            rumps.MenuItem("Quit", callback=self._quit)
        ]
    
    def _start_monitoring(self):
        """Initialize monitoring and start timer."""
        self.network_stats.initialize()
        # Start the update timer (runs on main thread) with adaptive interval
        self._update_timer = rumps.Timer(self._timer_callback, self._current_update_interval)
        self._update_timer.start()
    
    def _timer_callback(self, timer):
        """Timer callback (runs on main thread - thread-safe for UI)."""
        if not self._running:
            return
        try:
            self._update()
            # Adjust timer interval based on activity
            self._adjust_update_interval()
        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
    
    def _calculate_adaptive_interval(self) -> float:
        """Calculate the appropriate update interval based on recent activity.
        
        Returns faster intervals during high network activity, slower during idle.
        """
        if not self._activity_samples:
            return INTERVALS.UPDATE_NORMAL_SECONDS
        
        # Average recent activity
        avg_activity = sum(self._activity_samples) / len(self._activity_samples)
        
        if avg_activity > INTERVALS.ACTIVITY_HIGH_THRESHOLD:
            return INTERVALS.UPDATE_FAST_SECONDS
        elif avg_activity < INTERVALS.ACTIVITY_LOW_THRESHOLD:
            return INTERVALS.UPDATE_SLOW_SECONDS
        else:
            return INTERVALS.UPDATE_NORMAL_SECONDS
    
    def _adjust_update_interval(self):
        """Adjust the timer interval based on current activity level."""
        new_interval = self._calculate_adaptive_interval()
        
        # Only update if interval has changed significantly (avoid constant restarts)
        if abs(new_interval - self._current_update_interval) > 0.5:
            self._current_update_interval = new_interval
            # Update timer interval
            self._update_timer.interval = new_interval
            logger.debug(f"Adjusted update interval to {new_interval}s")
    
    def _update(self):
        """Update all statistics and UI."""
        import time as time_module
        
        # Get current connection info
        conn = self.connection_detector.get_current_connection()
        conn_key = self.connection_detector.get_connection_key()
        
        # Check for connection changes
        if conn_key != self._last_connection_key:
            if self._last_connection_key:
                self.issue_detector.log_connection_change(
                    self._last_connection_key, conn_key
                )
            self._last_connection_key = conn_key
            self._connection_start_bytes = self.network_stats.get_session_totals()
        
        # Check connectivity issues
        self.issue_detector.check_connectivity(conn.is_connected)
        
        # Scan for network devices periodically
        current_time = time_module.time()
        if current_time - self._last_device_scan >= self._device_scan_interval:
            self._last_device_scan = current_time
            # Run scan in background to avoid blocking
            threading.Thread(target=self._scan_devices, daemon=True).start()
        
        # Get network stats
        stats = self.network_stats.get_current_stats()
        
        if stats:
            # Record history for sparklines
            self._upload_history.append(stats.upload_speed)
            self._download_history.append(stats.download_speed)
            if self._current_latency is not None:
                self._latency_history.append(self._current_latency)
            
            # Record activity for adaptive intervals
            total_activity = stats.upload_speed + stats.download_speed
            self._activity_samples.append(total_activity)
            
            # Update menu bar title based on settings
            self._update_title(stats)
            
            # Update sparkline graphs
            self._update_sparklines(stats)
            
            # Check for latency issues periodically
            self.issue_detector.check_latency()
            
            # Get averages and peaks
            avg_up, avg_down = self.network_stats.get_average_speeds()
            peak_up, peak_down = self.network_stats.get_peak_speeds()
            
            # Check for speed drops
            total_speed = stats.download_speed + stats.upload_speed
            avg_total = avg_up + avg_down
            self.issue_detector.check_speed_drop(total_speed, avg_total)
            
            # Calculate session totals for current connection
            session_sent, session_recv = self.network_stats.get_session_totals()
            conn_sent = session_sent - self._connection_start_bytes[0]
            conn_recv = session_recv - self._connection_start_bytes[1]
            
            # Update persistent storage
            if conn.is_connected:
                self.store.update_stats(
                    conn_key,
                    conn_sent,
                    conn_recv,
                    peak_up,
                    peak_down
                )
            
            # Update menu items (on main thread via rumps timer)
            self._update_menu(conn, stats, avg_up, avg_down, peak_up, peak_down,
                            conn_sent, conn_recv)
    
    def _scan_devices(self):
        """Scan for network devices (runs in background thread)."""
        try:
            self.network_scanner.scan()
            # Occasionally resolve hostnames for newly discovered devices
            self.network_scanner.resolve_missing_hostnames()
        except Exception as e:
            logger.error(f"Device scan error: {e}", exc_info=True)
    
    def _initial_device_scan(self):
        """Initial device scan on startup - quick mode for fast results."""
        try:
            logger.info("Starting initial device scan...")
            # Quick scan first for immediate results
            self.network_scanner.scan(force=True, quick=True)
            self._last_device_scan = time.time()
            
            # Then do a full scan in background for more devices
            time.sleep(2)
            self.network_scanner.scan(force=True, quick=False)
            
            # Resolve hostnames for better device identification
            time.sleep(1)
            self.network_scanner.resolve_missing_hostnames()
            logger.info("Initial device scan completed")
        except Exception as e:
            logger.error(f"Initial device scan error: {e}", exc_info=True)
    
    def _create_gauge_icon(self, color: str, size: int = 18) -> str:
        """Create a gauge/speedometer icon colored by latency status.
        
        Inspired by Font Awesome gauge-high icon.
        Returns path to PNG file.
        """
        from PIL import Image, ImageDraw
        import math
        
        # Color mapping - use constants
        colors = {
            "green": COLORS.GREEN_HEX,
            "yellow": COLORS.YELLOW_HEX,
            "red": COLORS.RED_HEX,
            "gray": COLORS.GRAY_HEX,
        }
        fill_color = colors.get(color, colors["gray"])
        
        # Create image with transparency
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Draw gauge arc (speedometer shape)
        padding = 2
        bbox = [padding, padding + 2, size - padding, size - padding + 2]
        
        # Draw the gauge arc (semi-circle at top)
        draw.arc(bbox, start=180, end=0, fill=fill_color, width=2)
        
        # Draw needle based on "speed" (pointing right for good, left for bad)
        center_x = size // 2
        center_y = size // 2 + 2
        needle_len = size // 2 - 4
        
        # Needle angle: green=45° (right), yellow=90° (up), red=135° (left)
        if color == "green":
            angle = math.radians(45)
        elif color == "yellow":
            angle = math.radians(90)
        else:
            angle = math.radians(135)
        
        needle_x = center_x + int(needle_len * math.cos(math.pi - angle))
        needle_y = center_y - int(needle_len * math.sin(math.pi - angle))
        
        draw.line([(center_x, center_y), (needle_x, needle_y)], fill=fill_color, width=2)
        
        # Draw center dot
        dot_r = 2
        draw.ellipse([center_x - dot_r, center_y - dot_r, 
                      center_x + dot_r, center_y + dot_r], fill=fill_color)
        
        # Save to temp file
        temp_dir = Path(tempfile.gettempdir()) / STORAGE.ICON_TEMP_DIR
        temp_dir.mkdir(exist_ok=True)
        img_path = temp_dir / f'gauge_{color}.png'
        img.save(str(img_path), 'PNG')
        
        return str(img_path)
    
    def _update_title(self, stats):
        """Update menu bar title and icon based on settings.
        
        Uses gauge icon colored by latency status:
        - Green: Good (latency < 50ms)
        - Yellow: OK (latency 50-100ms)  
        - Red: Poor (latency > 100ms)
        """
        display_mode = self.settings.get_title_display()
        
        # Get status color based on latency
        if self._current_latency is not None:
            color = self.settings.get_latency_color(self._current_latency)
        else:
            color = "gray"
        
        # Set the gauge icon
        try:
            icon_path = self._create_gauge_icon(color)
            self.icon = icon_path
        except Exception as e:
            # Fallback to emoji if icon creation fails
            logger.debug(f"Icon creation failed, using fallback: {e}")
        
        # Format title based on display mode (text only, icon provides color)
        if display_mode == "latency":
            # Latency mode: just ms value
            if self._current_latency is not None:
                self.title = f"{self._current_latency:.0f}ms"
            else:
                self.title = "--"
        
        elif display_mode == "session":
            # Session data mode: up/down for session
            session_sent, session_recv = self.network_stats.get_session_totals()
            self.title = f"↑{format_bytes(session_sent)} ↓{format_bytes(session_recv)}"
        
        elif display_mode == "speed":
            # Speed mode: current up/down speed
            if stats:
                up = format_bytes(stats.upload_speed, speed=True)
                down = format_bytes(stats.download_speed, speed=True)
                self.title = f"↑{up} ↓{down}"
            else:
                self.title = "↑-- ↓--"
        
        elif display_mode == "devices":
            # Device count mode
            online, total = self.network_scanner.get_device_count()
            self.title = f"{online} devices"
        
        elif display_mode == "quality":
            # Quality score mode
            if self._quality_score is not None:
                self.title = f"{self._quality_score}%"
            else:
                self.title = "--"
        
        else:
            # Default to latency
            if self._current_latency is not None:
                self.title = f"{self._current_latency:.0f}ms"
            else:
                self.title = "--"
    
    def _update_menu(self, conn: ConnectionInfo, stats, avg_up: float, avg_down: float,
                    peak_up: float, peak_down: float, session_sent: int, session_recv: int):
        """Update menu item text."""
        # VPN status (check first so we can show in connection line)
        self._update_vpn_status()
        
        # Connection info (with VPN indicator if active)
        if conn.is_connected:
            name = conn.name[:22] if len(conn.name) <= 22 else conn.name[:19] + "..."
            ip = conn.ip_address or ""
            if self._vpn_active:
                self.menu_connection.title = f"🔒 {name} ({ip})"
            else:
                self.menu_connection.title = f"{name} ({ip})"
        else:
            self.menu_connection.title = "Disconnected"
        
        # Speed (no icon - cleaner)
        self.menu_speed.title = f"↑ {format_bytes(stats.upload_speed, True)}  ↓ {format_bytes(stats.download_speed, True)}"
        
        # Update latency display
        self._update_latency()
        
        # Update network quality score
        self._update_quality_score()
        
        today_sent, today_recv = self.store.get_today_totals()
        self.menu_today.title = f"Today: ↑ {format_bytes(today_sent)}  ↓ {format_bytes(today_recv)}"
        
        # Update budget status (with notifications)
        self._update_budget(conn, today_sent, today_recv)
        
        # Update history section
        self._update_history()
        
        # Update top apps
        self._update_top_apps()
        
        # Update top devices
        self._update_top_devices()
        
        # Update events
        self._update_events()
    
    def _create_sparkline_image(self, values: list, color: str = '#007AFF', 
                                  width: int = 120, height: int = 16) -> str:
        """Generate a PIL-based sparkline image and return path to PNG file.
        
        Uses PIL/Pillow for faster rendering and lower memory usage than matplotlib.
        Falls back to matplotlib if PIL rendering fails.
        """
        if not values or len(values) < 2:
            values = [0, 0]
        
        try:
            return self._create_sparkline_pil(values, color, width, height)
        except Exception as e:
            logger.debug(f"PIL sparkline failed, falling back to matplotlib: {e}")
            return self._create_sparkline_matplotlib(values, color, width, height)
    
    def _create_sparkline_pil(self, values: list, color: str = '#007AFF',
                               width: int = 120, height: int = 16) -> str:
        """Create sparkline using PIL/Pillow - fast and lightweight."""
        from PIL import Image, ImageDraw
        import hashlib
        
        # Create image with transparency
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Convert hex color to RGB tuple
        if color.startswith('#'):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
        else:
            r, g, b = 0, 122, 255  # Default blue
        
        line_color = (r, g, b, 255)
        fill_color = (r, g, b, 40)  # Semi-transparent fill
        
        # Calculate scaling
        padding_x = 2
        padding_y = 2
        graph_width = width - 2 * padding_x
        graph_height = height - 2 * padding_y
        
        max_val = max(values) if max(values) > 0 else 1
        min_val = min(values)
        val_range = max_val - min_val if max_val != min_val else 1
        
        # Calculate points
        points = []
        for i, val in enumerate(values):
            x = padding_x + (i / (len(values) - 1)) * graph_width
            # Normalize value to graph height (invert Y since PIL coords are top-down)
            normalized = (val - min_val) / val_range
            y = padding_y + (1 - normalized) * graph_height
            points.append((x, y))
        
        # Draw filled area under the line
        if len(points) >= 2:
            fill_points = list(points)
            fill_points.append((points[-1][0], height - padding_y))
            fill_points.append((points[0][0], height - padding_y))
            draw.polygon(fill_points, fill=fill_color)
        
        # Draw the line
        if len(points) >= 2:
            draw.line(points, fill=line_color, width=1)
        
        # Draw last point marker (small circle)
        if points:
            last_x, last_y = points[-1]
            r_dot = 2
            draw.ellipse([last_x - r_dot, last_y - r_dot, 
                         last_x + r_dot, last_y + r_dot], fill=line_color)
        
        # Save to temp file
        temp_dir = Path(tempfile.gettempdir()) / STORAGE.SPARKLINE_TEMP_DIR
        temp_dir.mkdir(exist_ok=True)
        
        # Use hash of values for filename to enable caching
        # nosec B324 - MD5 used for cache key, not security
        val_hash = hashlib.md5(str(values).encode(), usedforsecurity=False).hexdigest()[:8]
        img_path = temp_dir / f'spark_{color.replace("#", "")}_{val_hash}.png'
        
        img.save(str(img_path), 'PNG')
        return str(img_path)
    
    def _create_sparkline_matplotlib(self, values: list, color: str = '#007AFF',
                                      width: int = 120, height: int = 16) -> str:
        """Create sparkline using matplotlib - fallback for complex cases."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import hashlib
        
        # Create figure with exact pixel dimensions
        dpi = 72
        fig, ax = plt.subplots(figsize=(width/dpi, height/dpi), dpi=dpi)
        
        # Plot the line - thin and smooth
        ax.plot(values, color=color, linewidth=1.0, solid_capstyle='round')
        
        # Fill under the line with transparency
        ax.fill_between(range(len(values)), values, alpha=0.15, color=color)
        
        # Mark the last point
        if values:
            ax.plot(len(values)-1, values[-1], 'o', color=color, markersize=2)
        
        # Remove all axes and borders (pure sparkline)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        
        # Tight layout with no padding
        ax.margins(x=0.02, y=0.1)
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
        
        # Save to temp file
        temp_dir = Path(tempfile.gettempdir()) / STORAGE.SPARKLINE_TEMP_DIR
        temp_dir.mkdir(exist_ok=True)
        
        # nosec B324 - MD5 used for cache key, not security
        val_hash = hashlib.md5(str(values).encode(), usedforsecurity=False).hexdigest()[:8]
        img_path = temp_dir / f'spark_{color.replace("#", "")}_{val_hash}.png'
        
        fig.savefig(img_path, transparent=True, dpi=dpi, pad_inches=0)
        plt.close(fig)
        
        return str(img_path)
    
    def _set_menu_image(self, menu_item, image_path: str):
        """Set an image on a menu item using AppKit."""
        try:
            from AppKit import NSImage
            image = NSImage.alloc().initWithContentsOfFile_(image_path)
            if image:
                menu_item._menuitem.setImage_(image)
        except Exception as e:
            logger.debug(f"Failed to set menu image: {e}")  # Non-critical UI feature
    
    def _update_sparklines(self, stats):
        """Update the sparkline graph display with matplotlib line graphs."""
        # Colors for each metric - use constants
        up_color = COLORS.UPLOAD_COLOR
        down_color = COLORS.DOWNLOAD_COLOR
        lat_color = COLORS.LATENCY_COLOR
        
        # Upload sparkline
        up_cur = stats.upload_speed if stats else 0
        if list(self._upload_history):
            up_img = self._create_sparkline_image(list(self._upload_history), up_color)
            self._set_menu_image(self.menu_graph_upload, up_img)
        self.menu_graph_upload.title = f"  ↑  {format_bytes(up_cur, True)}"
        
        # Download sparkline
        down_cur = stats.download_speed if stats else 0
        if list(self._download_history):
            down_img = self._create_sparkline_image(list(self._download_history), down_color)
            self._set_menu_image(self.menu_graph_download, down_img)
        self.menu_graph_download.title = f"  ↓  {format_bytes(down_cur, True)}"
        
        # Latency sparkline
        lat_cur = self._current_latency if self._current_latency else 0
        if list(self._latency_history):
            lat_img = self._create_sparkline_image(list(self._latency_history), lat_color)
            self._set_menu_image(self.menu_graph_latency, lat_img)
        self.menu_graph_latency.title = f"  ●  {lat_cur:.0f}ms"
    
    def _update_latency(self):
        """Update latency display."""
        import time as time_module
        
        current_time = time_module.time()
        
        # Only check latency periodically (it's slow)
        if current_time - self._last_latency_check >= self._latency_check_interval:
            self._last_latency_check = current_time
            
            # Run ping in background to avoid blocking
            threading.Thread(target=self._check_latency_background, daemon=True).start()
        
        # Update display with current value
        if self._current_latency is not None:
            latency = self._current_latency
            
            # Calculate average if we have samples
            if self._latency_samples:
                avg_latency = sum(self._latency_samples) / len(self._latency_samples)
                self.menu_latency.title = f"Latency: {latency:.0f}ms (avg {avg_latency:.0f}ms)"
            else:
                self.menu_latency.title = f"Latency: {latency:.0f}ms"
        else:
            self.menu_latency.title = "Latency: --"
    
    def _check_latency_background(self):
        """Check latency in background thread."""
        try:
            latency = self.issue_detector.get_current_latency()
            if latency is not None:
                self._current_latency = latency
                self._latency_samples.append(latency)
                # Keep last N samples for average
                if len(self._latency_samples) > THRESHOLDS.LATENCY_SAMPLE_COUNT:
                    self._latency_samples.pop(0)
        except Exception as e:
            logger.error(f"Latency check error: {e}", exc_info=True)
    
    def _update_vpn_status(self):
        """Update VPN status detection.
        
        VPN status is shown inline with connection info.
        """
        import time as time_module
        
        current_time = time_module.time()
        
        # Only check VPN periodically
        if current_time - self._last_vpn_check >= self._vpn_check_interval:
            self._last_vpn_check = current_time
            
            vpn_active, vpn_name = self.connection_detector.detect_vpn()
            self._vpn_active = vpn_active
            self._vpn_name = vpn_name if vpn_active else None
    
    def _update_quality_score(self):
        """Update network quality score.
        
        Score is 0-100 based on:
        - Latency (40% weight): <30ms=100, >200ms=0
        - Jitter (30% weight): Latency variance
        - Speed consistency (30% weight): Based on activity samples
        """
        if not self._latency_samples:
            self.menu_quality.title = "Quality: ⏳ measuring..."
            self._quality_score = None
            return
        
        # Need at least 1 sample for basic score, 3+ for full accuracy
        sample_count = len(self._latency_samples)
        
        # Calculate latency score (40%)
        avg_latency = sum(self._latency_samples) / len(self._latency_samples)
        if avg_latency <= 30:
            latency_score = 100
        elif avg_latency >= 200:
            latency_score = 0
        else:
            # Linear interpolation between 30ms (100) and 200ms (0)
            latency_score = max(0, 100 - ((avg_latency - 30) / 170) * 100)
        
        # Calculate jitter score (30%) - lower variance is better
        if len(self._latency_samples) >= 2:
            mean = avg_latency
            variance = sum((x - mean) ** 2 for x in self._latency_samples) / len(self._latency_samples)
            jitter = variance ** 0.5  # Standard deviation
            
            if jitter <= 5:
                jitter_score = 100
            elif jitter >= 50:
                jitter_score = 0
            else:
                jitter_score = max(0, 100 - ((jitter - 5) / 45) * 100)
        else:
            jitter_score = 50  # Unknown
        
        # Calculate consistency score (30%) - based on activity variance
        if self._activity_samples and len(self._activity_samples) >= 3:
            activity_list = list(self._activity_samples)
            if max(activity_list) > 0:
                # Coefficient of variation (lower is more consistent)
                mean_activity = sum(activity_list) / len(activity_list)
                if mean_activity > 0:
                    std_activity = (sum((x - mean_activity) ** 2 for x in activity_list) / len(activity_list)) ** 0.5
                    cv = std_activity / mean_activity
                    # CV of 0 = 100 score, CV of 2+ = 0 score
                    consistency_score = max(0, 100 - cv * 50)
                else:
                    consistency_score = 100  # No activity = consistent
            else:
                consistency_score = 100
        else:
            consistency_score = 50  # Unknown
        
        # Weighted average
        self._quality_score = int(
            latency_score * 0.4 +
            jitter_score * 0.3 +
            consistency_score * 0.3
        )
        
        # Display with color indicator
        if self._quality_score >= 80:
            indicator = "🟢"
            label = "Excellent"
        elif self._quality_score >= 60:
            indicator = "🟡"
            label = "Good"
        elif self._quality_score >= 40:
            indicator = "🟠"
            label = "Fair"
        else:
            indicator = "🔴"
            label = "Poor"
        
        self.menu_quality.title = f"Quality: {indicator} {self._quality_score}% ({label})"
        
        # Check for quality drops and log as event
        jitter = None
        if len(self._latency_samples) >= 2:
            mean = avg_latency
            variance = sum((x - mean) ** 2 for x in self._latency_samples) / len(self._latency_samples)
            jitter = variance ** 0.5
        
        quality_issue = self.issue_detector.check_quality_drop(
            self._quality_score, 
            latency=avg_latency,
            jitter=jitter
        )
        if quality_issue:
            logger.warning(f"Quality drop detected: {quality_issue.description}")
    
    def _update_history(self):
        """Update history section with weekly and monthly stats."""
        # Get weekly totals
        weekly = self.store.get_weekly_totals()
        self.menu_week.title = f"Week: ↑ {format_bytes(weekly['sent'])}  ↓ {format_bytes(weekly['recv'])}"
        
        # Get monthly totals
        monthly = self.store.get_monthly_totals()
        self.menu_month.title = f"Month: ↑ {format_bytes(monthly['sent'])}  ↓ {format_bytes(monthly['recv'])}"
        
        # Update daily breakdown submenu
        self._update_daily_history()
        
        # Update connection history submenu
        self._update_connection_history(weekly, monthly)
    
    def _update_daily_history(self):
        """Update daily breakdown submenu."""
        self._safe_menu_clear(self.menu_daily_history)
        
        daily = self.store.get_daily_totals(days=7)
        
        if not daily or all(d['sent'] == 0 and d['recv'] == 0 for d in daily):
            self.menu_daily_history.add(rumps.MenuItem("No history yet"))
            return
        
        for day_data in daily:
            date_str = day_data['date']
            # Format date nicely
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(date_str)
                if date_str == datetime.now().strftime('%Y-%m-%d'):
                    day_label = "Today"
                elif date_str == (datetime.now() - __import__('datetime').timedelta(days=1)).strftime('%Y-%m-%d'):
                    day_label = "Yesterday"
                else:
                    day_label = dt.strftime('%a %d')  # e.g., "Mon 20"
            except:
                day_label = date_str
            
            sent = day_data['sent']
            recv = day_data['recv']
            
            if sent > 0 or recv > 0:
                title = f"{day_label}: ↑{format_bytes(sent)} ↓{format_bytes(recv)}"
            else:
                title = f"{day_label}: No data"
            
            self.menu_daily_history.add(rumps.MenuItem(title))
    
    def _update_connection_history(self, weekly: dict, monthly: dict):
        """Update per-connection history submenu."""
        self._safe_menu_clear(self.menu_connection_history)
        
        # Get unique connections from monthly data
        connections = monthly.get('by_connection', {})
        
        if not connections:
            self.menu_connection_history.add(rumps.MenuItem("No connections recorded"))
            return
        
        # Sort by total traffic
        sorted_conns = sorted(
            connections.items(),
            key=lambda x: x[1]['sent'] + x[1]['recv'],
            reverse=True
        )
        
        for conn_key, stats in sorted_conns[:10]:
            # Create submenu for each connection
            conn_menu = rumps.MenuItem(f"{conn_key}")
            
            # Add monthly total
            conn_menu.add(rumps.MenuItem(
                f"Month: ↑{format_bytes(stats['sent'])} ↓{format_bytes(stats['recv'])}"
            ))
            
            # Add weekly total if available
            weekly_stats = weekly.get('by_connection', {}).get(conn_key, {'sent': 0, 'recv': 0})
            conn_menu.add(rumps.MenuItem(
                f"Week: ↑{format_bytes(weekly_stats['sent'])} ↓{format_bytes(weekly_stats['recv'])}"
            ))
            
            # Add daily breakdown for this connection
            conn_menu.add(rumps.separator)
            daily_history = self.store.get_connection_history(conn_key, days=7)
            for day_data in daily_history[:5]:
                date_str = day_data['date']
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(date_str)
                    if date_str == datetime.now().strftime('%Y-%m-%d'):
                        day_label = "Today"
                    else:
                        day_label = dt.strftime('%a')
                except:
                    day_label = date_str[:5]
                
                if day_data['sent'] > 0 or day_data['recv'] > 0:
                    conn_menu.add(rumps.MenuItem(
                        f"{day_label}: ↑{format_bytes(day_data['sent'])} ↓{format_bytes(day_data['recv'])}"
                    ))
            
            self.menu_connection_history.add(conn_menu)
    
    def _safe_menu_clear(self, menu_item):
        """Safely clear a menu item's submenu contents."""
        try:
            if menu_item and hasattr(menu_item, '_menu') and menu_item._menu:
                menu_item.clear()
        except (AttributeError, TypeError):
            pass  # Menu not properly initialized yet
    
    def _update_top_apps(self):
        """Update apps menu - dynamically populated, no empty slots."""
        try:
            top_processes = self.traffic_monitor.get_top_processes(limit=15)
            
            # Clear and rebuild menu
            self._safe_menu_clear(self.menu_apps)
            
            if not top_processes:
                self.menu_apps.title = "Apps"
                self.menu_apps.add(rumps.MenuItem("No active apps"))
                return
            
            self.menu_apps.title = f"Apps ({len(top_processes)})"
            
            # Add top 5 directly
            for i, (name, bytes_in, bytes_out, conns) in enumerate(top_processes[:5]):
                if conns > 0:
                    title = f"{name}: {conns} conn{'s' if conns > 1 else ''}"
                else:
                    title = f"{name}: idle"
                self.menu_apps.add(rumps.MenuItem(title))
            
            # Add "More" submenu if there are more than 5
            if len(top_processes) > 5:
                more_menu = rumps.MenuItem(f"More ({len(top_processes) - 5})")
                for name, bytes_in, bytes_out, conns in top_processes[5:]:
                    if conns > 0:
                        title = f"{name}: {conns} conn{'s' if conns > 1 else ''}"
                    else:
                        title = f"{name}: idle"
                    more_menu.add(rumps.MenuItem(title))
                self.menu_apps.add(more_menu)
                
        except Exception as e:
            self._safe_menu_clear(self.menu_apps)
            self.menu_apps.add(rumps.MenuItem(f"Error: {str(e)[:25]}"))
    
    def _update_events(self):
        """Update recent events menu - dynamically populated.
        
        Quality drop events are clickable to show troubleshooting info.
        """
        from monitor.issues import IssueType
        
        issues = self.issue_detector.get_recent_issues(10)
        
        self._safe_menu_clear(self.menu_events)
        
        if not issues:
            self.menu_events.title = "Recent Events"
            self.menu_events.add(rumps.MenuItem("No recent events"))
            return
        
        self.menu_events.title = f"Recent Events ({len(issues)})"
        
        # Show most recent first
        for issue in reversed(issues):
            time_str = issue.timestamp.strftime("%H:%M")
            desc = issue.description[:35]
            
            # Make quality drop events clickable
            if issue.issue_type == IssueType.QUALITY_DROP:
                item = rumps.MenuItem(
                    f"⚠️ {time_str}  {desc}",
                    callback=lambda _, i=issue: self._show_troubleshooting(i)
                )
            elif issue.issue_type == IssueType.HIGH_LATENCY:
                item = rumps.MenuItem(
                    f"🔴 {time_str}  {desc}",
                    callback=lambda _, i=issue: self._show_troubleshooting(i)
                )
            elif issue.issue_type == IssueType.DISCONNECT:
                item = rumps.MenuItem(f"❌ {time_str}  {desc}")
            elif issue.issue_type == IssueType.RECONNECT:
                item = rumps.MenuItem(f"✅ {time_str}  {desc}")
            elif issue.issue_type == IssueType.CONNECTION_CHANGE:
                item = rumps.MenuItem(f"🔄 {time_str}  {desc}")
            else:
                item = rumps.MenuItem(f"{time_str}  {desc}")
            
            self.menu_events.add(item)
    
    def _show_troubleshooting(self, issue):
        """Show troubleshooting information for a network issue."""
        from monitor.issues import IssueType
        
        details = issue.details
        
        # Build the message
        lines = [f"Event: {issue.description}", ""]
        
        if issue.issue_type == IssueType.QUALITY_DROP:
            lines.append(f"Previous Score: {details.get('previous_score', 'N/A')}%")
            lines.append(f"Current Score: {details.get('current_score', 'N/A')}%")
            if details.get('latency_ms'):
                lines.append(f"Latency: {details['latency_ms']:.0f}ms")
            if details.get('jitter_ms'):
                lines.append(f"Jitter: {details['jitter_ms']:.1f}ms")
            
            cause = details.get('likely_cause', 'unknown')
            cause_labels = {
                'high_latency': 'High Latency',
                'high_jitter': 'Unstable Connection',
                'poor_connection': 'Poor Connection Quality',
                'network_congestion': 'Network Congestion'
            }
            lines.append(f"\nLikely Cause: {cause_labels.get(cause, cause)}")
            
            tips = details.get('troubleshooting', [])
            if tips:
                lines.append("\nTroubleshooting Tips:")
                for tip in tips[:5]:
                    lines.append(f"  • {tip}")
        
        elif issue.issue_type == IssueType.HIGH_LATENCY:
            if details.get('latency_ms'):
                lines.append(f"Latency: {details['latency_ms']:.0f}ms")
            lines.append("\nTroubleshooting Tips:")
            lines.append("  • Check for bandwidth-heavy applications")
            lines.append("  • Restart your router")
            lines.append("  • Move closer to WiFi access point")
            lines.append("  • Consider using wired connection")
        
        rumps.alert(
            title="Network Issue Details",
            message="\n".join(lines),
            ok="OK"
        )
    
    def _format_device_name(self, device: NetworkDevice, include_ip: bool = True) -> str:
        """Get best available identifier for a device with type icon."""
        icon = device.type_icon
        
        # Get the display name
        name = device.display_name[:25]  # Truncate long names
        
        # Build the display string
        if device.os_hint:
            suffix = f"({device.os_hint})"
        elif include_ip:
            suffix = f"({device.ip_address})"
        else:
            suffix = ""
        
        return f"{icon} {name} {suffix}".strip()
    
    def _update_top_devices(self):
        """Update devices menu - dynamically populated with device type icons.
        
        Click on any device to rename it.
        Uses lazy hostname resolution - only resolves hostnames for visible devices.
        """
        devices = self.network_scanner.get_all_devices()
        online_devices = [d for d in devices if d.is_online]
        offline_devices = [d for d in devices if not d.is_online]
        
        # Sort: devices with custom names first, then better identification
        from monitor.scanner import DeviceType
        def sort_key(d):
            has_custom = bool(d.custom_name)
            has_model = bool(d.model_hint)
            has_name = bool(d.hostname and d.hostname != d.ip_address)
            has_type = d.device_type != DeviceType.UNKNOWN
            return (not has_custom, not has_model, not has_name, not has_type, d.ip_address)
        
        online_devices.sort(key=sort_key)
        
        # Lazy hostname resolution: request resolution only for visible devices (top 5)
        visible_macs = [d.mac_address for d in online_devices[:5]]
        self.network_scanner.request_resolution_for_visible(visible_macs)
        
        # Clear and rebuild menu
        self._safe_menu_clear(self.menu_devices)
        
        if not online_devices:
            self.menu_devices.title = "Devices"
            self.menu_devices.add(rumps.MenuItem("Scanning..."))
            return
        
        self.menu_devices.title = f"Devices ({len(online_devices)})"
        
        # Helper to create device menu item with rename callback
        def make_device_item(device, prefix=""):
            name = self._format_device_name(device)
            item = rumps.MenuItem(
                f"{prefix}{name}",
                callback=lambda _: self._rename_device(device)
            )
            return item
        
        # Add top 5 directly - device type icon is included in format
        for d in online_devices[:5]:
            self.menu_devices.add(make_device_item(d))
        
        # Add "More" submenu if there are more than 5
        if len(online_devices) > 5:
            more_menu = rumps.MenuItem(f"More ({len(online_devices) - 5})")
            for d in online_devices[5:]:
                more_menu.add(make_device_item(d))
            
            # Add offline devices inside More
            if offline_devices:
                more_menu.add(rumps.separator)
                offline_menu = rumps.MenuItem(f"Offline ({len(offline_devices)})")
                for d in offline_devices:
                    offline_menu.add(make_device_item(d))
                more_menu.add(offline_menu)
            
            self.menu_devices.add(more_menu)
        elif offline_devices:
            # No "More" needed but still show offline
            offline_menu = rumps.MenuItem(f"Offline ({len(offline_devices)})")
            for d in offline_devices:
                offline_menu.add(make_device_item(d, "○ "))
            self.menu_devices.add(offline_menu)
    
    def _rename_device(self, device):
        """Show dialog to rename a device."""
        current_name = device.custom_name or device.display_name
        
        response = rumps.Window(
            title=f"Rename Device",
            message=f"MAC: {device.mac_address}\nIP: {device.ip_address}\nVendor: {device.vendor or 'Unknown'}\n\nEnter a name for this device:",
            default_text=current_name,
            ok="Save",
            cancel="Cancel"
        ).run()
        
        if response.clicked:
            new_name = response.text.strip()
            if new_name:
                self.network_scanner.set_device_name(device.mac_address, new_name)
                rumps.notification(
                    "Network Monitor",
                    "Device Renamed",
                    f"{new_name}"
                )
            else:
                # Clear custom name if empty
                self.network_scanner._name_store.remove_name(device.mac_address)
                device.custom_name = None
                rumps.notification(
                    "Network Monitor", 
                    "Device Name Cleared",
                    f"Using auto-detected name"
                )
    
    def _save_issues_to_storage(self):
        """Save detected issues to persistent storage."""
        issues = self.issue_detector.get_recent_issues(10)
        today_issues = self.store.get_today_issues()
        for issue in issues:
            issue_dict = issue.to_dict()
            if issue_dict not in today_issues:
                conn_key = self.connection_detector.get_connection_key()
                self.store.add_issue(conn_key, issue_dict)
    
    def _rescan_network(self, _):
        """Force a network device scan."""
        rumps.notification(
            title="Network Monitor",
            subtitle="Scanning",
            message="Scanning for network devices..."
        )
        threading.Thread(target=self._force_scan_devices, daemon=True).start()
    
    def _force_scan_devices(self):
        """Force a device scan and notify when done."""
        try:
            self.network_scanner.scan(force=True)
            online, total = self.network_scanner.get_device_count()
            rumps.notification(
                title="Network Monitor",
                subtitle="Scan Complete",
                message=f"Found {online} online devices ({total} total known)"
            )
            logger.info(f"Force scan completed: {online} online, {total} total")
        except Exception as e:
            logger.error(f"Force scan error: {e}", exc_info=True)
    
    def _toggle_launch_at_login(self, sender):
        """Toggle Launch at Login setting."""
        success, message = self.launch_manager.toggle()
        sender.title = self.launch_manager.get_status()
        rumps.notification(
            title="Network Monitor",
            subtitle="Startup Settings",
            message=message
        )
    
    def _reset_session(self, _):
        """Reset session statistics."""
        self.network_stats.reset_session()
        self.issue_detector.clear_issues()
        self._connection_start_bytes = (0, 0)
        # Clear history
        self._upload_history.clear()
        self._download_history.clear()
        self._latency_history.clear()
        rumps.notification(
            title="Network Monitor",
            subtitle="Session Reset",
            message="Session statistics have been reset."
        )
    
    def _reset_today(self, _):
        """Reset today's statistics."""
        response = rumps.alert(
            title="Reset Today's Stats",
            message="Are you sure you want to reset all statistics for today?",
            ok="Reset",
            cancel="Cancel"
        )
        if response == 1:
            self.store.reset_today()
            self.network_stats.reset_session()
            self.issue_detector.clear_issues()
            rumps.notification(
                title="Network Monitor",
                subtitle="Stats Reset",
                message="Today's statistics have been reset."
            )
    
    def _open_data_folder(self, _):
        """Open the data folder in Finder."""
        import subprocess
        folder = str(self.store.data_dir)
        subprocess.run(['open', folder])
    
    def _create_budget_bar_image(self, percent: float, width: int = 100, height: int = 12) -> str:
        """Create a PIL-based budget progress bar image.
        
        Args:
            percent: Budget usage percentage (0-100+)
            width: Image width in pixels
            height: Image height in pixels
            
        Returns:
            Path to the generated PNG file
        """
        from PIL import Image, ImageDraw
        import hashlib
        
        # Clamp display percent but track if exceeded
        exceeded = percent > 100
        display_percent = min(percent, 100)
        
        # Create image with transparency
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Colors based on status
        if exceeded:
            fill_color = (255, 59, 48, 255)      # Red
            bg_color = (255, 59, 48, 80)         # Light red background
        elif percent >= 80:
            fill_color = (255, 204, 0, 255)      # Yellow
            bg_color = (100, 100, 100, 60)       # Gray background
        else:
            fill_color = (52, 199, 89, 255)      # Green
            bg_color = (100, 100, 100, 60)       # Gray background
        
        # Draw background (rounded rectangle)
        padding = 1
        radius = height // 3
        draw.rounded_rectangle(
            [padding, padding, width - padding, height - padding],
            radius=radius,
            fill=bg_color
        )
        
        # Draw filled portion
        filled_width = int((display_percent / 100) * (width - 2 * padding))
        if filled_width > 0:
            draw.rounded_rectangle(
                [padding, padding, padding + filled_width, height - padding],
                radius=radius,
                fill=fill_color
            )
        
        # Save to temp file
        temp_dir = Path(tempfile.gettempdir()) / STORAGE.ICON_TEMP_DIR
        temp_dir.mkdir(exist_ok=True)
        
        # Use hash for caching
        cache_key = f"budget_{int(percent)}_{width}_{height}"
        img_path = temp_dir / f'{cache_key}.png'
        
        img.save(str(img_path), 'PNG')
        return str(img_path)
    
    def _update_budget(self, conn: ConnectionInfo, today_sent: int, today_recv: int):
        """Update budget status display with visual progress bar."""
        if not conn.is_connected:
            self.menu_budget.title = "Budget: Not connected"
            return
        
        conn_key = self.connection_detector.get_connection_key()
        budget = self.settings.get_budget(conn_key)
        
        if not budget or not budget.enabled:
            self.menu_budget.title = "Budget: Not set  ›"
            return
        
        # Get usage for the budget period
        if budget.period == "daily":
            usage = today_sent + today_recv
            period_label = "today"
        elif budget.period == "weekly":
            weekly = self.store.get_weekly_totals()
            conn_stats = weekly.get('by_connection', {}).get(conn_key, {'sent': 0, 'recv': 0})
            usage = conn_stats.get('sent', 0) + conn_stats.get('recv', 0)
            period_label = "this week"
        else:  # monthly
            monthly = self.store.get_monthly_totals()
            conn_stats = monthly.get('by_connection', {}).get(conn_key, {'sent': 0, 'recv': 0})
            usage = conn_stats.get('sent', 0) + conn_stats.get('recv', 0)
            period_label = "this month"
        
        status = self.settings.check_budget_status(conn_key, 0, usage)
        percent = status['percent_used']
        
        # Create visual progress bar image
        try:
            bar_image_path = self._create_budget_bar_image(percent)
            self._set_menu_image(self.menu_budget, bar_image_path)
        except Exception as e:
            logger.debug(f"Could not create budget bar: {e}")
        
        # Format remaining data
        remaining = format_bytes(status['remaining_bytes'])
        
        # Budget notifications and title
        if status['exceeded']:
            self.menu_budget.title = f"  OVER LIMIT ({percent:.0f}%)"
            # Send exceeded notification (once per connection)
            if conn_key not in self._budget_exceeded_notified:
                self._budget_exceeded_notified.add(conn_key)
                limit_str = format_bytes(status['limit_bytes'])
                rumps.notification(
                    title="Network Monitor",
                    subtitle="⚠️ Data Budget Exceeded!",
                    message=f"You've exceeded your {budget.period} limit of {limit_str} on {conn_key}.",
                    sound=True
                )
                logger.warning(f"Budget exceeded for {conn_key}: {percent:.1f}%")
        elif status['warning']:
            self.menu_budget.title = f"  {percent:.0f}% used ({remaining} left)"
            # Send warning notification (once per connection)
            if conn_key not in self._budget_warning_notified:
                self._budget_warning_notified.add(conn_key)
                rumps.notification(
                    title="Network Monitor",
                    subtitle=f"Data Budget Warning ({percent:.0f}%)",
                    message=f"You've used {percent:.0f}% of your {budget.period} limit. {remaining} remaining.",
                    sound=False
                )
                logger.info(f"Budget warning for {conn_key}: {percent:.1f}%")
        else:
            self.menu_budget.title = f"  {percent:.0f}% used ({remaining} left)"
            # Reset notification flags when under warning threshold
            # (allows re-notification if usage drops and rises again)
            self._budget_warning_notified.discard(conn_key)
            self._budget_exceeded_notified.discard(conn_key)
    
    def _build_budget_menu(self):
        """Build the budget submenu with presets and options."""
        self._safe_menu_clear(self.menu_budgets)
        
        conn_key = self.connection_detector.get_connection_key() if hasattr(self, 'connection_detector') else None
        budget = self.settings.get_budget(conn_key) if conn_key else None
        
        # Current connection budget section
        if conn_key:
            # Header
            self.menu_budgets.add(rumps.MenuItem(f"── {conn_key[:20]} ──"))
            
            if budget and budget.enabled:
                # Show current status
                limit_display = self._format_budget_limit(budget.limit_bytes)
                self.menu_budgets.add(rumps.MenuItem(f"   Limit: {limit_display}/{budget.period}"))
                
                # Toggle off option
                self.menu_budgets.add(rumps.MenuItem("   ✓ Budget Enabled", 
                                                     callback=lambda _: self._toggle_budget(conn_key)))
            else:
                self.menu_budgets.add(rumps.MenuItem("   No budget set"))
            
            self.menu_budgets.add(rumps.separator)
            
            # Quick presets
            self.menu_budgets.add(rumps.MenuItem("── Quick Set ──"))
            presets = [
                ("500 MB", 500),
                ("1 GB", 1024),
                ("2 GB", 2048),
                ("5 GB", 5120),
                ("10 GB", 10240),
                ("Unlimited", 0),
            ]
            
            for label, mb in presets:
                # Check if this is the current setting
                is_current = budget and budget.enabled and budget.limit_bytes == mb * 1024 * 1024
                prefix = "   ✓ " if is_current else "      "
                self.menu_budgets.add(rumps.MenuItem(
                    f"{prefix}{label}",
                    callback=lambda _, m=mb: self._set_quick_budget(conn_key, m)
                ))
            
            self.menu_budgets.add(rumps.separator)
            
            # Period selection
            self.menu_budgets.add(rumps.MenuItem("── Reset Period ──"))
            periods = [("Daily", "daily"), ("Weekly", "weekly"), ("Monthly", "monthly")]
            current_period = budget.period if budget else "monthly"
            
            for label, period in periods:
                is_current = current_period == period
                prefix = "   ✓ " if is_current else "      "
                self.menu_budgets.add(rumps.MenuItem(
                    f"{prefix}{label}",
                    callback=lambda _, p=period: self._set_budget_period(conn_key, p)
                ))
            
            self.menu_budgets.add(rumps.separator)
            
            # Custom amount
            self.menu_budgets.add(rumps.MenuItem("Custom Amount...", 
                                                 callback=self._set_custom_budget))
        else:
            self.menu_budgets.add(rumps.MenuItem("Connect to a network first"))
        
        # View all budgets
        self.menu_budgets.add(rumps.separator)
        self.menu_budgets.add(rumps.MenuItem("View All Budgets...", 
                                             callback=self._show_all_budgets))
    
    def _format_budget_limit(self, bytes_val: int) -> str:
        """Format budget limit nicely."""
        if bytes_val == 0:
            return "Unlimited"
        gb = bytes_val / (1024 * 1024 * 1024)
        if gb >= 1:
            return f"{gb:.1f} GB"
        mb = bytes_val / (1024 * 1024)
        return f"{mb:.0f} MB"
    
    def _set_quick_budget(self, conn_key: str, limit_mb: int):
        """Set a quick preset budget."""
        if limit_mb == 0:
            # Disable budget
            self.settings.remove_budget(conn_key)
            rumps.notification("Network Monitor", "Budget Removed", 
                             f"Unlimited data for {conn_key}")
        else:
            budget = self.settings.get_budget(conn_key)
            period = budget.period if budget else "monthly"
            
            new_budget = ConnectionBudget(
                enabled=True,
                limit_bytes=limit_mb * 1024 * 1024,
                period=period,
                warn_at_percent=80
            )
            self.settings.set_budget(conn_key, new_budget)
            
            rumps.notification("Network Monitor", "Budget Set", 
                             f"{self._format_budget_limit(limit_mb * 1024 * 1024)}/{period}")
        
        self._build_budget_menu()
    
    def _set_budget_period(self, conn_key: str, period: str):
        """Change the budget period."""
        budget = self.settings.get_budget(conn_key)
        if budget:
            budget.period = period
            self.settings.set_budget(conn_key, budget)
            rumps.notification("Network Monitor", "Period Changed", 
                             f"Budget now resets {period}")
        self._build_budget_menu()
    
    def _toggle_budget(self, conn_key: str):
        """Toggle budget on/off."""
        budget = self.settings.get_budget(conn_key)
        if budget and budget.enabled:
            self.settings.remove_budget(conn_key)
            rumps.notification("Network Monitor", "Budget Disabled", conn_key)
        self._build_budget_menu()
    
    def _set_custom_budget(self, _):
        """Set a custom budget amount."""
        conn_key = self.connection_detector.get_connection_key()
        if not conn_key:
            return
        
        response = rumps.Window(
            title="Custom Data Budget",
            message="Enter limit in MB:",
            default_text="1024",
            ok="Set",
            cancel="Cancel"
        ).run()
        
        if response.clicked:
            try:
                limit_mb = int(response.text)
                self._set_quick_budget(conn_key, limit_mb)
            except ValueError:
                rumps.alert("Invalid", "Please enter a number")
    
    def _show_all_budgets(self, _):
        """Show all configured budgets."""
        budgets = self.settings.get_all_budgets()
        
        if not budgets:
            rumps.alert("Data Budgets", "No budgets configured.\n\nConnect to a network and use Quick Set to add one.")
            return
        
        lines = ["Configured Budgets:\n"]
        for conn_key, budget in budgets.items():
            if budget.enabled:
                limit = self._format_budget_limit(budget.limit_bytes)
                lines.append(f"• {conn_key}")
                lines.append(f"   {limit} per {budget.period}")
                lines.append("")
        
        rumps.alert("Data Budgets", "\n".join(lines))
    
    # === Data Export ===
    
    def _export_csv(self, _):
        """Export network data to CSV file."""
        import csv
        from datetime import datetime
        
        # Get export file path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"network_monitor_export_{timestamp}.csv"
        
        # Use file dialog to get save location
        try:
            import subprocess
            result = subprocess.run(
                ['osascript', '-e', 
                 f'tell application "System Events" to return POSIX path of (choose file name default name "{default_filename}" default location (path to desktop folder))'],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                return  # User cancelled
            
            filepath = Path(result.stdout.strip())
            if not filepath.suffix:
                filepath = filepath.with_suffix('.csv')
        except Exception as e:
            logger.error(f"File dialog error: {e}")
            # Fallback to desktop
            filepath = Path.home() / "Desktop" / default_filename
        
        try:
            # Collect data
            daily = self.store.get_daily_totals(days=30)
            
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                
                # Header
                writer.writerow(['Date', 'Uploaded (bytes)', 'Downloaded (bytes)', 'Total (bytes)'])
                
                # Daily data
                for day in daily:
                    writer.writerow([
                        day['date'],
                        day['sent'],
                        day['recv'],
                        day['sent'] + day['recv']
                    ])
                
                # Add summary section
                writer.writerow([])
                writer.writerow(['Summary'])
                
                weekly = self.store.get_weekly_totals()
                monthly = self.store.get_monthly_totals()
                
                writer.writerow(['Period', 'Uploaded', 'Downloaded', 'Total'])
                writer.writerow(['This Week', weekly['sent'], weekly['recv'], weekly['sent'] + weekly['recv']])
                writer.writerow(['This Month', monthly['sent'], monthly['recv'], monthly['sent'] + monthly['recv']])
            
            rumps.notification(
                title="Network Monitor",
                subtitle="Export Complete",
                message=f"Data exported to {filepath.name}"
            )
            logger.info(f"Data exported to CSV: {filepath}")
            
            # Open in Finder
            subprocess.run(['open', '-R', str(filepath)])
            
        except Exception as e:
            logger.error(f"CSV export error: {e}", exc_info=True)
            rumps.alert("Export Error", f"Could not export data: {e}")
    
    def _export_json(self, _):
        """Export network data to JSON file."""
        import json
        from datetime import datetime
        
        # Get export file path  
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"network_monitor_export_{timestamp}.json"
        
        # Use file dialog to get save location
        try:
            import subprocess
            result = subprocess.run(
                ['osascript', '-e',
                 f'tell application "System Events" to return POSIX path of (choose file name default name "{default_filename}" default location (path to desktop folder))'],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                return  # User cancelled
            
            filepath = Path(result.stdout.strip())
            if not filepath.suffix:
                filepath = filepath.with_suffix('.json')
        except Exception as e:
            logger.error(f"File dialog error: {e}")
            # Fallback to desktop
            filepath = Path.home() / "Desktop" / default_filename
        
        try:
            # Collect comprehensive data
            export_data = {
                "export_timestamp": datetime.now().isoformat(),
                "app_version": "1.2",
                "daily_usage": self.store.get_daily_totals(days=90),
                "weekly_totals": self.store.get_weekly_totals(),
                "monthly_totals": self.store.get_monthly_totals(),
                "current_session": {
                    "upload_bytes": self.network_stats.get_session_totals()[0],
                    "download_bytes": self.network_stats.get_session_totals()[1],
                },
                "network_quality": {
                    "score": self._quality_score,
                    "avg_latency_ms": sum(self._latency_samples) / len(self._latency_samples) if self._latency_samples else None,
                    "sample_count": len(self._latency_samples),
                },
                "devices": [
                    {
                        "ip": d.ip_address,
                        "mac": d.mac_address,
                        "name": d.display_name,
                        "vendor": d.vendor,
                        "type": d.device_type,
                        "is_online": d.is_online,
                    }
                    for d in self.network_scanner.get_all_devices()
                ],
                "budgets": {
                    k: v.to_dict() for k, v in self.settings.get_all_budgets().items()
                },
            }
            
            with open(filepath, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            rumps.notification(
                title="Network Monitor",
                subtitle="Export Complete",
                message=f"Data exported to {filepath.name}"
            )
            logger.info(f"Data exported to JSON: {filepath}")
            
            # Open in Finder
            import subprocess
            subprocess.run(['open', '-R', str(filepath)])
            
        except Exception as e:
            logger.error(f"JSON export error: {e}", exc_info=True)
            rumps.alert("Export Error", f"Could not export data: {e}")
    
    # === Backup/Restore Methods ===
    
    def _create_backup(self, _):
        """Create a database backup."""
        from datetime import datetime
        
        # Get backup file path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"network_monitor_backup_{timestamp}.db"
        
        try:
            import subprocess
            result = subprocess.run(
                ['osascript', '-e',
                 f'tell application "System Events" to return POSIX path of (choose file name default name "{default_filename}" default location (path to desktop folder))'],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                return  # User cancelled
            
            filepath = Path(result.stdout.strip())
            if not filepath.suffix:
                filepath = filepath.with_suffix('.db')
        except Exception as e:
            logger.error(f"File dialog error: {e}")
            # Fallback to default location
            filepath = Path.home() / "Desktop" / default_filename
        
        try:
            backup_path = self.store.backup(filepath)
            
            rumps.notification(
                title="Network Monitor",
                subtitle="Backup Complete",
                message=f"Database backed up to {backup_path.name}"
            )
            logger.info(f"Backup created: {backup_path}")
            
            # Open in Finder
            import subprocess
            subprocess.run(['open', '-R', str(backup_path)])
            
        except Exception as e:
            logger.error(f"Backup error: {e}", exc_info=True)
            rumps.alert("Backup Error", f"Could not create backup: {e}")
    
    def _restore_backup(self, _):
        """Restore database from a backup file."""
        # Confirm the action
        response = rumps.alert(
            title="Restore from Backup",
            message="This will replace ALL current data with the backup.\n\nAre you sure you want to continue?",
            ok="Choose Backup...",
            cancel="Cancel"
        )
        
        if response != 1:
            return
        
        try:
            import subprocess
            result = subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to return POSIX path of (choose file of type {"db", "sqlite", "sqlite3"} with prompt "Select backup file to restore")'],
                capture_output=True, text=True, timeout=60
            )
            
            if result.returncode != 0 or not result.stdout.strip():
                return  # User cancelled
            
            backup_path = Path(result.stdout.strip())
            
            # Double-confirm
            confirm = rumps.alert(
                title="Confirm Restore",
                message=f"Restore from:\n{backup_path.name}\n\nAll current data will be replaced. This cannot be undone.",
                ok="Restore",
                cancel="Cancel"
            )
            
            if confirm != 1:
                return
            
            self.store.restore(backup_path)
            
            rumps.notification(
                title="Network Monitor",
                subtitle="Restore Complete",
                message=f"Data restored from {backup_path.name}"
            )
            logger.info(f"Database restored from: {backup_path}")
            
        except Exception as e:
            logger.error(f"Restore error: {e}", exc_info=True)
            rumps.alert("Restore Error", f"Could not restore backup: {e}")
    
    def _show_database_info(self, _):
        """Show database statistics and information."""
        try:
            stats = self.store.get_database_stats()
            
            info_lines = [
                "Database Statistics",
                "",
                f"Traffic Records: {stats.get('traffic_records', 0):,}",
                f"Issues Logged: {stats.get('issues_count', 0):,}",
                f"Known Devices: {stats.get('devices_count', 0):,}",
                "",
                f"Date Range: {stats.get('oldest_date', 'N/A')} to {stats.get('newest_date', 'N/A')}",
                "",
                f"Database Size: {stats.get('file_size_mb', 0):.2f} MB",
                "",
                f"Retention Policy: {STORAGE.RETENTION_DAYS} days",
                f"Location: {self.store.get_data_file_path()}"
            ]
            
            rumps.alert(
                title="Database Info",
                message="\n".join(info_lines),
                ok="OK"
            )
        except Exception as e:
            logger.error(f"Database info error: {e}", exc_info=True)
            rumps.alert("Error", f"Could not get database info: {e}")
    
    def _run_cleanup(self, _):
        """Manually run data cleanup."""
        response = rumps.alert(
            title="Run Cleanup",
            message=f"This will delete data older than {STORAGE.RETENTION_DAYS} days.\n\nContinue?",
            ok="Run Cleanup",
            cancel="Cancel"
        )
        
        if response != 1:
            return
        
        try:
            deleted = self.store.cleanup_old_data()
            
            if deleted > 0:
                rumps.notification(
                    title="Network Monitor",
                    subtitle="Cleanup Complete",
                    message=f"Removed {deleted} old records"
                )
            else:
                rumps.notification(
                    title="Network Monitor",
                    subtitle="Cleanup Complete",
                    message="No old data to remove"
                )
            logger.info(f"Manual cleanup completed: {deleted} records removed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}", exc_info=True)
            rumps.alert("Cleanup Error", f"Could not run cleanup: {e}")
    
    def _set_title_display(self, mode: str):
        """Set the title display mode."""
        self.settings.set_title_display(mode)
        
        # Rebuild the display options menu to show checkmark
        self._safe_menu_clear(self.menu_title_display)
        for m, label in self.settings.get_title_display_options():
            check = "✓ " if m == mode else "   "
            item = rumps.MenuItem(f"{check}{label}", callback=lambda s, m=m: self._set_title_display(m))
            self.menu_title_display.add(item)
        
        rumps.notification(
            title="Network Monitor",
            subtitle="Display Changed",
            message=f"Menu bar will now show: {mode}"
        )
    
    def _show_about(self, _):
        """Show About dialog."""
        about_text = """Network Monitor v1.2

A lightweight macOS menu bar app for monitoring network activity.

Features:
• Real-time upload/download speed
• Latency monitoring with history graphs
• Network device discovery
• Per-app bandwidth tracking
• Data budgets per connection
• Daily/weekly/monthly statistics
• Launch at login support
• SQLite database with backup/restore

v1.2: Migrated to SQLite storage for better
performance. Added automatic cleanup, backup
and restore functionality.

Data is stored locally in:
~/.network-monitor/

Built with Python, rumps, and matplotlib.

© 2026"""
        
        rumps.alert(
            title="About Network Monitor",
            message=about_text,
            ok="OK"
        )
    
    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files created by the app."""
        import shutil
        for temp_dir in self._temp_dirs:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Warning: Could not clean up {temp_dir}: {e}")
    
    def _cleanup_old_sparklines(self) -> None:
        """Remove sparkline images older than configured max age."""
        import time as time_module
        sparkline_dir = Path(tempfile.gettempdir()) / STORAGE.SPARKLINE_TEMP_DIR
        if not sparkline_dir.exists():
            return
        
        cutoff = time_module.time() - STORAGE.SPARKLINE_MAX_AGE_SECONDS
        try:
            for file in sparkline_dir.glob('*.png'):
                if file.stat().st_mtime < cutoff:
                    file.unlink()
        except Exception as e:
            logger.debug(f"Sparkline cleanup error: {e}")
    
    def _quit(self, _):
        """Quit the application."""
        logger.info("Application shutting down...")
        self._running = False
        self.store.flush()  # Save any pending data
        self._cleanup_temp_files()
        logger.info("Shutdown complete")
        rumps.quit_application()


def main():
    """Entry point for the application."""
    # Check for existing instance first (before logging to avoid confusion)
    if not _singleton_lock.acquire():
        # Another instance is running - show alert and exit
        print("Network Monitor is already running.", file=sys.stderr)
        try:
            # Try to show a user-friendly alert
            rumps.alert(
                title="Network Monitor",
                message="Network Monitor is already running.\n\nCheck your menu bar for the existing instance.",
                ok="OK"
            )
        except Exception:
            pass  # nosec B110 - If alert fails, we've already printed to stderr
        sys.exit(1)
    
    # Register lock release on exit
    atexit.register(_singleton_lock.release)
    
    # Initialize logging
    data_dir = Path.home() / STORAGE.DATA_DIR_NAME
    setup_logging(data_dir=data_dir, debug=False, console_output=True)
    logger.info("Network Monitor starting...")
    
    try:
        app = NetworkMonitorApp()
        app.run()
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        raise
    finally:
        _singleton_lock.release()


if __name__ == "__main__":
    main()
