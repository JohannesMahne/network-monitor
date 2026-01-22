"""macOS Launch Agent management for auto-start at login."""
import os
import plistlib
import subprocess
from pathlib import Path
from typing import Optional


class LaunchAgentManager:
    """Manages the macOS Launch Agent for auto-starting the app at login."""
    
    AGENT_LABEL = "com.networkmonitor.app"
    AGENT_FILENAME = f"{AGENT_LABEL}.plist"
    
    def __init__(self):
        self.launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        self.agent_path = self.launch_agents_dir / self.AGENT_FILENAME
        self.app_dir = Path(__file__).parent.parent.resolve()
        self.python_path = self._get_python_path()
        self.script_path = self.app_dir / "network_monitor.py"
    
    def _get_python_path(self) -> str:
        """Get the path to the Python interpreter (preferring venv if available)."""
        venv_python = self.app_dir / "venv" / "bin" / "python"
        if venv_python.exists():
            return str(venv_python)
        
        # Fall back to system python3
        return "/usr/bin/python3"
    
    def _create_plist_content(self) -> dict:
        """Create the Launch Agent plist content."""
        return {
            "Label": self.AGENT_LABEL,
            "ProgramArguments": [
                self.python_path,
                str(self.script_path)
            ],
            "WorkingDirectory": str(self.app_dir),
            "RunAtLoad": True,
            "KeepAlive": False,
            "StandardOutPath": str(Path.home() / ".network-monitor" / "stdout.log"),
            "StandardErrorPath": str(Path.home() / ".network-monitor" / "stderr.log"),
            "EnvironmentVariables": {
                "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
            }
        }
    
    def is_enabled(self) -> bool:
        """Check if Launch at Login is enabled."""
        return self.agent_path.exists()
    
    def is_loaded(self) -> bool:
        """Check if the launch agent is currently loaded."""
        try:
            result = subprocess.run(
                ["launchctl", "list", self.AGENT_LABEL],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def enable(self) -> tuple[bool, str]:
        """Enable Launch at Login.
        
        Returns (success, message) tuple.
        """
        try:
            # Ensure LaunchAgents directory exists
            self.launch_agents_dir.mkdir(parents=True, exist_ok=True)
            
            # Ensure log directory exists
            log_dir = Path.home() / ".network-monitor"
            log_dir.mkdir(parents=True, exist_ok=True)
            
            # Create the plist file
            plist_content = self._create_plist_content()
            
            with open(self.agent_path, 'wb') as f:
                plistlib.dump(plist_content, f)
            
            # Load the agent (so it takes effect immediately for future logins)
            # Note: We don't load it now since the app is already running
            
            return True, "Launch at Login enabled"
            
        except PermissionError:
            return False, "Permission denied - cannot write to LaunchAgents"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def disable(self) -> tuple[bool, str]:
        """Disable Launch at Login.
        
        Returns (success, message) tuple.
        """
        try:
            # Unload the agent if loaded
            if self.is_loaded():
                subprocess.run(
                    ["launchctl", "unload", str(self.agent_path)],
                    capture_output=True
                )
            
            # Remove the plist file
            if self.agent_path.exists():
                self.agent_path.unlink()
            
            return True, "Launch at Login disabled"
            
        except PermissionError:
            return False, "Permission denied - cannot remove LaunchAgent"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def toggle(self) -> tuple[bool, str]:
        """Toggle Launch at Login on/off.
        
        Returns (success, message) tuple.
        """
        if self.is_enabled():
            return self.disable()
        else:
            return self.enable()
    
    def get_status(self) -> str:
        """Get human-readable status."""
        if self.is_enabled():
            return "✓ Launch at Login: On"
        else:
            return "○ Launch at Login: Off"


def get_launch_agent_manager() -> LaunchAgentManager:
    """Get a LaunchAgentManager instance."""
    return LaunchAgentManager()
