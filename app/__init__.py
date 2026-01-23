"""Application module for Network Monitor.

Contains the main application components:
- EventBus: Internal event communication
- AppController: Business logic orchestration with DI
- MenuAwareTimer: Timer that works during menu tracking
- Views: UI components (icons, menus, dialogs)
"""

from app.controller import AppController
from app.dependencies import AppDependencies, create_dependencies
from app.events import Event, EventBus, EventType
from app.timer import MenuAwareTimer

__all__ = [
    "AppController",
    "AppDependencies",
    "Event",
    "EventBus",
    "EventType",
    "MenuAwareTimer",
    "create_dependencies",
]
