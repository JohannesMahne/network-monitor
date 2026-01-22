"""Application controller for Network Monitor.

Orchestrates the business logic and coordinates between components.
Uses dependency injection for testability.

Usage:
    from app.controller import AppController
    from app.dependencies import create_dependencies
    
    deps = create_dependencies()
    controller = AppController(deps)
    controller.start()
"""
import time
import threading
from typing import Optional, Tuple, List
from collections import deque
from datetime import datetime

from config import get_logger, INTERVALS, THRESHOLDS
from app.dependencies import AppDependencies
from app.events import EventBus, EventType, get_event_bus

logger = get_logger(__name__)


class AppController:
    """Central controller that orchestrates application logic.
    
    Separates business logic from UI concerns. The controller:
    - Manages the update loop
    - Coordinates between monitoring components
    - Publishes events for state changes
    - Provides data to the UI layer
    
    Attributes:
        deps: The dependency container with all components.
        event_bus: Event bus for publishing state changes.
    """
    
    def __init__(self, deps: AppDependencies, event_bus: Optional[EventBus] = None):
        """Initialize the controller with dependencies.
        
        Args:
            deps: AppDependencies container with all required components.
            event_bus: Optional event bus (uses global if not provided).
        """
        self.deps = deps
        self.event_bus = event_bus or deps.event_bus or get_event_bus()
        
        # State tracking
        self._running = False
        self._last_connection_key = ""
        self._connection_start_bytes = (0, 0)
        self._last_stored_bytes: dict = {}  # Track last bytes sent to DB to compute delta
        self._last_device_scan = 0
        self._last_latency_check = 0
        self._current_latency: Optional[float] = None
        self._latency_samples: List[float] = []
        
        # History for sparklines
        self._upload_history: deque = deque(maxlen=THRESHOLDS.SPARKLINE_HISTORY_SIZE)
        self._download_history: deque = deque(maxlen=THRESHOLDS.SPARKLINE_HISTORY_SIZE)
        self._latency_history: deque = deque(maxlen=THRESHOLDS.SPARKLINE_HISTORY_SIZE)
        
        logger.info("AppController initialized")
    
    def start(self) -> None:
        """Start the controller and initialize monitoring."""
        logger.info("Starting AppController...")
        self._running = True
        
        # Initialize network stats
        self.deps.network_stats.initialize()
        
        # Publish starting event
        self.event_bus.publish(EventType.APP_STARTING)
        
        # Start initial device scan in background
        threading.Thread(target=self._initial_device_scan, daemon=True).start()
        
        logger.info("AppController started")
    
    def stop(self) -> None:
        """Stop the controller and clean up."""
        logger.info("Stopping AppController...")
        self._running = False
        
        # Flush data
        self.deps.store.flush()
        
        # Publish stopping event
        self.event_bus.publish(EventType.APP_STOPPING)
        
        logger.info("AppController stopped")
    
    def update(self) -> dict:
        """Perform one update cycle and return current state.
        
        This should be called periodically (e.g., every 2 seconds).
        
        Returns:
            Dictionary with current state data for UI updates.
        """
        if not self._running:
            return {}
        
        current_time = time.time()
        state = {}
        
        # Get current connection info
        conn = self.deps.connection_detector.get_current_connection()
        conn_key = self.deps.connection_detector.get_connection_key()
        state['connection'] = conn
        state['connection_key'] = conn_key
        
        # Check for connection changes
        if conn_key != self._last_connection_key:
            self._handle_connection_change(conn_key)
        
        # Check connectivity issues
        self.deps.issue_detector.check_connectivity(conn.is_connected)
        
        # Scan for network devices periodically
        if current_time - self._last_device_scan >= INTERVALS.DEVICE_SCAN_SECONDS:
            self._last_device_scan = current_time
            threading.Thread(target=self._scan_devices, daemon=True).start()
        
        # Get network stats
        stats = self.deps.network_stats.get_current_stats()
        state['stats'] = stats
        
        if stats:
            # Record history for sparklines
            self._upload_history.append(stats.upload_speed)
            self._download_history.append(stats.download_speed)
            if self._current_latency is not None:
                self._latency_history.append(self._current_latency)
            
            state['upload_history'] = list(self._upload_history)
            state['download_history'] = list(self._download_history)
            state['latency_history'] = list(self._latency_history)
            
            # Check for latency issues
            self.deps.issue_detector.check_latency()
            
            # Get averages and peaks
            avg_up, avg_down = self.deps.network_stats.get_average_speeds()
            peak_up, peak_down = self.deps.network_stats.get_peak_speeds()
            state['avg_speeds'] = (avg_up, avg_down)
            state['peak_speeds'] = (peak_up, peak_down)
            
            # Check for speed drops
            total_speed = stats.download_speed + stats.upload_speed
            avg_total = avg_up + avg_down
            self.deps.issue_detector.check_speed_drop(total_speed, avg_total)
            
            # Calculate session totals for current connection
            session_sent, session_recv = self.deps.network_stats.get_session_totals()
            conn_sent = session_sent - self._connection_start_bytes[0]
            conn_recv = session_recv - self._connection_start_bytes[1]
            state['session_totals'] = (session_sent, session_recv)
            state['connection_totals'] = (conn_sent, conn_recv)
            
            # Update persistent storage with DELTA (bytes since last update)
            # This ensures data accumulates correctly across app restarts
            if conn.is_connected:
                last_sent, last_recv = self._last_stored_bytes.get(conn_key, (0, 0))
                delta_sent = max(0, conn_sent - last_sent)
                delta_recv = max(0, conn_recv - last_recv)
                
                if delta_sent > 0 or delta_recv > 0:
                    self.deps.store.update_stats(
                        conn_key,
                        delta_sent,
                        delta_recv,
                        peak_up,
                        peak_down
                    )
                    self._last_stored_bytes[conn_key] = (conn_sent, conn_recv)
            
            # Publish stats update event
            self.event_bus.publish(EventType.STATS_UPDATED, {
                'upload_speed': stats.upload_speed,
                'download_speed': stats.download_speed,
                'session_sent': session_sent,
                'session_recv': session_recv,
            })
        
        # Update latency (background check)
        self._check_latency(current_time)
        state['current_latency'] = self._current_latency
        state['avg_latency'] = self._get_average_latency()
        
        # Get today's totals
        today_sent, today_recv = self.deps.store.get_today_totals()
        state['today_totals'] = (today_sent, today_recv)
        
        # Get weekly and monthly totals
        state['weekly'] = self.deps.store.get_weekly_totals()
        state['monthly'] = self.deps.store.get_monthly_totals()
        
        # Check budget status
        state['budget_status'] = self._get_budget_status(conn_key, today_sent, today_recv)
        
        return state
    
    def _handle_connection_change(self, new_conn_key: str) -> None:
        """Handle a connection change event."""
        if self._last_connection_key:
            self.deps.issue_detector.log_connection_change(
                self._last_connection_key, new_conn_key
            )
            self.event_bus.publish(EventType.CONNECTION_CHANGED, {
                'old': self._last_connection_key,
                'new': new_conn_key,
            })
        
        self._last_connection_key = new_conn_key
        self._connection_start_bytes = self.deps.network_stats.get_session_totals()
        # Reset delta tracking for this connection to start fresh
        if new_conn_key in self._last_stored_bytes:
            del self._last_stored_bytes[new_conn_key]
        logger.info(f"Connection changed to: {new_conn_key}")
    
    def _scan_devices(self) -> None:
        """Scan for network devices (runs in background thread)."""
        try:
            self.deps.network_scanner.scan()
            self.deps.network_scanner.resolve_missing_hostnames()
            
            online, total = self.deps.network_scanner.get_device_count()
            self.event_bus.publish(EventType.DEVICES_SCANNED, {
                'online': online,
                'total': total,
            })
        except Exception as e:
            logger.error(f"Device scan error: {e}", exc_info=True)
    
    def _initial_device_scan(self) -> None:
        """Initial device scan on startup."""
        try:
            logger.info("Starting initial device scan...")
            
            # Quick scan first for immediate results
            self.deps.network_scanner.scan(force=True, quick=True)
            self._last_device_scan = time.time()
            
            # Then do a full scan
            time.sleep(2)
            self.deps.network_scanner.scan(force=True, quick=False)
            
            # Resolve hostnames
            time.sleep(1)
            self.deps.network_scanner.resolve_missing_hostnames()
            
            logger.info("Initial device scan completed")
        except Exception as e:
            logger.error(f"Initial device scan error: {e}", exc_info=True)
    
    def _check_latency(self, current_time: float) -> None:
        """Check latency if interval has passed."""
        if current_time - self._last_latency_check >= INTERVALS.LATENCY_CHECK_SECONDS:
            self._last_latency_check = current_time
            threading.Thread(target=self._check_latency_background, daemon=True).start()
    
    def _check_latency_background(self) -> None:
        """Check latency in background thread."""
        try:
            latency = self.deps.issue_detector.get_current_latency()
            if latency is not None:
                self._current_latency = latency
                self._latency_samples.append(latency)
                
                # Keep last N samples
                if len(self._latency_samples) > THRESHOLDS.LATENCY_SAMPLE_COUNT:
                    self._latency_samples.pop(0)
                
                self.event_bus.publish(EventType.LATENCY_UPDATE, {
                    'latency': latency,
                    'avg': self._get_average_latency(),
                })
        except Exception as e:
            logger.error(f"Latency check error: {e}", exc_info=True)
    
    def _get_average_latency(self) -> Optional[float]:
        """Get average latency from samples."""
        if self._latency_samples:
            return sum(self._latency_samples) / len(self._latency_samples)
        return None
    
    def _get_budget_status(self, conn_key: str, today_sent: int, today_recv: int) -> dict:
        """Get budget status for current connection."""
        budget = self.deps.settings.get_budget(conn_key)
        
        if not budget or not budget.enabled:
            return {'has_budget': False}
        
        # Get usage for the budget period
        if budget.period == "daily":
            usage = today_sent + today_recv
        elif budget.period == "weekly":
            weekly = self.deps.store.get_weekly_totals()
            conn_stats = weekly.get('by_connection', {}).get(conn_key, {'sent': 0, 'recv': 0})
            usage = conn_stats.get('sent', 0) + conn_stats.get('recv', 0)
        else:  # monthly
            monthly = self.deps.store.get_monthly_totals()
            conn_stats = monthly.get('by_connection', {}).get(conn_key, {'sent': 0, 'recv': 0})
            usage = conn_stats.get('sent', 0) + conn_stats.get('recv', 0)
        
        status = self.deps.settings.check_budget_status(conn_key, 0, usage)
        
        # Publish budget events
        if status.get('exceeded') and not getattr(self, '_budget_exceeded_notified', False):
            self.event_bus.publish(EventType.BUDGET_EXCEEDED, {
                'connection': conn_key,
                'usage': usage,
                'limit': budget.limit_bytes,
            })
            self._budget_exceeded_notified = True
        elif status.get('warning') and not getattr(self, '_budget_warning_notified', False):
            self.event_bus.publish(EventType.BUDGET_WARNING, {
                'connection': conn_key,
                'percent': status['percent_used'],
            })
            self._budget_warning_notified = True
        
        return status
    
    # === Action methods (called from UI) ===
    
    def force_scan_devices(self) -> None:
        """Force a device scan and notify when done."""
        threading.Thread(target=self._force_scan, daemon=True).start()
    
    def _force_scan(self) -> None:
        """Force scan implementation."""
        try:
            self.deps.network_scanner.scan(force=True)
            online, total = self.deps.network_scanner.get_device_count()
            
            self.event_bus.publish(EventType.DEVICES_SCANNED, {
                'online': online,
                'total': total,
                'forced': True,
            })
            
            logger.info(f"Force scan completed: {online} online, {total} total")
        except Exception as e:
            logger.error(f"Force scan error: {e}", exc_info=True)
    
    def reset_session(self) -> None:
        """Reset session statistics."""
        self.deps.network_stats.reset_session()
        self.deps.issue_detector.clear_issues()
        self._connection_start_bytes = (0, 0)
        self._last_stored_bytes = {}  # Reset delta tracking
        self._upload_history.clear()
        self._download_history.clear()
        self._latency_history.clear()
        self._latency_samples.clear()
        
        logger.info("Session reset")
    
    def reset_today(self) -> None:
        """Reset today's statistics."""
        self.deps.store.reset_today()
        self.deps.network_stats.reset_session()
        self.deps.issue_detector.clear_issues()
        self._last_stored_bytes = {}  # Reset delta tracking
        
        logger.info("Today's stats reset")
    
    def rename_device(self, mac_address: str, name: str) -> None:
        """Rename a network device."""
        self.deps.network_scanner.set_device_name(mac_address, name)
        
        self.event_bus.publish(EventType.DEVICE_RENAMED, {
            'mac': mac_address,
            'name': name,
        })
        
        logger.info(f"Device {mac_address} renamed to: {name}")
    
    def get_devices(self) -> list:
        """Get all network devices."""
        return self.deps.network_scanner.get_all_devices()
    
    def get_device_count(self) -> Tuple[int, int]:
        """Get (online, total) device counts."""
        return self.deps.network_scanner.get_device_count()
    
    def get_top_processes(self, limit: int = 15) -> list:
        """Get top processes by network activity."""
        return self.deps.traffic_monitor.get_top_processes(limit=limit)
    
    def get_recent_issues(self, count: int = 10) -> list:
        """Get recent network issues."""
        return self.deps.issue_detector.get_recent_issues(count)
    
    def get_latency_color(self, latency: Optional[float] = None) -> str:
        """Get status color for current latency."""
        lat = latency if latency is not None else self._current_latency
        if lat is not None:
            return self.deps.settings.get_latency_color(lat)
        return "gray"
    
    def get_title_display_mode(self) -> str:
        """Get current title display mode."""
        return self.deps.settings.get_title_display()
    
    def set_title_display_mode(self, mode: str) -> None:
        """Set title display mode."""
        self.deps.settings.set_title_display(mode)
        self.event_bus.publish(EventType.SETTINGS_CHANGED, {'title_display': mode})
    
    def get_launch_status(self) -> str:
        """Get launch at login status text."""
        return self.deps.launch_manager.get_status()
    
    def toggle_launch_at_login(self) -> Tuple[bool, str]:
        """Toggle launch at login setting."""
        return self.deps.launch_manager.toggle()
