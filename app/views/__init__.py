"""View components for Network Monitor UI.

Contains:
- icons: Icon and sparkline generation
- menu_builder: Menu construction helpers
- dialogs: Alert and input dialogs
"""
from app.views.icons import IconGenerator, create_gauge_icon, create_sparkline, create_status_icon
from app.views.menu_builder import MenuBuilder

__all__ = [
    "IconGenerator",
    "MenuBuilder",
    "create_gauge_icon",
    "create_sparkline",
    "create_status_icon",
]
