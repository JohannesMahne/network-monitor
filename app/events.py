"""Event bus for internal application communication.

Provides a publish/subscribe mechanism for decoupled component communication.
Components can subscribe to events and publish events without direct references.

Usage:
    from app.events import EventBus, EventType
    
    bus = EventBus()
    
    # Subscribe to events
    bus.subscribe(EventType.CONNECTION_CHANGED, lambda e: print(f"Connection: {e.data}"))
    
    # Publish events
    bus.publish(EventType.CONNECTION_CHANGED, {"old": "WiFi:Home", "new": "WiFi:Office"})
"""
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

from config import get_logger

logger = get_logger(__name__)


class EventType(Enum):
    """Types of events that can be published/subscribed."""

    # Connection events
    CONNECTION_CHANGED = auto()
    CONNECTION_LOST = auto()
    CONNECTION_RESTORED = auto()

    # Network stats events
    STATS_UPDATED = auto()
    SPEED_UPDATE = auto()
    LATENCY_UPDATE = auto()

    # Device events
    DEVICE_DISCOVERED = auto()
    DEVICE_OFFLINE = auto()
    DEVICE_RENAMED = auto()
    DEVICES_SCANNED = auto()

    # Budget events
    BUDGET_WARNING = auto()
    BUDGET_EXCEEDED = auto()
    BUDGET_CHANGED = auto()

    # Issue events
    ISSUE_DETECTED = auto()
    HIGH_LATENCY = auto()
    SPEED_DROP = auto()

    # App lifecycle events
    APP_STARTING = auto()
    APP_STOPPING = auto()
    SETTINGS_CHANGED = auto()

    # UI events
    MENU_REFRESH_NEEDED = auto()
    TITLE_UPDATE_NEEDED = auto()


@dataclass
class Event:
    """Represents an event with type and data.
    
    Attributes:
        event_type: The type of event.
        data: Optional dictionary with event-specific data.
        timestamp: When the event was created.
        source: Optional identifier of the event source.
    """
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: Optional[str] = None

    def __str__(self) -> str:
        return f"Event({self.event_type.name}, data={self.data})"


# Type alias for event handlers
EventHandler = Callable[[Event], None]


class EventBus:
    """Thread-safe publish/subscribe event bus.
    
    Allows components to communicate without direct coupling.
    Events are processed asynchronously by default.
    
    Attributes:
        async_mode: If True (default), events are processed in a background thread.
    
    Example:
        >>> bus = EventBus()
        >>> bus.subscribe(EventType.STATS_UPDATED, lambda e: print(e.data))
        >>> bus.publish(EventType.STATS_UPDATED, {"speed": 1000})
    """

    def __init__(self, async_mode: bool = True):
        self._subscribers: Dict[EventType, List[EventHandler]] = {}
        self._lock = threading.Lock()
        self._async_mode = async_mode
        self._event_queue: queue.Queue = queue.Queue()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        if async_mode:
            self._start_worker()

    def _start_worker(self) -> None:
        """Start the background event processing thread."""
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._process_events,
            daemon=True,
            name="EventBus-Worker"
        )
        self._worker_thread.start()
        logger.debug("EventBus worker thread started")

    def _process_events(self) -> None:
        """Process events from the queue in background thread."""
        while self._running:
            try:
                event = self._event_queue.get(timeout=0.1)
                self._dispatch_event(event)
                self._event_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing event: {e}", exc_info=True)

    def _dispatch_event(self, event: Event) -> None:
        """Dispatch event to all subscribers."""
        with self._lock:
            handlers = self._subscribers.get(event.event_type, []).copy()

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler for {event.event_type.name}: {e}",
                    exc_info=True
                )

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to an event type.
        
        Args:
            event_type: The type of event to subscribe to.
            handler: Callback function that takes an Event parameter.
        
        Example:
            >>> def on_connection_change(event):
            ...     print(f"Connection changed: {event.data}")
            >>> bus.subscribe(EventType.CONNECTION_CHANGED, on_connection_change)
        """
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)

        logger.debug(f"Subscribed to {event_type.name}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> bool:
        """Unsubscribe from an event type.
        
        Args:
            event_type: The type of event to unsubscribe from.
            handler: The handler to remove.
        
        Returns:
            True if handler was found and removed, False otherwise.
        """
        with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(handler)
                    logger.debug(f"Unsubscribed from {event_type.name}")
                    return True
                except ValueError:
                    pass
        return False

    def publish(self, event_type: EventType, data: Dict[str, Any] = None,
                source: str = None) -> None:
        """Publish an event.
        
        Args:
            event_type: The type of event to publish.
            data: Optional data to include with the event.
            source: Optional identifier of the event source.
        
        Example:
            >>> bus.publish(EventType.SPEED_UPDATE, {"upload": 1000, "download": 5000})
        """
        event = Event(
            event_type=event_type,
            data=data or {},
            source=source
        )

        if self._async_mode:
            self._event_queue.put(event)
        else:
            self._dispatch_event(event)

        logger.debug(f"Published {event_type.name}")

    def publish_sync(self, event_type: EventType, data: Dict[str, Any] = None,
                     source: str = None) -> None:
        """Publish an event synchronously (bypasses queue).
        
        Use this when you need immediate processing, e.g., for UI updates.
        """
        event = Event(
            event_type=event_type,
            data=data or {},
            source=source
        )
        self._dispatch_event(event)

    def clear_subscribers(self, event_type: Optional[EventType] = None) -> None:
        """Clear subscribers for an event type or all events.
        
        Args:
            event_type: If provided, only clear subscribers for this type.
                       If None, clear all subscribers.
        """
        with self._lock:
            if event_type:
                self._subscribers.pop(event_type, None)
            else:
                self._subscribers.clear()

    def get_subscriber_count(self, event_type: EventType) -> int:
        """Get the number of subscribers for an event type."""
        with self._lock:
            return len(self._subscribers.get(event_type, []))

    def shutdown(self) -> None:
        """Shutdown the event bus and stop the worker thread."""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)
        logger.debug("EventBus shut down")


# Global event bus instance
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus instance.
    
    Returns:
        The global EventBus instance.
    """
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus(async_mode=True)
    return _global_bus
