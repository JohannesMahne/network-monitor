"""Tests for the app module (events, dependencies, controller)."""
import time

import pytest

from app.controller import AppController
from app.dependencies import AppDependencies
from app.events import Event, EventBus, EventType
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


class TestEventBus:
    """Tests for EventBus."""

    def test_subscribe_and_publish(self):
        """Events should be delivered to subscribers."""
        bus = EventBus(async_mode=False)
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.STATS_UPDATED, handler)
        bus.publish(EventType.STATS_UPDATED, {"speed": 1000})

        assert len(received) == 1
        assert received[0].data["speed"] == 1000

    def test_multiple_subscribers(self):
        """Multiple subscribers should all receive events."""
        bus = EventBus(async_mode=False)
        count = [0]

        def handler1(event):
            count[0] += 1

        def handler2(event):
            count[0] += 10

        bus.subscribe(EventType.CONNECTION_CHANGED, handler1)
        bus.subscribe(EventType.CONNECTION_CHANGED, handler2)
        bus.publish(EventType.CONNECTION_CHANGED)

        assert count[0] == 11

    def test_unsubscribe(self):
        """Unsubscribed handlers should not receive events."""
        bus = EventBus(async_mode=False)
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.DEVICE_DISCOVERED, handler)
        bus.publish(EventType.DEVICE_DISCOVERED)
        assert len(received) == 1

        bus.unsubscribe(EventType.DEVICE_DISCOVERED, handler)
        bus.publish(EventType.DEVICE_DISCOVERED)
        assert len(received) == 1  # No new events

    def test_different_event_types(self):
        """Handlers should only receive their subscribed event type."""
        bus = EventBus(async_mode=False)
        received = []

        def handler(event):
            received.append(event.event_type)

        bus.subscribe(EventType.STATS_UPDATED, handler)

        bus.publish(EventType.STATS_UPDATED)
        bus.publish(EventType.CONNECTION_CHANGED)  # Should not trigger
        bus.publish(EventType.STATS_UPDATED)

        assert len(received) == 2
        assert all(e == EventType.STATS_UPDATED for e in received)

    def test_async_mode(self):
        """Async mode should process events in background."""
        bus = EventBus(async_mode=True)
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.LATENCY_UPDATE, handler)
        bus.publish(EventType.LATENCY_UPDATE, {"latency": 25})

        # Give the worker thread time to process
        time.sleep(0.2)

        assert len(received) == 1
        bus.shutdown()

    def test_publish_sync(self):
        """publish_sync should process immediately even in async mode."""
        bus = EventBus(async_mode=True)
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe(EventType.MENU_REFRESH_NEEDED, handler)
        bus.publish_sync(EventType.MENU_REFRESH_NEEDED)

        # Should be processed immediately
        assert len(received) == 1
        bus.shutdown()

    def test_clear_subscribers(self):
        """clear_subscribers should remove all handlers."""
        bus = EventBus(async_mode=False)

        bus.subscribe(EventType.STATS_UPDATED, lambda e: None)
        bus.subscribe(EventType.STATS_UPDATED, lambda e: None)

        assert bus.get_subscriber_count(EventType.STATS_UPDATED) == 2

        bus.clear_subscribers(EventType.STATS_UPDATED)

        assert bus.get_subscriber_count(EventType.STATS_UPDATED) == 0

    def test_handler_error_does_not_stop_others(self):
        """An error in one handler should not prevent others from running."""
        bus = EventBus(async_mode=False)
        count = [0]

        def bad_handler(event):
            raise ValueError("Test error")

        def good_handler(event):
            count[0] += 1

        bus.subscribe(EventType.ISSUE_DETECTED, bad_handler)
        bus.subscribe(EventType.ISSUE_DETECTED, good_handler)

        # Should not raise, and good_handler should still run
        bus.publish(EventType.ISSUE_DETECTED)

        assert count[0] == 1


class TestEvent:
    """Tests for Event dataclass."""

    def test_event_creation(self):
        """Events should be created with correct attributes."""
        event = Event(
            event_type=EventType.SPEED_UPDATE,
            data={"upload": 1000},
            source="test"
        )

        assert event.event_type == EventType.SPEED_UPDATE
        assert event.data["upload"] == 1000
        assert event.source == "test"
        assert event.timestamp is not None

    def test_event_str(self):
        """Event string representation should be readable."""
        event = Event(EventType.CONNECTION_LOST, {"reason": "timeout"})
        s = str(event)

        assert "CONNECTION_LOST" in s
        assert "reason" in s


class TestAppDependencies:
    """Tests for AppDependencies container."""

    def test_create_mock_dependencies(self):
        """Mock dependencies should be creatable."""
        deps = AppDependencies(
            network_stats=MockNetworkStats(),
            connection_detector=MockConnectionDetector(),
            issue_detector=MockIssueDetector(),
            network_scanner=MockNetworkScanner(),
            traffic_monitor=MockTrafficMonitor(),
            store=MockJsonStore(),
            settings=MockSettingsManager(),
            launch_manager=MockLaunchAgentManager(),
        )

        assert deps.network_stats is not None
        assert deps.store is not None

    def test_dependencies_accessible(self):
        """All dependencies should be accessible."""
        deps = AppDependencies(
            network_stats=MockNetworkStats(),
            connection_detector=MockConnectionDetector(),
            issue_detector=MockIssueDetector(),
            network_scanner=MockNetworkScanner(),
            traffic_monitor=MockTrafficMonitor(),
            store=MockJsonStore(),
            settings=MockSettingsManager(),
            launch_manager=MockLaunchAgentManager(),
        )

        # Should be able to call methods
        deps.network_stats.initialize()
        deps.connection_detector.get_current_connection()
        deps.store.get_today_totals()


