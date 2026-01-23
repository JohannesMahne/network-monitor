"""Menu building utilities for Network Monitor.

Provides helper classes and functions for constructing the rumps menu
in a maintainable way.

Usage:
    from app.views.menu_builder import MenuBuilder
    
    builder = MenuBuilder()
    menu = builder.build_main_menu(app_callbacks)
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import rumps

from config import get_logger
from monitor.network import format_bytes

logger = get_logger(__name__)


@dataclass
class MenuCallbacks:
    """Container for menu item callbacks.
    
    Centralizes all callback functions for menu items.
    """
    toggle_launch_login: Optional[Callable] = None
    set_title_display: Optional[Callable] = None
    rescan_network: Optional[Callable] = None
    reset_session: Optional[Callable] = None
    reset_today: Optional[Callable] = None
    open_data_folder: Optional[Callable] = None
    show_about: Optional[Callable] = None
    quit_app: Optional[Callable] = None
    rename_device: Optional[Callable] = None
    set_quick_budget: Optional[Callable] = None
    set_budget_period: Optional[Callable] = None
    set_custom_budget: Optional[Callable] = None
    show_all_budgets: Optional[Callable] = None


class MenuBuilder:
    """Builds and manages the application menu structure.
    
    Separates menu construction from business logic for better maintainability.
    """

    def __init__(self):
        self._menu_items: Dict[str, rumps.MenuItem] = {}
        logger.debug("MenuBuilder initialized")

    def build_main_menu(self, callbacks: MenuCallbacks) -> List:
        """Build the complete main menu structure.
        
        Args:
            callbacks: Container with callback functions for menu items.
        
        Returns:
            List of menu items for rumps.App.menu
        """
        # Sparkline graphs
        self._menu_items['graph_upload'] = rumps.MenuItem("↑ ─────────────────────")
        self._menu_items['graph_download'] = rumps.MenuItem("↓ ─────────────────────")
        self._menu_items['graph_latency'] = rumps.MenuItem("● ─────────────────────")

        # Current stats
        self._menu_items['connection'] = rumps.MenuItem("Detecting")
        self._menu_items['speed'] = rumps.MenuItem("↑ --  ↓ --")
        self._menu_items['latency'] = rumps.MenuItem("Latency: --")
        self._menu_items['today'] = rumps.MenuItem("Today: ↑ --  ↓ --")
        self._menu_items['budget'] = rumps.MenuItem("Budget: Not set")

        # Dynamic submenus
        self._menu_items['devices'] = rumps.MenuItem("Devices")
        self._menu_items['apps'] = rumps.MenuItem("Connections")
        self._menu_items['events'] = rumps.MenuItem("Recent Events")

        # History submenu
        self._menu_items['history'] = self._build_history_menu()

        # Settings submenu
        self._menu_items['settings'] = self._build_settings_menu(callbacks)

        # Actions submenu
        self._menu_items['actions'] = self._build_actions_menu(callbacks)

        # Build final menu
        menu = [
            self._menu_items['graph_upload'],
            self._menu_items['graph_download'],
            self._menu_items['graph_latency'],
            rumps.separator,
            self._menu_items['connection'],
            self._menu_items['speed'],
            self._menu_items['latency'],
            self._menu_items['today'],
            self._menu_items['budget'],
            rumps.separator,
            self._menu_items['devices'],
            self._menu_items['apps'],
            self._menu_items['history'],
            self._menu_items['events'],
            rumps.separator,
            self._menu_items['settings'],
            self._menu_items['actions'],
            rumps.separator,
            rumps.MenuItem("About", callback=callbacks.show_about),
            rumps.MenuItem("Quit", callback=callbacks.quit_app),
        ]

        return menu

    def _build_history_menu(self) -> rumps.MenuItem:
        """Build the history submenu."""
        history = rumps.MenuItem("History")

        self._menu_items['week'] = rumps.MenuItem("Week: ↑ --  ↓ --")
        self._menu_items['month'] = rumps.MenuItem("Month: ↑ --  ↓ --")
        self._menu_items['daily_history'] = rumps.MenuItem("Daily Breakdown")
        self._menu_items['connection_history'] = rumps.MenuItem("By Connection")

        history.add(self._menu_items['week'])
        history.add(self._menu_items['month'])
        history.add(rumps.separator)
        history.add(self._menu_items['daily_history'])
        history.add(self._menu_items['connection_history'])

        return history

    def _build_settings_menu(self, callbacks: MenuCallbacks) -> rumps.MenuItem:
        """Build the settings submenu."""
        settings = rumps.MenuItem("Settings")

        # Launch at login (will be configured by controller)
        self._menu_items['launch_login'] = rumps.MenuItem(
            "○ Launch at Login: Off",
            callback=callbacks.toggle_launch_login
        )
        settings.add(self._menu_items['launch_login'])
        settings.add(rumps.separator)

        # Title display options
        self._menu_items['title_display'] = rumps.MenuItem("Menu Bar Display")
        settings.add(self._menu_items['title_display'])
        settings.add(rumps.separator)

        # Budget management
        self._menu_items['budgets'] = rumps.MenuItem("Data Budgets")
        settings.add(self._menu_items['budgets'])

        return settings

    def _build_actions_menu(self, callbacks: MenuCallbacks) -> rumps.MenuItem:
        """Build the actions submenu."""
        actions = rumps.MenuItem("Actions")

        actions.add(rumps.MenuItem("Rescan Network", callback=callbacks.rescan_network))
        actions.add(rumps.separator)
        actions.add(rumps.MenuItem("Reset Session", callback=callbacks.reset_session))
        actions.add(rumps.MenuItem("Reset Today", callback=callbacks.reset_today))
        actions.add(rumps.separator)
        actions.add(rumps.MenuItem("Open Data Folder", callback=callbacks.open_data_folder))

        return actions

    def get_item(self, key: str) -> Optional[rumps.MenuItem]:
        """Get a menu item by key."""
        return self._menu_items.get(key)

    def update_connection(self, name: str, ip: str, is_connected: bool) -> None:
        """Update the connection menu item."""
        item = self._menu_items.get('connection')
        if item:
            if is_connected:
                display_name = name[:25] if len(name) <= 25 else name[:22] + "..."
                item.title = f"{display_name} ({ip})"
            else:
                item.title = "Disconnected"

    def update_speed(self, upload: float, download: float) -> None:
        """Update the speed menu item."""
        item = self._menu_items.get('speed')
        if item:
            item.title = f"↑ {format_bytes(upload, True)}  ↓ {format_bytes(download, True)}"

    def update_latency(self, latency: Optional[float], avg_latency: Optional[float] = None) -> None:
        """Update the latency menu item."""
        item = self._menu_items.get('latency')
        if item:
            if latency is not None:
                if avg_latency is not None:
                    item.title = f"Latency: {latency:.0f}ms (avg {avg_latency:.0f}ms)"
                else:
                    item.title = f"Latency: {latency:.0f}ms"
            else:
                item.title = "Latency: --"

    def update_today(self, sent: int, recv: int) -> None:
        """Update the today's usage menu item."""
        item = self._menu_items.get('today')
        if item:
            item.title = f"Today: ↑ {format_bytes(sent)}  ↓ {format_bytes(recv)}"

    def update_budget(self, text: str) -> None:
        """Update the budget menu item."""
        item = self._menu_items.get('budget')
        if item:
            item.title = text

    def update_week(self, sent: int, recv: int) -> None:
        """Update the weekly stats menu item."""
        item = self._menu_items.get('week')
        if item:
            item.title = f"Week: ↑ {format_bytes(sent)}  ↓ {format_bytes(recv)}"

    def update_month(self, sent: int, recv: int) -> None:
        """Update the monthly stats menu item."""
        item = self._menu_items.get('month')
        if item:
            item.title = f"Month: ↑ {format_bytes(sent)}  ↓ {format_bytes(recv)}"

    def update_sparkline_title(self, key: str, title: str) -> None:
        """Update a sparkline menu item's title."""
        item = self._menu_items.get(key)
        if item:
            item.title = title

    def set_menu_image(self, key: str, image_path: str) -> None:
        """Set an image on a menu item."""
        item = self._menu_items.get(key)
        if item:
            try:
                from AppKit import NSImage
                image = NSImage.alloc().initWithContentsOfFile_(image_path)
                if image:
                    item._menuitem.setImage_(image)
            except Exception:
                pass  # nosec B110 - Menu image is non-critical UI feature

    @staticmethod
    def safe_menu_clear(menu_item: rumps.MenuItem) -> None:
        """Safely clear a menu item's submenu contents."""
        try:
            if menu_item and hasattr(menu_item, '_menu') and menu_item._menu:
                menu_item.clear()
        except (AttributeError, TypeError):
            pass

    @staticmethod
    def create_progress_bar(percent: float, width: int = 12) -> str:
        """Create a Unicode progress bar."""
        filled = int(percent / 100 * width)
        empty = width - filled
        bar = "█" * filled + "░" * empty
        return f"[{bar}]"
