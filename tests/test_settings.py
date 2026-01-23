"""Tests for settings management."""

import pytest

from storage.settings import (
    AppSettings,
    BudgetPeriod,
    ConnectionBudget,
    SettingsManager,
    TitleDisplayMode,
)


class TestAppSettings:
    """Tests for AppSettings dataclass."""

    def test_default_values(self):
        """Test default settings values."""
        settings = AppSettings()
        assert settings.title_display == "latency"
        assert settings.budgets == {}
        assert settings.latency_good == 50
        assert settings.latency_ok == 100

    def test_to_dict(self):
        """Test converting settings to dict."""
        settings = AppSettings(title_display="speed")
        data = settings.to_dict()
        assert data["title_display"] == "speed"
        assert "budgets" in data

    def test_from_dict(self):
        """Test creating settings from dict."""
        data = {
            "title_display": "devices",
            "latency_good": 30,
            "latency_ok": 80,
        }
        settings = AppSettings.from_dict(data)
        assert settings.title_display == "devices"
        assert settings.latency_good == 30


class TestConnectionBudget:
    """Tests for ConnectionBudget dataclass."""

    def test_default_values(self):
        """Test default budget values."""
        budget = ConnectionBudget()
        assert budget.enabled is False
        assert budget.limit_bytes == 0
        assert budget.period == "monthly"
        assert budget.warn_at_percent == 80

    def test_to_dict(self):
        """Test converting budget to dict."""
        budget = ConnectionBudget(enabled=True, limit_bytes=1000000000)
        data = budget.to_dict()
        assert data["enabled"] is True
        assert data["limit_bytes"] == 1000000000

    def test_from_dict(self):
        """Test creating budget from dict."""
        data = {
            "enabled": True,
            "limit_bytes": 5000000000,
            "period": "weekly",
            "warn_at_percent": 90
        }
        budget = ConnectionBudget.from_dict(data)
        assert budget.enabled is True
        assert budget.limit_bytes == 5000000000
        assert budget.period == "weekly"


