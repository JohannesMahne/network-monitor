#!/usr/bin/env python3
"""
Network Monitor - macOS Menu Bar Application
Monitors network traffic, tracks daily usage per connection, and logs issues.
"""
import atexit
import json
import os
import signal
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import rumps

# Hide dock icon (menu bar only app)
from Foundation import NSBundle, NSOperationQueue

from app.controller import AppController
from app.dependencies import create_dependencies
from app.events import EventBus, EventType
from app.sparkline_renderer import SparklineRenderer
from app.timer import MenuAwareTimer
from config import COLORS, INTERVALS, STORAGE, THRESHOLDS, get_logger, setup_logging
from config.singleton import SingletonLock, get_singleton_lock
from monitor.connection import ConnectionInfo
from monitor.issues import IssueType
from monitor.network import format_bytes
from monitor.scanner import NetworkDevice
from monitor.speed_test import SpeedTest
from service.launch_agent import get_launch_agent_manager
from storage.settings import ConnectionBudget

info = NSBundle.mainBundle().infoDictionary()
info["LSUIElement"] = "1"

# For colored menu bar icons
from PIL import Image, ImageDraw

# Note: matplotlib is only imported if PIL sparklines fail (fallback)
# PIL is much faster and uses less memory for sparklines

# Global singleton lock (now imported from config.singleton)
_singleton_lock = get_singleton_lock()


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

        # Initialize dependency container and controller
        self._event_bus = EventBus(async_mode=False)  # Sync for UI updates
        self._deps = create_dependencies(event_bus=self._event_bus)
        self._controller = AppController(self._deps, self._event_bus)
        
        # Initialize sparkline renderer
        self._sparkline_renderer = SparklineRenderer()
        
        # Initialize speed test
        self._speed_test = SpeedTest()
        
        # Initialize keyboard shortcuts
        from app.shortcuts import ShortcutManager
        self._shortcut_manager = ShortcutManager()
        self._register_shortcuts()

        # Create aliases for backward compatibility during refactoring
        # These will be gradually migrated to use self._deps.* directly
        self.network_stats = self._deps.network_stats
        self.connection_detector = self._deps.connection_detector
        self.issue_detector = self._deps.issue_detector
        self.network_scanner = self._deps.network_scanner
        self.traffic_monitor = self._deps.traffic_monitor
        self.store = self._deps.store
        self.settings = self._deps.settings
        self._deps = self._deps  # Store for access to dns_monitor

        # Track session data
        self._session_bytes_sent = 0
        self._session_bytes_recv = 0
        self._last_connection_key = ""
        self._connection_start_bytes = (0, 0)
        self._last_stored_bytes = {}  # Track last bytes sent to DB to compute delta
        self._last_device_scan = 0
        self._device_scan_interval = INTERVALS.DEVICE_SCAN_SECONDS
        self._last_traffic_update = 0
        self._traffic_update_interval = INTERVALS.TRAFFIC_UPDATE_SECONDS
        self._last_latency_check = 0
        self._latency_check_interval = INTERVALS.LATENCY_CHECK_SECONDS
        self._current_latency = None
        self._latency_samples = []

        # History for sparkline graphs (persisted across restarts)
        self._upload_history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._download_history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._total_history: deque = deque(maxlen=self.HISTORY_SIZE)  # Combined up+down
        self._quality_history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._latency_history: deque = deque(maxlen=self.HISTORY_SIZE)
        self._dns_history: deque = deque(maxlen=self.HISTORY_SIZE)  # DNS latency history
        self._current_dns_latency: Optional[float] = None
        self._sparkline_lock = threading.Lock()  # Thread lock for sparkline history access
        self._load_sparkline_history()  # Load persisted history
        self._sparkline_save_counter = 0  # Counter for periodic saves

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

        # Subscribe to controller events for UI updates
        self._subscribe_to_events()

        # Start monitoring
        self._running = True
        self._controller.start()  # Start controller
        self._start_monitoring()

        # Schedule delayed timer start - runs after rumps.run()
        # so menu items have their underlying NSMenuItem objects
        self._startup_timer = rumps.Timer(self._delayed_timer_start, 0.5)
        self._startup_timer.start()

        # Trigger initial device scan immediately
        threading.Thread(target=self._initial_device_scan, daemon=True).start()

    def _register_shortcuts(self):
        """Register global keyboard shortcuts."""
        try:
            shortcut = self.settings.get_keyboard_shortcut()
            
            # Register menu toggle shortcut
            success = self._shortcut_manager.register_shortcut(
                shortcut,
                lambda: self._toggle_menu_visibility()
            )
            
            if not success:
                logger.warning("Could not register keyboard shortcut - may need Accessibility permissions")
        except Exception as e:
            logger.debug(f"Shortcut registration failed: {e}")

    def _toggle_menu_visibility(self):
        """Toggle menu visibility (called by keyboard shortcut)."""
        # This would toggle the menu - for now just log
        logger.debug("Keyboard shortcut triggered - menu toggle")
        # Note: rumps doesn't have direct menu visibility toggle,
        # but we could implement a status window or notification

    def _build_menu(self):
        """Build the dropdown menu - standard macOS style."""

        # === SPARKLINE GRAPHS (no header, graphs speak for themselves) ===
        self.menu_graph_quality = rumps.MenuItem("◆ ─────────────────────")
        self.menu_graph_upload = rumps.MenuItem("↑ ─────────────────────")
        self.menu_graph_download = rumps.MenuItem("↓ ─────────────────────")
        self.menu_graph_total = rumps.MenuItem("⇅ ─────────────────────")  # Combined total
        self.menu_graph_latency = rumps.MenuItem("● ─────────────────────")
        self.menu_graph_dns = rumps.MenuItem("🔍 ─────────────────────")  # DNS latency

        # === CURRENT STATS ===
        self.menu_connection = rumps.MenuItem("Detecting")
        self.menu_speed = rumps.MenuItem("↑ --  ↓ --")
        self.menu_latency = rumps.MenuItem("Latency: --")
        self.menu_dns = rumps.MenuItem("DNS: --")  # DNS latency
        self.menu_quality = rumps.MenuItem("Quality: --")  # Network quality score
        self.menu_today = rumps.MenuItem("Today: ↑ --  ↓ --")

        # === BUDGET STATUS (shown when budget is set) ===
        self.menu_budget = rumps.MenuItem("Budget: Not set")

        # === NETWORK DEVICES (dynamically populated) ===
        self.menu_devices = rumps.MenuItem("Devices")
        self.menu_devices.add(rumps.MenuItem("Scanning..."))  # Placeholder to make submenu clickable

        # === TOP APPS (dynamically populated) ===
        self.menu_apps = rumps.MenuItem("Connections")
        self.menu_apps.add(rumps.MenuItem("Loading..."))  # Placeholder to make submenu clickable

        # === CONNECTION LOCATIONS (geolocation) ===
        self.menu_locations = rumps.MenuItem("Connection Locations")
        self.menu_locations.add(rumps.MenuItem("Loading..."))  # Placeholder

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
        self.menu_events.add(rumps.MenuItem("No recent events"))  # Placeholder to make submenu clickable

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
        self.menu_speed_test = rumps.MenuItem("Run Speed Test...", callback=self._run_speed_test)
        self.menu_show_graphs = rumps.MenuItem("Show Detailed Stats...", callback=self._show_detailed_graphs)
        self.menu_reset_session = rumps.MenuItem("Reset Session", callback=self._reset_session)
        self.menu_reset_today = rumps.MenuItem("Reset Today", callback=self._reset_today)
        self.menu_data_location = rumps.MenuItem("Open Data Folder", callback=self._open_data_folder)

        # Export submenu
        self.menu_export = rumps.MenuItem("Export Data")
        self.menu_export.add(rumps.MenuItem("Export as CSV...", callback=self._export_csv))
        self.menu_export.add(rumps.MenuItem("Export as JSON...", callback=self._export_json))
        self.menu_export.add(rumps.separator)
        self.menu_export.add(rumps.MenuItem("Export to InfluxDB...", callback=self._export_to_influxdb))
        self.menu_export.add(rumps.MenuItem("Export to Prometheus...", callback=self._export_to_prometheus))

        # Backup/Restore submenu
        self.menu_backup = rumps.MenuItem("Backup & Restore")
        self.menu_backup.add(rumps.MenuItem("Create Backup...", callback=self._create_backup))
        self.menu_backup.add(rumps.MenuItem("Restore from Backup...", callback=self._restore_backup))
        self.menu_backup.add(rumps.separator)
        self.menu_backup.add(rumps.MenuItem("Database Info...", callback=self._show_database_info))
        self.menu_backup.add(rumps.MenuItem("Run Cleanup Now", callback=self._run_cleanup))

        self.menu_actions.add(self.menu_rescan)
        self.menu_actions.add(self.menu_speed_test)
        self.menu_actions.add(self.menu_show_graphs)
        self.menu_actions.add(rumps.separator)
        self.menu_actions.add(self.menu_reset_session)
        self.menu_actions.add(self.menu_reset_today)
        self.menu_actions.add(rumps.separator)
        self.menu_actions.add(self.menu_export)
        self.menu_actions.add(self.menu_backup)
        self.menu_actions.add(self.menu_data_location)

        # === BUILD MENU (organized by category) ===
        # Note: VPN status is added dynamically when VPN is detected
        self.menu = [
            # --- Connection & Live Status ---
            self.menu_connection,
            self.menu_speed,
            self.menu_latency,
            self.menu_dns,
            self.menu_quality,
            rumps.separator,
            # --- Sparkline Graphs (visual trends) ---
            self.menu_graph_quality,
            self.menu_graph_upload,
            self.menu_graph_download,
            self.menu_graph_total,
            self.menu_graph_latency,
            self.menu_graph_dns,
            rumps.separator,
            # --- Usage Stats ---
            self.menu_today,
            self.menu_budget,
            rumps.separator,
            # --- Data Sections ---
            self.menu_devices,
            self.menu_apps,
            self.menu_locations,
            self.menu_history,
            self.menu_events,
            rumps.separator,
            # --- App Controls ---
            self.menu_settings,
            self.menu_actions,
            rumps.separator,
            rumps.MenuItem("About", callback=self._show_about),
            rumps.MenuItem("Quit", callback=self._quit)
        ]

    def _subscribe_to_events(self):
        """Subscribe to controller events for UI updates."""
        # Subscribe to events from the controller/event bus
        # These allow the UI to respond to state changes
        self._event_bus.subscribe(EventType.STATS_UPDATED, self._on_stats_updated)
        self._event_bus.subscribe(EventType.CONNECTION_CHANGED, self._on_connection_changed)
        self._event_bus.subscribe(EventType.DEVICES_SCANNED, self._on_devices_scanned)
        self._event_bus.subscribe(EventType.LATENCY_UPDATE, self._on_latency_update)
        self._event_bus.subscribe(EventType.BUDGET_WARNING, self._on_budget_warning)
        self._event_bus.subscribe(EventType.BUDGET_EXCEEDED, self._on_budget_exceeded)
        self._event_bus.subscribe(EventType.BANDWIDTH_THRESHOLD_EXCEEDED, self._on_bandwidth_threshold_exceeded)
        self._event_bus.subscribe(EventType.DEVICE_NEWLY_ONLINE, self._on_device_newly_online)
        self._event_bus.subscribe(EventType.QUALITY_DEGRADED, self._on_quality_degraded)
        self._event_bus.subscribe(EventType.VPN_DISCONNECTED, self._on_vpn_disconnected)
        self._event_bus.subscribe(EventType.DNS_UPDATE, self._on_dns_update)
        self._event_bus.subscribe(EventType.DNS_SLOW, self._on_dns_slow)
        logger.debug("Subscribed to controller events")

    def _on_stats_updated(self, event):
        """Handle stats update event from controller."""
        # This is called when the controller updates stats
        # For now, we still use the direct update mechanism
        pass  # Will be implemented as refactoring progresses

    def _on_connection_changed(self, event):
        """Handle connection change event from controller."""
        data = event.data
        logger.info(f"Connection changed: {data.get('old')} -> {data.get('new')}")

    def _on_devices_scanned(self, event):
        """Handle devices scanned event from controller."""
        data = event.data
        online = data.get('online', 0)
        total = data.get('total', 0)
        logger.debug(f"Devices scanned: {online} online / {total} total")

    def _on_latency_update(self, event):
        """Handle latency update event from controller."""
        data = event.data
        latency = data.get('latency')
        if latency is not None:
            self._current_latency = latency

    def _on_budget_warning(self, event):
        """Handle budget warning event from controller."""
        data = event.data
        conn = data.get('connection', 'Unknown')
        percent = data.get('percent', 0)
        rumps.notification(
            title="Data Budget Warning",
            subtitle=conn,
            message=f"You've used {percent:.0f}% of your budget"
        )

    def _on_budget_exceeded(self, event):
        """Handle budget exceeded event from controller."""
        data = event.data
        conn = data.get('connection', 'Unknown')
        rumps.notification(
            title="Data Budget Exceeded",
            subtitle=conn,
            message="You've exceeded your data budget!"
        )

    def _on_bandwidth_threshold_exceeded(self, event):
        """Handle bandwidth threshold exceeded event."""
        data = event.data
        app_name = data.get('app_name', 'Unknown')
        current_mbps = data.get('current_mbps', 0)
        threshold_mbps = data.get('threshold_mbps', 0)
        rumps.notification(
            title="Bandwidth Alert",
            subtitle=app_name,
            message=f"Using {current_mbps:.1f} Mbps (threshold: {threshold_mbps:.1f} Mbps)",
            sound=True
        )

    def _on_device_newly_online(self, event):
        """Handle new device coming online event."""
        notif_settings = self.settings.get_notification_settings()
        if not notif_settings.notify_new_device:
            return
        
        data = event.data
        device_name = data.get('name', 'Unknown Device')
        device_ip = data.get('ip', '')
        rumps.notification(
            title="New Device Detected",
            subtitle=device_name,
            message=f"Device {device_ip} joined the network",
            sound=False
        )

    def _on_quality_degraded(self, event):
        """Handle network quality degradation event."""
        notif_settings = self.settings.get_notification_settings()
        if not notif_settings.notify_quality_degraded:
            return
        
        data = event.data
        previous_score = data.get('previous_score', 0)
        current_score = data.get('current_score', 0)
        
        # Only notify if quality dropped below threshold
        if current_score < notif_settings.quality_degraded_threshold:
            rumps.notification(
                title="Network Quality Degraded",
                subtitle=f"Quality: {current_score}%",
                message=f"Quality dropped from {previous_score}% to {current_score}%",
                sound=True
            )

    def _on_vpn_disconnected(self, event):
        """Handle VPN disconnect event."""
        notif_settings = self.settings.get_notification_settings()
        if not notif_settings.notify_vpn_disconnect:
            return
        
        data = event.data
        vpn_name = data.get('previous_vpn_name', 'VPN')
        rumps.notification(
            title="VPN Disconnected",
            subtitle=vpn_name,
            message="Your VPN connection was lost",
            sound=True
        )

    def _on_dns_update(self, event):
        """Handle DNS update event."""
        data = event.data
        latency = data.get('latency_ms')
        if latency is not None:
            self._current_dns_latency = latency

    def _on_dns_slow(self, event):
        """Handle DNS slow event."""
        data = event.data
        latency = data.get('latency_ms', 0)
        threshold = data.get('threshold_ms', 200)
        rumps.notification(
            title="Slow DNS Detected",
            subtitle=f"DNS: {latency:.0f}ms",
            message=f"DNS resolution is slow (threshold: {threshold:.0f}ms)",
            sound=False
        )

    def _start_monitoring(self):
        """Initialize monitoring and start timer.
        
        Note: Timers are started via a delayed mechanism because menu items
        don't have their underlying NSMenuItem objects until after rumps.run().
        """
        self.network_stats.initialize()

        # Don't start MenuAwareTimers here - they need to wait until rumps.run()
        # Instead, use a rumps.Timer that will be started by the rumps app loop
        # and will trigger the actual timer start
        self._update_timer = None
        self._sparkline_timer = None
        self._timers_started = False

    def _delayed_timer_start(self, _):
        """Called by rumps.Timer after app.run() to start actual timers."""
        if self._timers_started:
            return

        self._timers_started = True

        # Stop the startup timer (we only needed it once)
        if hasattr(self, '_startup_timer') and self._startup_timer:
            self._startup_timer.stop()
            self._startup_timer = None

        # Start the update timer with adaptive interval
        # Use MenuAwareTimer so updates continue even when menu is open
        self._update_timer = MenuAwareTimer(self._timer_callback, self._current_update_interval)
        self._update_timer.start()

        # Start a fast timer for sparkline updates (1 second) - keeps graphs smooth
        self._sparkline_timer = MenuAwareTimer(self._sparkline_timer_callback, 1.0)
        self._sparkline_timer.start()
        logger.info("Started menu-aware timers (delayed after app.run)")

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

    def _sparkline_timer_callback(self, timer):
        """Fast timer callback for sparkline updates (1 second)."""
        if not self._running:
            return
        try:
            # Get current stats for sparkline update
            stats = self.network_stats.get_current_stats()
            if stats:
                # Record history for sparklines (thread-safe)
                with self._sparkline_lock:
                    self._upload_history.append(stats.upload_speed)
                    self._download_history.append(stats.download_speed)
                    self._total_history.append(stats.upload_speed + stats.download_speed)
                    if self._current_latency is not None:
                        self._latency_history.append(self._current_latency)
                # Update sparkline display
                self._update_sparklines(stats)

            # Periodically save sparkline history (every 60 seconds)
            self._sparkline_save_counter = getattr(self, '_sparkline_save_counter', 0) + 1
            if self._sparkline_save_counter >= 60:
                self._sparkline_save_counter = 0
                self._save_sparkline_history()
        except Exception as e:
            logger.error(f"Sparkline update error: {e}", exc_info=True)

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
            # Record history for sparklines (thread-safe)
            with self._sparkline_lock:
                self._upload_history.append(stats.upload_speed)
                self._download_history.append(stats.download_speed)
                self._total_history.append(stats.upload_speed + stats.download_speed)
                if self._current_latency is not None:
                    self._latency_history.append(self._current_latency)
                if self._current_dns_latency is not None:
                    self._dns_history.append(self._current_dns_latency)

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

            # Update persistent storage with DELTA (bytes since last update)
            # This ensures data accumulates across app restarts
            if conn.is_connected:
                last_sent, last_recv = self._last_stored_bytes.get(conn_key, (0, 0))
                delta_sent = max(0, conn_sent - last_sent)
                delta_recv = max(0, conn_recv - last_recv)

                if delta_sent > 0 or delta_recv > 0:
                    self.store.update_stats(
                        conn_key,
                        delta_sent,
                        delta_recv,
                        peak_up,
                        peak_down
                    )
                    self._last_stored_bytes[conn_key] = (conn_sent, conn_recv)

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
        import math

        from PIL import Image, ImageDraw
        from app.sparkline_renderer import _get_appearance_mode

        # Color mapping - adjust for dark mode
        appearance_mode = _get_appearance_mode()
        if appearance_mode == 'dark':
            # Slightly brighter colors for dark mode
            colors = {
                "green": "#4CD964",  # Brighter green
                "yellow": "#FFCC00",  # Brighter yellow
                "red": "#FF3B30",     # Same red
                "gray": "#8E8E93",     # Same gray
            }
        else:
            # Light mode colors
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

        # Default to latency
        elif self._current_latency is not None:
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
            # Add WiFi signal strength if available
            signal_str = ""
            if conn.connection_type == "WiFi" and conn.wifi_signal_strength is not None:
                # Convert dBm to bars (approximate)
                rssi = conn.wifi_signal_strength
                if rssi >= -50:
                    signal_str = " 📶●●●"
                elif rssi >= -60:
                    signal_str = " 📶●●○"
                elif rssi >= -70:
                    signal_str = " 📶●○○"
                elif rssi >= -80:
                    signal_str = " 📶○○○"
                else:
                    signal_str = " 📶"
            if self._vpn_active:
                self.menu_connection.title = f"🔒 {name} ({ip}){signal_str}"
            else:
                self.menu_connection.title = f"{name} ({ip}){signal_str}"
        else:
            self.menu_connection.title = "Disconnected"

        # Speed (no icon - cleaner) - show up, down, and combined
        combined_speed = stats.upload_speed + stats.download_speed
        self.menu_speed.title = f"↑ {format_bytes(stats.upload_speed, True)}  ↓ {format_bytes(stats.download_speed, True)}  ⇅ {format_bytes(combined_speed, True)}"

        # Update latency display
        self._update_latency()

        # Update DNS latency display
        self._update_dns_latency()

        # Update network quality score
        self._update_quality_score()

        today_sent, today_recv = self.store.get_today_totals()
        today_total = today_sent + today_recv
        self.menu_today.title = f"Today: ↑ {format_bytes(today_sent)}  ↓ {format_bytes(today_recv)}  ⇅ {format_bytes(today_total)}"

        # Update budget status (with notifications)
        self._update_budget(conn, today_sent, today_recv)

        # Update history section
        self._update_history()

        # Update top apps
        self._update_top_apps()

        # Update top devices
        self._update_top_devices()

        # Update connection locations
        self._update_connection_locations()

        # Update events
        self._update_events()


    def _set_menu_image(self, menu_item, image_path: str, title: str = None):
        """Set an image on a menu item using AppKit with live refresh.
        
        Args:
            menu_item: The rumps MenuItem
            image_path: Path to the image file
            title: Optional new title (setting title helps force refresh)
        """
        try:
            import os

            from AppKit import NSImage

            # Update title via rumps - this syncs the internal state
            if title is not None:
                menu_item.title = title

            # For images, we need the NSMenuItem object which is only available
            # after the menu is built and the app is running
            ns_item = getattr(menu_item, '_menuitem', None)
            if ns_item is None:
                # Menu not built yet, title update via rumps is enough
                return

            # Set title via AppKit as well to force visual update
            if title is not None:
                ns_item.setTitle_(title)

            # Try to set image if file exists
            if image_path and os.path.exists(image_path):
                # Load image directly - use unique filenames to bypass cache
                image = NSImage.alloc().initWithContentsOfFile_(image_path)
                if image:
                    ns_item.setImage_(image)

        except Exception as e:
            logger.error(f"Failed to set menu image: {e}")

    def _update_sparklines(self, stats):
        """Update the sparkline graph display with matplotlib line graphs."""
        # Get appearance-aware colors
        from app.sparkline_renderer import _get_appearance_mode, _get_appearance_colors
        appearance_mode = _get_appearance_mode()
        colors = _get_appearance_colors(appearance_mode)
        
        # Colors for each metric - use appearance-aware colors
        quality_color = colors['quality']
        up_color = colors['upload']
        down_color = colors['download']
        lat_color = colors['latency']

        # Get copies of history data (thread-safe)
        with self._sparkline_lock:
            quality_history = list(self._quality_history)
            upload_history = list(self._upload_history)
            download_history = list(self._download_history)
            total_history = list(self._total_history)
            latency_history = list(self._latency_history)
            dns_history = list(self._dns_history)

        # Quality sparkline (0-100 scale)
        quality_cur = self._quality_score if self._quality_score is not None else 0
        quality_title = f"  ◆  {quality_cur}%"
        if quality_history:
            quality_img = self._sparkline_renderer.create_image(quality_history, quality_color)
            self._set_menu_image(self.menu_graph_quality, quality_img, quality_title)
        else:
            self.menu_graph_quality.title = quality_title

        # Upload sparkline
        up_cur = stats.upload_speed if stats else 0
        up_title = f"  ↑  {format_bytes(up_cur, True)}"
        if upload_history:
            up_img = self._sparkline_renderer.create_image(upload_history, up_color)
            self._set_menu_image(self.menu_graph_upload, up_img, up_title)
        else:
            self.menu_graph_upload.title = up_title

        # Download sparkline
        down_cur = stats.download_speed if stats else 0
        down_title = f"  ↓  {format_bytes(down_cur, True)}"
        if download_history:
            down_img = self._sparkline_renderer.create_image(download_history, down_color)
            self._set_menu_image(self.menu_graph_download, down_img, down_title)
        else:
            self.menu_graph_download.title = down_title

        # Total (combined) sparkline
        total_cur = (stats.upload_speed + stats.download_speed) if stats else 0
        total_title = f"  ⇅  {format_bytes(total_cur, True)}"
        total_color = colors['total']  # Use appearance-aware color
        if total_history:
            total_img = self._sparkline_renderer.create_image(total_history, total_color)
            self._set_menu_image(self.menu_graph_total, total_img, total_title)
        else:
            self.menu_graph_total.title = total_title

        # Latency sparkline
        lat_cur = self._current_latency if self._current_latency else 0
        lat_title = f"  ●  {lat_cur:.0f}ms"
        if latency_history:
            lat_img = self._sparkline_renderer.create_image(latency_history, lat_color)
            self._set_menu_image(self.menu_graph_latency, lat_img, lat_title)
        else:
            self.menu_graph_latency.title = lat_title

        # DNS sparkline
        dns_color = colors['latency']  # Use same color as latency (appearance-aware)
        dns_cur = self._current_dns_latency if self._current_dns_latency else 0
        dns_title = f"  🔍  {dns_cur:.0f}ms"
        if dns_history:
            dns_img = self._sparkline_renderer.create_image(dns_history, dns_color)
            self._set_menu_image(self.menu_graph_dns, dns_img, dns_title)
        else:
            self.menu_graph_dns.title = dns_title

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

    def _update_dns_latency(self):
        """Update DNS latency display."""
        dns_latency = self._deps.dns_monitor.get_current_dns_latency()
        if dns_latency is not None:
            self._current_dns_latency = dns_latency
            # Record in history for sparkline (already done in event handler, but ensure it's there)
            with self._sparkline_lock:
                if not self._dns_history or self._dns_history[-1] != dns_latency:
                    self._dns_history.append(dns_latency)
            
            # Calculate average
            avg_dns = self._deps.dns_monitor.get_average_dns_latency()
            if avg_dns is not None:
                self.menu_dns.title = f"DNS: {dns_latency:.0f}ms (avg {avg_dns:.0f}ms)"
            else:
                self.menu_dns.title = f"DNS: {dns_latency:.0f}ms"
        else:
            self.menu_dns.title = "DNS: --"

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

        # Track quality history for sparkline (thread-safe)
        with self._sparkline_lock:
            self._quality_history.append(self._quality_score)

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
        week_total = weekly['sent'] + weekly['recv']
        self.menu_week.title = f"Week: ↑ {format_bytes(weekly['sent'])}  ↓ {format_bytes(weekly['recv'])}  ⇅ {format_bytes(week_total)}"

        # Get monthly totals
        monthly = self.store.get_monthly_totals()
        month_total = monthly['sent'] + monthly['recv']
        self.menu_month.title = f"Month: ↑ {format_bytes(monthly['sent'])}  ↓ {format_bytes(monthly['recv'])}  ⇅ {format_bytes(month_total)}"

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
            except (ValueError, TypeError, AttributeError):
                day_label = date_str

            sent = day_data['sent']
            recv = day_data['recv']

            if sent > 0 or recv > 0:
                total = sent + recv
                title = f"{day_label}: ↑{format_bytes(sent)} ↓{format_bytes(recv)} ⇅{format_bytes(total)}"
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
                f"Month: ↑{format_bytes(stats['sent'])} ↓{format_bytes(stats['recv'])} ⇅{format_bytes(stats['sent'] + stats['recv'])}"
            ))

            # Add weekly total if available
            weekly_stats = weekly.get('by_connection', {}).get(conn_key, {'sent': 0, 'recv': 0})
            conn_menu.add(rumps.MenuItem(
                f"Week: ↑{format_bytes(weekly_stats['sent'])} ↓{format_bytes(weekly_stats['recv'])} ⇅{format_bytes(weekly_stats['sent'] + weekly_stats['recv'])}"
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
                except (ValueError, TypeError, AttributeError):
                    day_label = date_str[:5]

                if day_data['sent'] > 0 or day_data['recv'] > 0:
                    conn_menu.add(rumps.MenuItem(
                        f"{day_label}: ↑{format_bytes(day_data['sent'])} ↓{format_bytes(day_data['recv'])} ⇅{format_bytes(day_data['sent'] + day_data['recv'])}"
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
                self.menu_apps.title = "Connections"
                self.menu_apps.add(rumps.MenuItem("No active apps"))
                return

            # Count total connections across all apps
            total_connections = sum(conns for _, _, _, conns in top_processes)
            self.menu_apps.title = f"Connections ({total_connections})"

            # Add all processes in a flat list
            for name, bytes_in, bytes_out, conns in top_processes:
                if conns > 0:
                    title = f"{name}: {conns} conn{'s' if conns > 1 else ''}"
                else:
                    title = f"{name}: idle"
                self.menu_apps.add(rumps.MenuItem(title))

        except Exception as e:
            self._safe_menu_clear(self.menu_apps)
            self.menu_apps.add(rumps.MenuItem(f"Error: {str(e)[:25]}"))

    def _update_events(self):
        """Update recent events menu - dynamically populated.
        
        Quality drop events are clickable to show troubleshooting info.
        """

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

        # Add all online devices in a flat list
        for d in online_devices:
            self.menu_devices.add(make_device_item(d))

        # Add offline devices in a separate submenu at the bottom
        if offline_devices:
            self.menu_devices.add(rumps.separator)
            offline_menu = rumps.MenuItem(f"Offline ({len(offline_devices)})")
            for d in offline_devices:
                offline_menu.add(make_device_item(d, "○ "))
            self.menu_devices.add(offline_menu)

    def _update_connection_locations(self):
        """Update connection locations menu with geolocation data."""
        try:
            countries_per_app = self._deps.connection_tracker.get_countries_per_app()
            
            self._safe_menu_clear(self.menu_locations)
            
            if not countries_per_app:
                self.menu_locations.title = "Connection Locations"
                self.menu_locations.add(rumps.MenuItem("No external connections"))
                return
            
            # Country flag emoji mapping
            flag_map = {
                'US': '🇺🇸', 'GB': '🇬🇧', 'DE': '🇩🇪', 'FR': '🇫🇷',
                'CA': '🇨🇦', 'AU': '🇦🇺', 'JP': '🇯🇵', 'CN': '🇨🇳',
                'IN': '🇮🇳', 'BR': '🇧🇷', 'MX': '🇲🇽', 'IT': '🇮🇹',
                'ES': '🇪🇸', 'NL': '🇳🇱', 'SE': '🇸🇪', 'NO': '🇳🇴',
                'DK': '🇩🇰', 'FI': '🇫🇮', 'PL': '🇵🇱', 'RU': '🇷🇺',
            }
            
            # Get country names
            geoloc = self._deps.geolocation_service
            
            for app_name, country_codes in sorted(countries_per_app.items(), key=lambda x: len(x[1]), reverse=True):
                if not country_codes:
                    continue
                
                # Format countries with flags
                country_display = []
                for code in country_codes[:5]:  # Limit to 5 countries per app
                    flag = flag_map.get(code, '🌍')
                    name = geoloc.get_country_name(code)
                    country_display.append(f"{flag} {name}")
                
                if len(country_codes) > 5:
                    country_display.append(f"... ({len(country_codes) - 5} more)")
                
                title = f"{app_name}: {', '.join(country_display)}"
                self.menu_locations.add(rumps.MenuItem(title))
            
            if not self.menu_locations._menu or len(self.menu_locations._menu) == 0:
                self.menu_locations.title = "Connection Locations"
                self.menu_locations.add(rumps.MenuItem("No external connections"))
            else:
                self.menu_locations.title = f"Connection Locations ({len(countries_per_app)} apps)"
        except Exception as e:
            logger.error(f"Error updating connection locations: {e}", exc_info=True)
            self._safe_menu_clear(self.menu_locations)
            self.menu_locations.add(rumps.MenuItem("Error loading locations"))

    def _rename_device(self, device):
        """Show dialog to rename a device."""
        current_name = device.custom_name or device.display_name

        response = rumps.Window(
            title="Rename Device",
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
                    "Using auto-detected name"
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

    def _run_speed_test(self, _):
        """Run a network speed test."""
        if self._speed_test.is_running:
            rumps.alert(
                title="Speed Test",
                message="A speed test is already running. Please wait for it to complete.",
                ok="OK"
            )
            return

        # Confirm before running (speed tests use bandwidth)
        response = rumps.alert(
            title="Run Speed Test",
            message="This will test your network speed by downloading test data.\n\nThis may take 10-15 seconds and will use some bandwidth.\n\nContinue?",
            ok="Run Test",
            cancel="Cancel"
        )
        if response != 1:
            return

        # Run test in background thread
        threading.Thread(target=self._execute_speed_test, daemon=True).start()

    def _show_detailed_graphs(self, _):
        """Show detailed historical graphs in a popup window."""
        try:
            from app.views.graph_window import GraphWindow
            graph_window = GraphWindow(self.store)
            graph_window.show()
            logger.info("Graph window requested")
        except Exception as e:
            logger.error(f"Error creating graph window: {e}", exc_info=True)
            rumps.notification(
                title="Graph Window Error",
                subtitle="Could not open",
                message=str(e)[:100],
                sound=False
            )

    def _show_alert_on_main_thread(self, title: str, message: str):
        """Show a rumps alert on the main thread (required by macOS)."""
        def show_alert():
            rumps.alert(title=title, message=message, ok="OK")
        NSOperationQueue.mainQueue().addOperationWithBlock_(show_alert)

    def _execute_speed_test(self):
        """Execute the speed test in a background thread."""
        try:
            rumps.notification(
                title="Network Monitor",
                subtitle="Speed Test",
                message="Running speed test... This may take 10-15 seconds."
            )

            results = self._speed_test.run_test(duration_seconds=10)

            if results:
                download = results.get('download_mbps', 0)
                upload = results.get('upload_mbps', 0)
                latency = results.get('latency_ms', 0)

                message = f"Download: {download:.1f} Mbps\n"
                if upload > 0:
                    message += f"Upload: {upload:.1f} Mbps\n"
                message += f"Latency: {latency:.0f} ms"

                self._show_alert_on_main_thread("Speed Test Results", message)
            else:
                self._show_alert_on_main_thread(
                    "Speed Test",
                    "Speed test failed. Please check your internet connection."
                )
        except Exception as e:
            logger.error(f"Speed test error: {e}", exc_info=True)
            self._show_alert_on_main_thread(
                "Speed Test Error",
                f"An error occurred: {e}"
            )

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
        self._last_stored_bytes = {}  # Reset delta tracking
        # Clear history (thread-safe)
        with self._sparkline_lock:
            self._upload_history.clear()
            self._download_history.clear()
            self._total_history.clear()
            self._latency_history.clear()
            self._quality_history.clear()
            self._dns_history.clear()
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

        # Get usage for the budget period (specific to this connection)
        if budget.period == "daily":
            # Get today's stats for this specific connection
            today_stats = self.store.get_today_stats(conn_key)
            if today_stats:
                usage = today_stats.bytes_sent + today_stats.bytes_recv
            else:
                usage = 0
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
                "app_version": "1.5.0",
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

    def _export_to_influxdb(self, _):
        """Export metrics to InfluxDB."""
        from monitor.metrics_exporter import MetricsExporter
        
        exporter = MetricsExporter()
        
        # Get configuration from user
        response = rumps.Window(
            title="Export to InfluxDB",
            message="Enter InfluxDB configuration:\n\nEndpoint URL:\nToken:\nOrganization:\nBucket:",
            default_text="http://localhost:8086\n\nyour-token\n\nyour-org\n\nnetwork-monitor",
            ok="Export",
            cancel="Cancel"
        ).run()
        
        if not response.clicked:
            return
        
        try:
            lines = response.text.strip().split('\n')
            if len(lines) < 4:
                rumps.alert("Invalid", "Please provide all 4 values: endpoint, token, org, bucket")
                return
            
            endpoint = lines[0].strip()
            token = lines[1].strip()
            org = lines[2].strip()
            bucket = lines[3].strip()
            
            # Collect current metrics
            stats = self.network_stats.get_current_stats()
            online, total = self.network_scanner.get_device_count()
            
            export_data = {
                'upload_speed': stats.upload_speed if stats else 0,
                'download_speed': stats.download_speed if stats else 0,
                'latency_ms': self._current_latency or 0,
                'quality_score': self._quality_score or 0,
                'device_count': online,
            }
            
            success = exporter.export_to_influxdb(export_data, endpoint, token, org, bucket)
            
            if success:
                rumps.notification(
                    title="Network Monitor",
                    subtitle="InfluxDB Export",
                    message="Metrics exported successfully"
                )
            else:
                rumps.alert("Export Failed", "Could not export to InfluxDB. Check logs for details.")
        except Exception as e:
            logger.error(f"InfluxDB export error: {e}", exc_info=True)
            rumps.alert("Export Error", f"Could not export to InfluxDB: {e}")

    def _export_to_prometheus(self, _):
        """Export metrics to Prometheus Pushgateway."""
        from monitor.metrics_exporter import MetricsExporter
        
        exporter = MetricsExporter()
        
        # Get configuration from user
        response = rumps.Window(
            title="Export to Prometheus",
            message="Enter Prometheus Pushgateway URL:",
            default_text="http://localhost:9091",
            ok="Export",
            cancel="Cancel"
        ).run()
        
        if not response.clicked:
            return
        
        try:
            gateway_url = response.text.strip()
            if not gateway_url:
                rumps.alert("Invalid", "Please provide a Pushgateway URL")
                return
            
            # Collect current metrics
            stats = self.network_stats.get_current_stats()
            online, total = self.network_scanner.get_device_count()
            
            export_data = {
                'upload_speed': stats.upload_speed if stats else 0,
                'download_speed': stats.download_speed if stats else 0,
                'latency_ms': self._current_latency or 0,
                'quality_score': self._quality_score or 0,
                'device_count': online,
            }
            
            success = exporter.export_to_prometheus(export_data, gateway_url)
            
            if success:
                rumps.notification(
                    title="Network Monitor",
                    subtitle="Prometheus Export",
                    message="Metrics exported successfully"
                )
            else:
                rumps.alert("Export Failed", "Could not export to Prometheus. Check logs for details.")
        except Exception as e:
            logger.error(f"Prometheus export error: {e}", exc_info=True)
            rumps.alert("Export Error", f"Could not export to Prometheus: {e}")

    # === Backup/Restore Methods ===

    def _create_backup(self, _):
        """Create a database backup."""

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
        about_text = """Network Monitor v1.7.0

A lightweight macOS menu bar app for monitoring network activity.

Features:
• Live sparkline graphs (quality, speed, latency, DNS)
• Real-time upload/download speed tracking
• Network quality score (0-100%)
• WiFi signal strength monitoring
• On-demand network speed testing
• Per-connection data budgets with alerts
• Network device discovery with device type detection
• Per-app bandwidth tracking with throttling alerts
• DNS performance monitoring with latency tracking
• IP geolocation for external connections
• Historical graphs window (daily/weekly/monthly)
• Network change notifications (devices, quality, VPN)
• Metrics export to InfluxDB and Prometheus
• Dark mode aware icons and sparklines
• Daily/weekly/monthly statistics
• Persistent history across restarts
• SQLite database with backup/restore
• Launch at login support

v1.7.0: Major Feature Update
• Bandwidth throttling alerts with per-app thresholds
• Historical graphs window with matplotlib
• Network change notifications (devices, quality, VPN)
• DNS performance monitoring with sparkline
• IP geolocation tracking for external connections
• InfluxDB and Prometheus metrics export
• Keyboard shortcuts framework
• Dark mode aware icons and sparklines
• Improved speed test with better reliability

v1.6.0: Code quality improvements
• Extracted SparklineRenderer for better modularity
• Converted DeviceType to proper Enum
• Added thread-safe sparkline history access
• Fixed budget notification state management
• Added WiFi signal strength monitoring
• Added on-demand speed test feature
• Improved error handling and code organization

Data is stored locally in:
~/.network-monitor/

Built with Python, rumps, PIL, and matplotlib.

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

    def _load_sparkline_history(self) -> None:
        """Load sparkline history from persistent storage."""
        history_file = self.store.data_dir / "sparkline_history.json"
        logger.debug(f"Loading sparkline history from: {history_file}")
        try:
            if history_file.exists():
                with open(history_file) as f:
                    data = json.load(f)

                # Load each history, respecting maxlen (thread-safe)
                with self._sparkline_lock:
                    for val in data.get('upload', []):
                        self._upload_history.append(val)
                    for val in data.get('download', []):
                        self._download_history.append(val)
                    for val in data.get('total', []):
                        self._total_history.append(val)
                    for val in data.get('quality', []):
                        self._quality_history.append(val)
                    for val in data.get('latency', []):
                        self._latency_history.append(val)
                    for val in data.get('dns', []):
                        self._dns_history.append(val)

                logger.info(f"Loaded sparkline history: {len(self._quality_history)} quality, {len(self._upload_history)} upload, {len(self._total_history)} total samples")
            else:
                logger.info(f"No sparkline history file at {history_file}, starting fresh")
        except Exception as e:
            logger.warning(f"Could not load sparkline history: {e}")

    def _save_sparkline_history(self) -> None:
        """Save sparkline history to persistent storage."""
        history_file = self.store.data_dir / "sparkline_history.json"
        try:
            # Get copies of history data (thread-safe)
            with self._sparkline_lock:
                data = {
                    'upload': list(self._upload_history),
                    'download': list(self._download_history),
                    'total': list(self._total_history),
                    'quality': list(self._quality_history),
                    'latency': list(self._latency_history),
                    'dns': list(self._dns_history),
                }
            with open(history_file, 'w') as f:
                json.dump(data, f)
            logger.info(f"Saved sparkline history: {len(data['quality'])} quality, {len(data['upload'])} upload samples to {history_file}")
        except Exception as e:
            logger.error(f"Could not save sparkline history to {history_file}: {e}")

    def _quit(self, _):
        """Quit the application."""
        logger.info("Application shutting down...")
        self._running = False
        # Stop controller
        if hasattr(self, '_controller'):
            self._controller.stop()
        # Stop timers
        if hasattr(self, '_sparkline_timer'):
            self._sparkline_timer.stop()
        if hasattr(self, '_update_timer'):
            self._update_timer.stop()
        self._save_sparkline_history()  # Persist graph history
        self.store.flush()  # Save any pending data
        self._cleanup_temp_files()
        logger.info("Shutdown complete")
        rumps.quit_application()


def main():
    """Entry point for the application."""
    # Try to acquire the lock first
    if not _singleton_lock.acquire():
        # Another instance is running - kill it and take over
        if not _singleton_lock.kill_existing():
            print("Could not stop existing instance.", file=sys.stderr)
            sys.exit(1)

        # Try to acquire the lock again after killing
        import time as time_module
        time_module.sleep(0.5)  # Give the lock file time to be released

        if not _singleton_lock.acquire():
            print("Could not acquire lock after stopping existing instance.", file=sys.stderr)
            sys.exit(1)

    # Register lock release on exit
    atexit.register(_singleton_lock.release)

    # Initialize logging
    data_dir = Path.home() / STORAGE.DATA_DIR_NAME
    setup_logging(data_dir=data_dir, debug=False, console_output=True)
    logger.info("Network Monitor starting...")

    app = None

    def signal_handler(signum, frame):
        """Handle SIGTERM/SIGINT to save data before exit."""
        logger.info(f"Received signal {signum}, saving data...")
        if app:
            try:
                app._save_sparkline_history()
                app.store.flush()
                logger.info("Data saved, quitting...")
                rumps.quit_application()
            except Exception as e:
                logger.error(f"Error saving on signal: {e}")
                rumps.quit_application()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        app = NetworkMonitorApp()
        app.run()
    except Exception as e:
        logger.critical(f"Application crashed: {e}", exc_info=True)
        raise
    finally:
        # Ensure data is saved on any exit
        if app:
            try:
                app._save_sparkline_history()
            except Exception:
                pass
        _singleton_lock.release()


if __name__ == "__main__":
    main()
