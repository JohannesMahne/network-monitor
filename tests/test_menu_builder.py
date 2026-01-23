"""Tests for app/views/menu_builder.py"""
from unittest.mock import MagicMock, patch

import pytest

from app.views.menu_builder import MenuBuilder, MenuCallbacks


class TestMenuCallbacks:
    """Tests for MenuCallbacks dataclass."""

    def test_default_callbacks_none(self):
        """Test that callbacks default to None."""
        callbacks = MenuCallbacks()
        assert callbacks.toggle_launch_login is None
        assert callbacks.set_title_display is None
        assert callbacks.rescan_network is None

    def test_callbacks_with_values(self):
        """Test setting callback values."""
        mock_callback = MagicMock()
        callbacks = MenuCallbacks(
            toggle_launch_login=mock_callback,
            rescan_network=mock_callback,
        )
        assert callbacks.toggle_launch_login is mock_callback
        assert callbacks.rescan_network is mock_callback


class TestMenuBuilder:
    """Tests for MenuBuilder class."""

    @pytest.fixture
    def builder(self):
        """Create a MenuBuilder instance."""
        return MenuBuilder()

    @pytest.fixture
    def mock_callbacks(self):
        """Create mock callbacks."""
        return MenuCallbacks(
            toggle_launch_login=MagicMock(),
            set_title_display=MagicMock(),
            rescan_network=MagicMock(),
            reset_session=MagicMock(),
            reset_today=MagicMock(),
            open_data_folder=MagicMock(),
            show_about=MagicMock(),
            quit_app=MagicMock(),
            rename_device=MagicMock(),
            set_quick_budget=MagicMock(),
            set_budget_period=MagicMock(),
            set_custom_budget=MagicMock(),
            show_all_budgets=MagicMock(),
        )

    def test_init(self, builder):
        """Test MenuBuilder initialization."""
        assert builder is not None
        assert isinstance(builder._menu_items, dict)

    @patch('app.views.menu_builder.rumps')
    def test_build_main_menu(self, mock_rumps, builder, mock_callbacks):
        """Test building the main menu."""
        mock_rumps.MenuItem = MagicMock(return_value=MagicMock())
        mock_rumps.separator = MagicMock()

        menu = builder.build_main_menu(mock_callbacks)

        assert menu is not None
        assert isinstance(menu, list)
        assert len(menu) > 0

    @patch('app.views.menu_builder.rumps')
    def test_build_main_menu_creates_items(self, mock_rumps, builder, mock_callbacks):
        """Test that menu items are created."""
        mock_rumps.MenuItem = MagicMock(return_value=MagicMock())
        mock_rumps.separator = MagicMock()

        builder.build_main_menu(mock_callbacks)

        # Should have created various menu items
        assert 'connection' in builder._menu_items
        assert 'speed' in builder._menu_items
        assert 'latency' in builder._menu_items
        assert 'today' in builder._menu_items

    @patch('app.views.menu_builder.rumps')
    def test_get_item(self, mock_rumps, builder, mock_callbacks):
        """Test getting menu items by key."""
        mock_rumps.MenuItem = MagicMock(return_value=MagicMock())
        mock_rumps.separator = MagicMock()

        builder.build_main_menu(mock_callbacks)

        item = builder.get_item('connection')
        assert item is not None

    @patch('app.views.menu_builder.rumps')
    def test_get_item_nonexistent(self, mock_rumps, builder):
        """Test getting nonexistent menu item."""
        item = builder.get_item('nonexistent_key')
        assert item is None