class TestSettingsManager:
    """Tests for SettingsManager class."""

    @pytest.fixture
    def settings_manager(self, temp_data_dir):
        """Create a SettingsManager with temporary directory."""
        return SettingsManager(data_dir=temp_data_dir)

    def test_init_creates_default_settings(self, settings_manager):
        """Test that initialization creates default settings."""
        assert settings_manager.get_title_display() == "latency"

    def test_set_and_get_title_display(self, settings_manager):
        """Test setting and getting title display mode."""
        settings_manager.set_title_display("speed")
        assert settings_manager.get_title_display() == "speed"

    def test_get_title_display_options(self, settings_manager):
        """Test getting available title display options."""
        options = settings_manager.get_title_display_options()
        assert len(options) >= 4
        # Options should be (key, label) tuples
        keys = [opt[0] for opt in options]
        assert "latency" in keys
        assert "speed" in keys

    def test_get_latency_color_green(self, settings_manager):
        """Test latency color for good values."""
        color = settings_manager.get_latency_color(25.0)
        assert color == "green"

    def test_get_latency_color_yellow(self, settings_manager):
        """Test latency color for OK values."""
        color = settings_manager.get_latency_color(75.0)
        assert color == "yellow"

    def test_get_latency_color_red(self, settings_manager):
        """Test latency color for poor values."""
        color = settings_manager.get_latency_color(150.0)
        assert color == "red"

    def test_set_and_get_budget(self, settings_manager):
        """Test setting and getting connection budget."""
        budget = ConnectionBudget(
            enabled=True,
            limit_bytes=10000000000,  # 10 GB
            period="monthly",
            warn_at_percent=80
        )
        settings_manager.set_budget("WiFi:TestNetwork", budget)

        retrieved = settings_manager.get_budget("WiFi:TestNetwork")
        assert retrieved is not None
        assert retrieved.enabled is True
        assert retrieved.limit_bytes == 10000000000

    def test_get_nonexistent_budget(self, settings_manager):
        """Test getting budget for connection without one."""
        budget = settings_manager.get_budget("NonExistent:Network")
        assert budget is None

    def test_remove_budget(self, settings_manager):
        """Test removing a budget."""
        budget = ConnectionBudget(enabled=True, limit_bytes=1000000)
        settings_manager.set_budget("WiFi:TestNetwork", budget)
        settings_manager.remove_budget("WiFi:TestNetwork")

        assert settings_manager.get_budget("WiFi:TestNetwork") is None

    def test_get_all_budgets(self, settings_manager):
        """Test getting all budgets."""
        budget1 = ConnectionBudget(enabled=True, limit_bytes=1000000)
        budget2 = ConnectionBudget(enabled=True, limit_bytes=2000000)

        settings_manager.set_budget("WiFi:Network1", budget1)
        settings_manager.set_budget("WiFi:Network2", budget2)

        all_budgets = settings_manager.get_all_budgets()
        assert len(all_budgets) == 2

    def test_check_budget_status_no_budget(self, settings_manager):
        """Test budget status when no budget is set."""
        status = settings_manager.check_budget_status("WiFi:TestNetwork", 0, 0)
        assert status["has_budget"] is False
        assert status["exceeded"] is False

    def test_check_budget_status_under_limit(self, settings_manager):
        """Test budget status when under limit."""
        budget = ConnectionBudget(enabled=True, limit_bytes=1000000000)
        settings_manager.set_budget("WiFi:TestNetwork", budget)

        status = settings_manager.check_budget_status(
            "WiFi:TestNetwork",
            current_usage=100000000,
            period_usage=500000000  # 50% of limit
        )

        assert status["has_budget"] is True
        assert status["exceeded"] is False
        assert status["warning"] is False
        assert status["percent_used"] == 50.0

    def test_check_budget_status_warning(self, settings_manager):
        """Test budget status when at warning threshold."""
        budget = ConnectionBudget(enabled=True, limit_bytes=1000000000, warn_at_percent=80)
        settings_manager.set_budget("WiFi:TestNetwork", budget)

        status = settings_manager.check_budget_status(
            "WiFi:TestNetwork",
            current_usage=0,
            period_usage=850000000  # 85% of limit
        )

        assert status["warning"] is True
        assert status["exceeded"] is False

    def test_check_budget_status_exceeded(self, settings_manager):
        """Test budget status when exceeded."""
        budget = ConnectionBudget(enabled=True, limit_bytes=1000000000)
        settings_manager.set_budget("WiFi:TestNetwork", budget)

        status = settings_manager.check_budget_status(
            "WiFi:TestNetwork",
            current_usage=0,
            period_usage=1500000000  # 150% of limit
        )

        assert status["exceeded"] is True
        assert status["percent_used"] == 100  # Capped at 100

    def test_settings_persistence(self, temp_data_dir):
        """Test that settings persist across instances."""
        manager1 = SettingsManager(data_dir=temp_data_dir)
        manager1.set_title_display("devices")

        manager2 = SettingsManager(data_dir=temp_data_dir)
        assert manager2.get_title_display() == "devices"

    def test_budget_persistence(self, temp_data_dir):
        """Test that budgets persist across instances."""
        manager1 = SettingsManager(data_dir=temp_data_dir)
        budget = ConnectionBudget(enabled=True, limit_bytes=5000000000)
        manager1.set_budget("WiFi:TestNetwork", budget)

        manager2 = SettingsManager(data_dir=temp_data_dir)
        retrieved = manager2.get_budget("WiFi:TestNetwork")
        assert retrieved is not None
        assert retrieved.limit_bytes == 5000000000


class TestBudgetPeriod:
    """Tests for BudgetPeriod enum."""

    def test_values(self):
        """Test enum values."""
        assert BudgetPeriod.DAILY.value == "daily"
        assert BudgetPeriod.WEEKLY.value == "weekly"
        assert BudgetPeriod.MONTHLY.value == "monthly"


class TestTitleDisplayMode:
    """Tests for TitleDisplayMode enum."""

    def test_values(self):
        """Test enum values."""
        assert TitleDisplayMode.LATENCY.value == "latency"
        assert TitleDisplayMode.SESSION_DATA.value == "session"
        assert TitleDisplayMode.SPEED.value == "speed"
        assert TitleDisplayMode.DEVICES.value == "devices"