class TestAppController:
    """Tests for AppController."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies for testing."""
        return AppDependencies(
            network_stats=MockNetworkStats(),
            connection_detector=MockConnectionDetector(),
            issue_detector=MockIssueDetector(),
            network_scanner=MockNetworkScanner(),
            traffic_monitor=MockTrafficMonitor(),
            store=MockJsonStore(),
            settings=MockSettingsManager(),
            launch_manager=MockLaunchAgentManager(),
            event_bus=EventBus(async_mode=False),
        )

    def test_controller_initialization(self, mock_deps):
        """Controller should initialize correctly."""
        controller = AppController(mock_deps)

        assert controller.deps is mock_deps
        assert controller.event_bus is not None

    def test_controller_start(self, mock_deps):
        """Controller start should initialize components."""
        controller = AppController(mock_deps)

        events = []
        mock_deps.event_bus.subscribe(EventType.APP_STARTING, lambda e: events.append(e))

        controller.start()

        assert controller._running
        assert len(events) == 1

    def test_controller_stop(self, mock_deps):
        """Controller stop should clean up."""
        controller = AppController(mock_deps)
        controller.start()

        events = []
        mock_deps.event_bus.subscribe(EventType.APP_STOPPING, lambda e: events.append(e))

        controller.stop()

        assert not controller._running
        assert len(events) == 1

    def test_controller_update_returns_state(self, mock_deps):
        """Update should return current state dictionary."""
        controller = AppController(mock_deps)
        controller.start()

        # Set some mock data
        mock_deps.network_stats.set_speeds(upload=1000, download=5000)
        mock_deps.issue_detector.set_latency(25.0)

        state = controller.update()

        assert 'connection' in state
        assert 'stats' in state
        assert 'today_totals' in state

    def test_connection_change_publishes_event(self, mock_deps):
        """Connection change should publish event."""
        controller = AppController(mock_deps)
        controller.start()

        events = []
        mock_deps.event_bus.subscribe(EventType.CONNECTION_CHANGED, lambda e: events.append(e))

        # Initial update sets connection
        controller.update()

        # Change connection
        mock_deps.connection_detector.set_connection(name="NewNetwork")
        controller.update()

        assert len(events) == 1
        assert events[0].data['new'] == "WiFi:NewNetwork"

    def test_reset_session(self, mock_deps):
        """Reset session should clear state."""
        controller = AppController(mock_deps)
        controller.start()

        # Add some data
        mock_deps.network_stats.add_traffic(sent=1000, recv=5000)
        controller.update()

        controller.reset_session()

        assert len(controller._upload_history) == 0
        assert len(controller._latency_samples) == 0

    def test_get_devices(self, mock_deps):
        """get_devices should return scanner devices."""
        controller = AppController(mock_deps)

        mock_deps.network_scanner.add_device("192.168.1.1", "00:11:22:33:44:55")
        mock_deps.network_scanner.add_device("192.168.1.2", "AA:BB:CC:DD:EE:FF")

        devices = controller.get_devices()

        assert len(devices) == 2

    def test_get_latency_color(self, mock_deps):
        """get_latency_color should return correct color."""
        controller = AppController(mock_deps)
        controller._current_latency = 25.0

        assert controller.get_latency_color() == "green"

        controller._current_latency = 75.0
        assert controller.get_latency_color() == "yellow"

        controller._current_latency = 150.0
        assert controller.get_latency_color() == "red"

    def test_toggle_launch_at_login(self, mock_deps):
        """toggle_launch_at_login should work."""
        controller = AppController(mock_deps)

        success, message = controller.toggle_launch_at_login()

        assert success
        assert "enabled" in message.lower()

        success, message = controller.toggle_launch_at_login()

        assert success
        assert "disabled" in message.lower()


class TestMocks:
    """Tests for mock implementations."""

    def test_mock_network_stats(self):
        """MockNetworkStats should work correctly."""
        stats = MockNetworkStats()
        stats.initialize()

        stats.set_speeds(upload=1000, download=5000)
        current = stats.get_current_stats()

        assert current.upload_speed == 1000
        assert current.download_speed == 5000

        peak = stats.get_peak_speeds()
        assert peak == (1000, 5000)

    def test_mock_connection_detector(self):
        """MockConnectionDetector should work correctly."""
        detector = MockConnectionDetector()

        conn = detector.get_current_connection()
        assert conn.is_connected
        assert conn.connection_type == "WiFi"

        detector.set_connection(name="TestWiFi", is_connected=False)
        conn = detector.get_current_connection()

        assert not conn.is_connected
        assert conn.name == "TestWiFi"

    def test_mock_scanner(self):
        """MockNetworkScanner should work correctly."""
        scanner = MockNetworkScanner()

        scanner.add_device("192.168.1.1", "00:11:22:33:44:55", vendor="Apple")
        scanner.add_device("192.168.1.2", "AA:BB:CC:DD:EE:FF", is_online=False)

        online, total = scanner.get_device_count()

        assert online == 1
        assert total == 2

    def test_mock_store(self):
        """MockJsonStore should work correctly."""
        store = MockJsonStore()

        store.update_stats("WiFi:Test", sent=1000, recv=5000)

        sent, recv = store.get_today_totals()

        assert sent == 1000
        assert recv == 5000
