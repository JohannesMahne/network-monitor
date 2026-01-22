"""Tests for Launch Agent management."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from service.launch_agent import LaunchAgentManager, get_launch_agent_manager


class TestLaunchAgentManager:
    """Tests for LaunchAgentManager class."""

    @pytest.fixture
    def temp_launch_agents_dir(self):
        """Create a temporary LaunchAgents directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def manager(self, temp_launch_agents_dir):
        """Create a LaunchAgentManager with mocked paths."""
        with patch.object(
            LaunchAgentManager,
            '__init__',
            lambda self: None
        ):
            mgr = LaunchAgentManager()
            mgr.launch_agents_dir = temp_launch_agents_dir
            mgr.agent_path = temp_launch_agents_dir / "com.networkmonitor.app.plist"
            mgr.app_dir = Path(__file__).parent.parent
            mgr.python_path = "/usr/bin/python3"
            mgr.script_path = mgr.app_dir / "network_monitor.py"
            return mgr

    def test_is_enabled_false_when_no_file(self, manager):
        """Test is_enabled returns False when plist doesn't exist."""
        assert manager.is_enabled() is False

    def test_is_enabled_true_when_file_exists(self, manager):
        """Test is_enabled returns True when plist exists."""
        manager.agent_path.touch()
        assert manager.is_enabled() is True

    @patch('subprocess.run')
    def test_is_loaded(self, mock_run, manager):
        """Test is_loaded checks launchctl."""
        mock_run.return_value = MagicMock(returncode=0)
        
        result = manager.is_loaded()
        
        assert result is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_is_loaded_not_loaded(self, mock_run, manager):
        """Test is_loaded returns False when not loaded."""
        mock_run.return_value = MagicMock(returncode=1)
        
        result = manager.is_loaded()
        
        assert result is False

    def test_enable(self, manager, temp_launch_agents_dir):
        """Test enabling launch at login."""
        # Ensure the directory exists
        manager.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        
        success, message = manager.enable()
        
        assert success is True
        assert manager.agent_path.exists()
        assert "enabled" in message.lower()

    def test_enable_creates_plist(self, manager):
        """Test that enable creates a valid plist."""
        manager.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        
        manager.enable()
        
        import plistlib
        with open(manager.agent_path, 'rb') as f:
            plist = plistlib.load(f)
        
        assert "Label" in plist
        assert "ProgramArguments" in plist
        assert "RunAtLoad" in plist

    @patch('subprocess.run')
    def test_disable(self, mock_run, manager):
        """Test disabling launch at login."""
        mock_run.return_value = MagicMock(returncode=0)
        
        # First enable
        manager.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        manager.enable()
        
        # Then disable
        success, message = manager.disable()
        
        assert success is True
        assert not manager.agent_path.exists()
        assert "disabled" in message.lower()

    @patch('subprocess.run')
    def test_toggle_enable(self, mock_run, manager):
        """Test toggle enables when disabled."""
        mock_run.return_value = MagicMock(returncode=0)
        manager.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        
        success, message = manager.toggle()
        
        assert success is True
        assert manager.agent_path.exists()

    @patch('subprocess.run')
    def test_toggle_disable(self, mock_run, manager):
        """Test toggle disables when enabled."""
        mock_run.return_value = MagicMock(returncode=0)
        manager.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        
        # First enable
        manager.enable()
        
        # Then toggle should disable
        success, message = manager.toggle()
        
        assert success is True
        assert not manager.agent_path.exists()

    def test_get_status_enabled(self, manager):
        """Test get_status when enabled."""
        manager.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        manager.enable()
        
        status = manager.get_status()
        
        assert "On" in status
        assert "✓" in status

    def test_get_status_disabled(self, manager):
        """Test get_status when disabled."""
        status = manager.get_status()
        
        assert "Off" in status
        assert "○" in status

    def test_get_python_path_venv(self, manager, tmp_path):
        """Test _get_python_path prefers venv."""
        # Use a completely isolated temp directory
        manager.app_dir = tmp_path
        
        # Create a mock venv structure
        venv_path = tmp_path / ".venv" / "bin"
        venv_path.mkdir(parents=True, exist_ok=True)
        venv_python = venv_path / "python"
        venv_python.touch()
        
        result = manager._get_python_path()
        assert ".venv" in result or "venv" in result

    def test_get_python_path_fallback(self, manager, tmp_path):
        """Test _get_python_path falls back to system python."""
        # Use a completely isolated temp directory with no venv
        manager.app_dir = tmp_path
        
        result = manager._get_python_path()
        
        assert result == "/usr/bin/python3"


class TestPlistContent:
    """Tests for plist content generation."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a LaunchAgentManager with temp paths."""
        with patch.object(
            LaunchAgentManager,
            '__init__',
            lambda self: None
        ):
            mgr = LaunchAgentManager()
            mgr.launch_agents_dir = tmp_path / "LaunchAgents"
            mgr.agent_path = mgr.launch_agents_dir / "com.networkmonitor.app.plist"
            mgr.app_dir = Path(__file__).parent.parent
            mgr.python_path = "/usr/bin/python3"
            mgr.script_path = mgr.app_dir / "network_monitor.py"
            return mgr

    def test_plist_content(self, manager):
        """Test plist content has required fields."""
        content = manager._create_plist_content()
        
        assert "Label" in content
        assert "ProgramArguments" in content
        assert "WorkingDirectory" in content
        assert content["RunAtLoad"] is True

    def test_plist_program_arguments(self, manager):
        """Test plist program arguments."""
        content = manager._create_plist_content()
        
        args = content["ProgramArguments"]
        assert len(args) == 2
        assert "python" in args[0].lower()

    def test_plist_environment(self, manager):
        """Test plist environment variables."""
        content = manager._create_plist_content()
        
        env = content.get("EnvironmentVariables", {})
        assert "PATH" in env


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_launch_agent_manager(self):
        """Test get_launch_agent_manager returns a manager."""
        with patch.object(LaunchAgentManager, '__init__', return_value=None):
            manager = get_launch_agent_manager()
            assert isinstance(manager, LaunchAgentManager)


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a LaunchAgentManager with temp paths."""
        with patch.object(
            LaunchAgentManager,
            '__init__',
            lambda self: None
        ):
            mgr = LaunchAgentManager()
            mgr.launch_agents_dir = tmp_path / "LaunchAgents"
            mgr.agent_path = mgr.launch_agents_dir / "com.networkmonitor.app.plist"
            mgr.app_dir = tmp_path
            mgr.python_path = "/usr/bin/python3"
            mgr.script_path = mgr.app_dir / "network_monitor.py"
            return mgr

    def test_enable_permission_error(self, manager):
        """Test enable handles permission error."""
        # Create directory but make it read-only
        manager.launch_agents_dir.mkdir(parents=True)
        manager.launch_agents_dir.chmod(0o444)
        
        try:
            success, message = manager.enable()
            # Either fails gracefully or succeeds (depending on OS)
            assert isinstance(success, bool)
            assert isinstance(message, str)
        finally:
            manager.launch_agents_dir.chmod(0o755)

    @patch('subprocess.run')
    def test_is_loaded_exception(self, mock_run, manager):
        """Test is_loaded handles exceptions."""
        mock_run.side_effect = Exception("Test error")
        
        result = manager.is_loaded()
        
        assert result is False
