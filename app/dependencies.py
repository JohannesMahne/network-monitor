"""Dependency injection container for Network Monitor.

Provides a centralized way to create and manage application dependencies,
making components easier to test and swap out.

Usage:
    from app.dependencies import create_dependencies

    # Create all dependencies
    deps = create_dependencies()

    # Access individual components
    deps.network_stats.get_current_stats()
    deps.store.get_today_totals()
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import STORAGE, get_logger

logger = get_logger(__name__)


@dataclass
class AppDependencies:
    """Container for all application dependencies.

    Using a dataclass makes dependencies explicit and easy to mock in tests.
    Each field represents a component that can be injected.
    """

    # Core monitoring components
    network_stats: "NetworkStats"
    connection_detector: "ConnectionDetector"
    issue_detector: "IssueDetector"
    network_scanner: "NetworkScanner"
    traffic_monitor: "TrafficMonitor"
    bandwidth_monitor: "BandwidthMonitor"
    dns_monitor: "DNSMonitor"
    geolocation_service: "GeolocationService"
    connection_tracker: "ConnectionTracker"

    # Storage components
    store: "SQLiteStore"
    settings: "SettingsManager"

    # Service components
    launch_manager: "LaunchAgentManager"

    # Event bus (optional, can be shared)
    event_bus: Optional["EventBus"] = None

    def __post_init__(self):
        """Log dependency creation."""
        logger.debug("AppDependencies container created")


def create_dependencies(
    data_dir: Optional[Path] = None, event_bus: Optional["EventBus"] = None
) -> AppDependencies:
    """Create all application dependencies.

    Factory function that instantiates all required components
    and wires them together.

    Args:
        data_dir: Override the default data directory.
        event_bus: Provide an existing event bus, or one will be created.

    Returns:
        AppDependencies container with all components.

    Example:
        >>> deps = create_dependencies()
        >>> deps.network_stats.initialize()
    """
    # Import here to avoid circular imports
    from app.events import get_event_bus
    from monitor.connection import ConnectionDetector
    from monitor.issues import IssueDetector
    from monitor.network import NetworkStats
    from monitor.scanner import NetworkScanner
    from monitor.traffic import TrafficMonitor
    from service.launch_agent import get_launch_agent_manager
    from storage.settings import get_settings_manager
    from storage.sqlite_store import SQLiteStore

    logger.info("Creating application dependencies...")

    # Resolve data directory
    if data_dir is None:
        data_dir = Path.home() / STORAGE.DATA_DIR_NAME

    # Create storage first (other components may depend on it)
    store = SQLiteStore(data_dir=data_dir)
    settings = get_settings_manager(data_dir)

    # Create monitoring components
    network_stats = NetworkStats()
    connection_detector = ConnectionDetector(
        event_bus=event_bus
    )  # Pass event bus for VPN notifications
    issue_detector = IssueDetector(event_bus=event_bus)  # Pass event bus for quality notifications
    network_scanner = NetworkScanner(event_bus=event_bus)  # Pass event bus for device notifications
    traffic_monitor = TrafficMonitor()
    from monitor.bandwidth_monitor import BandwidthMonitor
    from monitor.connection_tracker import ConnectionTracker
    from monitor.dns_monitor import DNSMonitor
    from monitor.geolocation import GeolocationService

    bandwidth_monitor = BandwidthMonitor()
    dns_monitor = DNSMonitor()
    geolocation_service = GeolocationService(data_dir=data_dir)
    connection_tracker = ConnectionTracker(geolocation_service=geolocation_service)

    # Create service components
    launch_manager = get_launch_agent_manager()

    # Use provided event bus or get global one
    if event_bus is None:
        event_bus = get_event_bus()

    deps = AppDependencies(
        network_stats=network_stats,
        connection_detector=connection_detector,
        issue_detector=issue_detector,
        network_scanner=network_scanner,
        traffic_monitor=traffic_monitor,
        bandwidth_monitor=bandwidth_monitor,
        dns_monitor=dns_monitor,
        geolocation_service=geolocation_service,
        connection_tracker=connection_tracker,
        store=store,
        settings=settings,
        launch_manager=launch_manager,
        event_bus=event_bus,
    )

    logger.info("All dependencies created successfully")
    return deps


def create_mock_dependencies() -> AppDependencies:
    """Create mock dependencies for testing.

    Returns an AppDependencies container with mock objects
    that don't require system access.

    Returns:
        AppDependencies with mock implementations.
    """
    from app.events import EventBus
    from tests.mocks import (
        MockConnectionDetector,
        MockIssueDetector,
        MockJsonStore,
        MockLaunchAgentManager,
        MockNetworkScanner,
        MockNetworkStats,
        MockSettingsManager,
        MockTrafficMonitor,
    )

    logger.debug("Creating mock dependencies for testing")

    from monitor.bandwidth_monitor import BandwidthMonitor
    from monitor.connection_tracker import ConnectionTracker
    from monitor.dns_monitor import DNSMonitor
    from monitor.geolocation import GeolocationService

    return AppDependencies(
        network_stats=MockNetworkStats(),
        connection_detector=MockConnectionDetector(),
        issue_detector=MockIssueDetector(),
        network_scanner=MockNetworkScanner(),
        traffic_monitor=MockTrafficMonitor(),
        bandwidth_monitor=BandwidthMonitor(),  # Real implementation is lightweight
        dns_monitor=DNSMonitor(),  # Real implementation is lightweight
        geolocation_service=GeolocationService(),  # Real implementation
        connection_tracker=ConnectionTracker(),  # Real implementation
        store=MockJsonStore(),
        settings=MockSettingsManager(),
        launch_manager=MockLaunchAgentManager(),
        event_bus=EventBus(async_mode=False),  # Sync mode for testing
    )
