"""Tests for app/dependencies.py - Dependency injection container."""

from unittest.mock import MagicMock

import pytest

from app.dependencies import AppDependencies, create_dependencies, create_mock_dependencies


class TestAppDependencies:
    """Tests for the AppDependencies dataclass."""

    def test_basic_creation(self):
        """Test creating AppDependencies with mock objects."""
        mock_network_stats = MagicMock()
        mock_connection_detector = MagicMock()
        mock_issue_detector = MagicMock()
        mock_network_scanner = MagicMock()
        mock_traffic_monitor = MagicMock()
        mock_bandwidth_monitor = MagicMock()
        mock_dns_monitor = MagicMock()
        mock_geolocation_service = MagicMock()
        mock_connection_tracker = MagicMock()
        mock_store = MagicMock()
        mock_settings = MagicMock()
        mock_launch_manager = MagicMock()

        deps = AppDependencies(
            network_stats=mock_network_stats,
            connection_detector=mock_connection_detector,
            issue_detector=mock_issue_detector,
            network_scanner=mock_network_scanner,
            traffic_monitor=mock_traffic_monitor,
            bandwidth_monitor=mock_bandwidth_monitor,
            dns_monitor=mock_dns_monitor,
            geolocation_service=mock_geolocation_service,
            connection_tracker=mock_connection_tracker,
            store=mock_store,
            settings=mock_settings,
            launch_manager=mock_launch_manager,
        )

        assert deps.network_stats is mock_network_stats
        assert deps.connection_detector is mock_connection_detector
        assert deps.store is mock_store

    def test_optional_event_bus(self):
        """Test that event_bus is optional."""
        deps = AppDependencies(
            network_stats=MagicMock(),
            connection_detector=MagicMock(),
            issue_detector=MagicMock(),
            network_scanner=MagicMock(),
            traffic_monitor=MagicMock(),
            bandwidth_monitor=MagicMock(),
            dns_monitor=MagicMock(),
            geolocation_service=MagicMock(),
            connection_tracker=MagicMock(),
            store=MagicMock(),
            settings=MagicMock(),
            launch_manager=MagicMock(),
        )
        assert deps.event_bus is None

    def test_with_event_bus(self):
        """Test creating AppDependencies with event bus."""
        mock_event_bus = MagicMock()

        deps = AppDependencies(
            network_stats=MagicMock(),
            connection_detector=MagicMock(),
            issue_detector=MagicMock(),
            network_scanner=MagicMock(),
            traffic_monitor=MagicMock(),
            bandwidth_monitor=MagicMock(),
            dns_monitor=MagicMock(),
            geolocation_service=MagicMock(),
            connection_tracker=MagicMock(),
            store=MagicMock(),
            settings=MagicMock(),
            launch_manager=MagicMock(),
            event_bus=mock_event_bus,
        )

        assert deps.event_bus is mock_event_bus


class TestCreateDependencies:
    """Tests for create_dependencies factory function."""

    def test_create_dependencies_with_temp_dir(self, tmp_path):
        """Test create_dependencies with custom data directory."""
        custom_dir = tmp_path / "test_data"
        custom_dir.mkdir()

        deps = create_dependencies(data_dir=custom_dir)

        assert deps is not None
        assert isinstance(deps, AppDependencies)
        assert deps.store is not None
        assert deps.settings is not None

        # Clean up
        deps.store.flush()

    def test_create_dependencies_custom_event_bus(self, tmp_path):
        """Test create_dependencies with custom event bus."""
        from app.events import EventBus

        custom_dir = tmp_path / "test_data2"
        custom_dir.mkdir()
        custom_bus = EventBus(async_mode=False)

        deps = create_dependencies(data_dir=custom_dir, event_bus=custom_bus)

        assert deps.event_bus is custom_bus

        # Clean up
        deps.store.flush()

    def test_create_dependencies_returns_wired_components(self, tmp_path):
        """Test that all components are properly wired."""
        custom_dir = tmp_path / "test_data3"
        custom_dir.mkdir()

        deps = create_dependencies(data_dir=custom_dir)

        # Verify all components exist
        assert deps.network_stats is not None
        assert deps.connection_detector is not None
        assert deps.issue_detector is not None
        assert deps.network_scanner is not None
        assert deps.traffic_monitor is not None
        assert deps.store is not None
        assert deps.settings is not None
        assert deps.launch_manager is not None

        # Clean up
        deps.store.flush()


class TestCreateMockDependencies:
    """Tests for create_mock_dependencies function."""

    def test_create_mock_dependencies(self):
        """Test creating mock dependencies."""
        deps = create_mock_dependencies()

        assert deps is not None
        assert isinstance(deps, AppDependencies)

    def test_mock_dependencies_have_mock_components(self):
        """Test that mock dependencies use mock implementations."""
        deps = create_mock_dependencies()

        # All components should be mock implementations
        assert deps.network_stats is not None
        assert deps.connection_detector is not None
        assert deps.issue_detector is not None
        assert deps.network_scanner is not None
        assert deps.traffic_monitor is not None
        assert deps.store is not None
        assert deps.settings is not None
        assert deps.launch_manager is not None

    def test_mock_dependencies_event_bus_sync(self):
        """Test that mock event bus is in sync mode."""
        deps = create_mock_dependencies()

        # Event bus should be in sync mode for deterministic testing
        assert deps.event_bus is not None
        # The event bus should be in sync mode (async_mode=False)
        assert deps.event_bus._async_mode is False

    def test_mock_network_stats_methods(self):
        """Test that mock network stats has expected methods."""
        deps = create_mock_dependencies()

        # Should have key methods available
        assert hasattr(deps.network_stats, "get_current_stats")
        assert hasattr(deps.network_stats, "initialize")
        assert hasattr(deps.network_stats, "get_session_totals")

    def test_mock_store_methods(self):
        """Test that mock store has expected methods."""
        deps = create_mock_dependencies()

        # Should have key methods available
        assert hasattr(deps.store, "update_stats")
        assert hasattr(deps.store, "get_today_totals")
        assert hasattr(deps.store, "flush")

    def test_mock_settings_methods(self):
        """Test that mock settings has expected methods."""
        deps = create_mock_dependencies()

        # Should have key methods available
        assert hasattr(deps.settings, "get_title_display")
        assert hasattr(deps.settings, "set_title_display")
        assert hasattr(deps.settings, "get_budget")


@pytest.mark.integration
class TestDependenciesIntegration:
    """Integration tests for dependencies (creates real objects)."""

    def test_create_real_dependencies(self, integration_data_dir):
        """Test creating real dependencies with temp directory."""
        # This will create real objects but with a temp data directory
        deps = create_dependencies(data_dir=integration_data_dir)

        assert deps is not None
        assert deps.store is not None
        assert deps.settings is not None

        # Clean up
        deps.store.flush()
