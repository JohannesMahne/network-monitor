"""Menu-aware timer for macOS menu bar applications.

Provides a timer that continues running even when the menu is open,
using performSelectorOnMainThread for UI thread safety.

Usage:
    from app.timer import MenuAwareTimer

    def on_tick(timer):
        print("Tick!")

    timer = MenuAwareTimer(on_tick, interval=2.0)
    timer.start()
"""

import threading
import time
from typing import Callable, Optional

from config import get_logger

logger = get_logger(__name__)


# Global callback helper for MenuAwareTimer - defined once at module level
_TimerCallbackHelper = None
_TimerCallbackHelperLock = threading.Lock()


def _get_timer_callback_helper():
    """Get or create the global callback helper class (thread-safe)."""
    global _TimerCallbackHelper

    # Fast path - already created
    if _TimerCallbackHelper is not None:
        return _TimerCallbackHelper

    # Slow path - need to create (with lock to avoid race condition)
    with _TimerCallbackHelperLock:
        # Double-check after acquiring lock
        if _TimerCallbackHelper is not None:
            return _TimerCallbackHelper

        from Foundation import NSObject

        class _MenuAwareTimerHelper(NSObject):
            """Helper object to dispatch timer callbacks to main thread."""

            callback_ref = None
            timer_ref = None

            def doCallback_(self, _):
                if self.callback_ref and self.timer_ref and self.timer_ref._running:
                    try:
                        self.callback_ref(self.timer_ref)
                    except Exception:
                        pass

        _TimerCallbackHelper = _MenuAwareTimerHelper

    return _TimerCallbackHelper


class MenuAwareTimer:
    """Timer that continues running even when menu is open.

    Uses a background thread with performSelectorOnMainThread to ensure
    UI updates happen on the main thread, even during menu tracking.

    Attributes:
        interval: Time between timer ticks in seconds.

    Example:
        >>> timer = MenuAwareTimer(callback, interval=1.0)
        >>> timer.start()
        >>> # Later...
        >>> timer.stop()
    """

    def __init__(self, callback: Callable, interval: float):
        """Initialize the timer.

        Args:
            callback: Function to call on each tick. Receives the timer as argument.
            interval: Time between ticks in seconds.
        """
        self._callback = callback
        self._interval = interval
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._helper = None

    @property
    def interval(self) -> float:
        """Get the current interval."""
        return self._interval

    @interval.setter
    def interval(self, value: float) -> None:
        """Update interval."""
        with self._lock:
            self._interval = value

    def _timer_loop(self) -> None:
        """Background thread that schedules callbacks on main thread."""
        # Get or create the helper class
        HelperClass = _get_timer_callback_helper()

        helper = HelperClass.alloc().init()
        helper.callback_ref = self._callback
        helper.timer_ref = self
        self._helper = helper

        while self._running:
            time.sleep(self._interval)
            if self._running:
                # Dispatch to main thread using performSelectorOnMainThread
                helper.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "doCallback:", None, False
                )

    def start(self) -> None:
        """Start the timer in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._thread.start()
        logger.debug(f"MenuAwareTimer started with interval {self._interval}s")

    def stop(self) -> None:
        """Stop the timer."""
        self._running = False
        self._helper = None
        self._thread = None
        logger.debug("MenuAwareTimer stopped")
