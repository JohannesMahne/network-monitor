"""Application module for Network Monitor.

Contains the main application components:
- EventBus: Internal event communication
- AppController: Business logic orchestration with DI
- Views: UI components (icons, menus, dialogs)
"""
from app.events import EventBus, EventType, Event
from app.dependencies import AppDependencies, create_dependencies
from app.controller import AppController

__all__ = [
    "EventBus",
    "EventType", 
    "Event",
    "AppDependencies",
    "create_dependencies",
    "AppController",
]
