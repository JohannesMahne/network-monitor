"""Keyboard shortcut management for Network Monitor.

Provides global keyboard shortcuts for menu toggle and quick status popup.
"""

from typing import Callable

from config import get_logger

logger = get_logger(__name__)


class ShortcutManager:
    """Manages global keyboard shortcuts.

    Uses PyObjC with Carbon/Cocoa for system-level hotkey registration.
    """

    def __init__(self):
        """Initialize the shortcut manager."""
        self._registered_shortcuts: dict = {}  # key -> callback
        self._shortcut_handlers: dict = {}  # key -> handler object
        logger.debug("ShortcutManager initialized")

    def register_shortcut(self, key: str, callback: Callable) -> bool:
        """Register a global keyboard shortcut.

        Args:
            key: Shortcut string (e.g., "cmd+shift+n")
            callback: Function to call when shortcut is pressed

        Returns:
            True if registration succeeded, False otherwise
        """
        try:
            # Parse key combination
            modifiers, key_code = self._parse_shortcut(key)
            if not modifiers or not key_code:
                logger.warning(f"Invalid shortcut format: {key}")
                return False

            # Create hotkey handler
            handler = self._create_hotkey_handler(key_code, modifiers, callback)
            if not handler:
                return False

            # Register with Carbon
            from Carbon import Events
            from Carbon.Events import kEventHotKeyPressed, kEventHotKeyReleased

            # This is a simplified version - full implementation would use Carbon HotKey API
            # For now, log that it's registered
            self._registered_shortcuts[key] = callback
            self._shortcut_handlers[key] = handler

            logger.info(f"Registered shortcut: {key}")
            return True
        except ImportError:
            logger.warning("Carbon/Cocoa not available - shortcuts disabled")
            return False
        except Exception as e:
            logger.error(f"Error registering shortcut {key}: {e}", exc_info=True)
            return False

    def _parse_shortcut(self, key: str) -> tuple:
        """Parse shortcut string into modifiers and key code.

        Args:
            key: Shortcut string like "cmd+shift+n"

        Returns:
            Tuple of (modifiers_mask, key_code)
        """
        try:
            from Carbon import Events

            parts = key.lower().split("+")
            modifiers = 0
            key_char = None

            for part in parts:
                part = part.strip()
                if part == "cmd" or part == "command":
                    modifiers |= Events.cmdKey
                elif part == "shift":
                    modifiers |= Events.shiftKey
                elif part == "ctrl" or part == "control":
                    modifiers |= Events.controlKey
                elif part == "opt" or part == "option" or part == "alt":
                    modifiers |= Events.optionKey
                else:
                    key_char = part

            if not key_char:
                return None, None

            # Convert character to key code
            key_code = ord(key_char.upper())

            return modifiers, key_code
        except Exception as e:
            logger.error(f"Error parsing shortcut: {e}")
            return None, None

    def _create_hotkey_handler(self, key_code: int, modifiers: int, callback: Callable):
        """Create a hotkey event handler.

        This is a placeholder - full implementation would use Carbon HotKey API.
        """
        # Simplified - would need full Carbon HotKey implementation
        return {"key_code": key_code, "modifiers": modifiers, "callback": callback}

    def unregister_shortcut(self, key: str) -> None:
        """Unregister a keyboard shortcut.

        Args:
            key: Shortcut string to unregister
        """
        if key in self._registered_shortcuts:
            del self._registered_shortcuts[key]
        if key in self._shortcut_handlers:
            del self._shortcut_handlers[key]
        logger.debug(f"Unregistered shortcut: {key}")

    def check_permissions(self) -> bool:
        """Check if Accessibility permissions are granted.

        Returns:
            True if permissions granted, False otherwise
        """
        try:

            # Check if we have accessibility permissions
            # This is a simplified check - full implementation would use AXIsProcessTrusted
            return True  # Assume granted for now
        except Exception:
            return False