class TestMenuBuilderUpdates:
    """Tests for MenuBuilder update methods."""

    @pytest.fixture
    def builder_with_items(self):
        """Create MenuBuilder with menu items."""
        builder = MenuBuilder()
        # Manually add mock menu items
        builder._menu_items['connection'] = MagicMock()
        builder._menu_items['speed'] = MagicMock()
        builder._menu_items['latency'] = MagicMock()
        builder._menu_items['today'] = MagicMock()
        builder._menu_items['budget'] = MagicMock()
        builder._menu_items['week'] = MagicMock()
        builder._menu_items['month'] = MagicMock()
        builder._menu_items['graph_upload'] = MagicMock()
        return builder

    def test_update_connection_connected(self, builder_with_items):
        """Test updating connection when connected."""
        builder_with_items.update_connection("MyNetwork", "192.168.1.100", True)
        item = builder_with_items._menu_items['connection']
        assert "MyNetwork" in item.title
        assert "192.168.1.100" in item.title

    def test_update_connection_disconnected(self, builder_with_items):
        """Test updating connection when disconnected."""
        builder_with_items.update_connection("", "", False)
        item = builder_with_items._menu_items['connection']
        assert item.title == "Disconnected"

    def test_update_connection_long_name(self, builder_with_items):
        """Test updating connection with long name truncation."""
        long_name = "A" * 50
        builder_with_items.update_connection(long_name, "192.168.1.100", True)
        item = builder_with_items._menu_items['connection']
        # Should be truncated
        assert len(item.title) < len(long_name) + 20

    def test_update_speed(self, builder_with_items):
        """Test updating speed display."""
        builder_with_items.update_speed(1024.0, 2048.0)
        item = builder_with_items._menu_items['speed']
        assert "↑" in item.title
        assert "↓" in item.title

    def test_update_latency_with_value(self, builder_with_items):
        """Test updating latency with a value."""
        builder_with_items.update_latency(45.5)
        item = builder_with_items._menu_items['latency']
        # Check it contains latency info (rounded)
        assert "Latency:" in item.title
        assert "ms" in item.title

    def test_update_latency_with_average(self, builder_with_items):
        """Test updating latency with average."""
        builder_with_items.update_latency(45.5, 50.0)
        item = builder_with_items._menu_items['latency']
        assert "Latency:" in item.title
        assert "avg" in item.title

    def test_update_latency_none(self, builder_with_items):
        """Test updating latency when None."""
        builder_with_items.update_latency(None)
        item = builder_with_items._menu_items['latency']
        assert "--" in item.title

    def test_update_today(self, builder_with_items):
        """Test updating today's stats."""
        builder_with_items.update_today(1000000, 5000000)
        item = builder_with_items._menu_items['today']
        assert "Today" in item.title

    def test_update_budget(self, builder_with_items):
        """Test updating budget display."""
        builder_with_items.update_budget("50% of 10 GB")
        item = builder_with_items._menu_items['budget']
        assert "50%" in item.title

    def test_update_week(self, builder_with_items):
        """Test updating weekly stats."""
        builder_with_items.update_week(5000000, 10000000)
        item = builder_with_items._menu_items['week']
        assert "Week" in item.title

    def test_update_month(self, builder_with_items):
        """Test updating monthly stats."""
        builder_with_items.update_month(50000000, 100000000)
        item = builder_with_items._menu_items['month']
        assert "Month" in item.title

    def test_update_sparkline_title(self, builder_with_items):
        """Test updating sparkline title."""
        builder_with_items.update_sparkline_title('graph_upload', "↑ ▁▂▃▄▅▆▇█")
        item = builder_with_items._menu_items['graph_upload']
        assert "▁" in item.title or "↑" in item.title


class TestMenuBuilderUtilities:
    """Tests for MenuBuilder utility methods."""

    def test_safe_menu_clear_with_menu(self):
        """Test safe menu clearing with valid menu."""
        mock_item = MagicMock()
        mock_item._menu = MagicMock()
        mock_item.clear = MagicMock()

        MenuBuilder.safe_menu_clear(mock_item)
        mock_item.clear.assert_called_once()

    def test_safe_menu_clear_no_menu(self):
        """Test safe menu clearing with no menu."""
        mock_item = MagicMock()
        mock_item._menu = None

        # Should not raise
        MenuBuilder.safe_menu_clear(mock_item)

    def test_safe_menu_clear_none(self):
        """Test safe menu clearing with None."""
        # Should not raise
        MenuBuilder.safe_menu_clear(None)

    def test_create_progress_bar_empty(self):
        """Test creating empty progress bar."""
        bar = MenuBuilder.create_progress_bar(0)
        assert "░" in bar
        assert "[" in bar
        assert "]" in bar

    def test_create_progress_bar_full(self):
        """Test creating full progress bar."""
        bar = MenuBuilder.create_progress_bar(100)
        assert "█" in bar
        assert "░" not in bar

    def test_create_progress_bar_half(self):
        """Test creating half-full progress bar."""
        bar = MenuBuilder.create_progress_bar(50)
        assert "█" in bar
        assert "░" in bar

    def test_create_progress_bar_custom_width(self):
        """Test creating progress bar with custom width."""
        bar = MenuBuilder.create_progress_bar(50, width=20)
        # Width 20 + brackets = 22
        assert len(bar) == 22


class TestMenuBuilderImages:
    """Tests for MenuBuilder image handling."""

    @pytest.fixture
    def builder_with_items(self):
        """Create MenuBuilder with menu items."""
        builder = MenuBuilder()
        mock_item = MagicMock()
        mock_item._menuitem = MagicMock()
        builder._menu_items['test_item'] = mock_item
        return builder

    def test_set_menu_image_nonexistent_item(self):
        """Test setting image on nonexistent menu item."""
        builder = MenuBuilder()
        # Should not raise
        builder.set_menu_image('nonexistent', '/path/to/image.png')

    def test_set_menu_image_with_item(self, builder_with_items):
        """Test setting image on existing menu item."""
        # Should not raise even if image doesn't exist
        builder_with_items.set_menu_image('test_item', '/nonexistent/path.png')
