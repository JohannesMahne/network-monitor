"""Singleton lock for ensuring single application instance.

Uses file locking (fcntl) which is automatically released when the
process exits, even on crash.

Usage:
    from config.singleton import SingletonLock
    
    lock = SingletonLock()
    if not lock.acquire():
        lock.kill_existing()
        lock.acquire()
"""
import fcntl
import os
import signal
import tempfile
import time
from pathlib import Path
from typing import Optional

from config import get_logger

logger = get_logger(__name__)


class SingletonLock:
    """Ensures only one instance of the application can run at a time.
    
    Uses file locking (fcntl) which is automatically released when the
    process exits, even on crash.
    
    Attributes:
        lock_name: Name used for the lock file.
    
    Example:
        >>> lock = SingletonLock("my-app")
        >>> if lock.acquire():
        ...     print("Running as the only instance")
        ... else:
        ...     print("Another instance is running")
    """

    def __init__(self, lock_name: str = "network-monitor"):
        """Initialize the singleton lock.
        
        Args:
            lock_name: Base name for the lock file.
        """
        self._lock_file = Path(tempfile.gettempdir()) / f"{lock_name}.lock"
        self._lock_fd = None
        self._lock_name = lock_name

    def get_running_pid(self) -> Optional[int]:
        """Get the PID of the currently running instance, if any.
        
        Returns:
            PID of running instance, or None if no instance is running.
        """
        pid_file = self._lock_file.with_suffix('.pid')
        if not pid_file.exists():
            return None
        try:
            with open(pid_file) as f:
                pid_str = f.read().strip()
                if pid_str:
                    pid = int(pid_str)
                    # Check if process is actually running
                    os.kill(pid, 0)  # Signal 0 = check if process exists
                    return pid
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            pass
        return None

    def _write_pid(self) -> None:
        """Write our PID to the pid file."""
        pid_file = self._lock_file.with_suffix('.pid')
        try:
            with open(pid_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass  # Non-critical

    def _remove_pid(self) -> None:
        """Remove the pid file."""
        pid_file = self._lock_file.with_suffix('.pid')
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass  # Non-critical

    def kill_existing(self, timeout: float = 3.0) -> bool:
        """Kill any existing instance and wait for it to exit.
        
        Args:
            timeout: Maximum seconds to wait for graceful shutdown before force kill.
            
        Returns:
            True if no instance was running or it was successfully killed.
        """
        pid = self.get_running_pid()
        if pid is None:
            return True

        logger.info(f"Stopping existing instance (PID {pid})...")

        try:
            # Try SIGTERM first for graceful shutdown
            os.kill(pid, signal.SIGTERM)

            # Wait briefly for graceful exit
            start_time = time.time()
            while time.time() - start_time < timeout:
                try:
                    os.kill(pid, 0)  # Check if still running
                    time.sleep(0.2)
                except ProcessLookupError:
                    logger.info("Previous instance stopped gracefully.")
                    self._remove_pid()  # Clean up PID file
                    return True

            # Process didn't exit gracefully - force kill
            # (rumps/AppKit event loop may not process signals properly)
            logger.warning("Force killing (SIGKILL)...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
            self._remove_pid()  # Clean up PID file
            logger.info("Previous instance force stopped.")
            return True

        except ProcessLookupError:
            # Process already gone
            self._remove_pid()
            return True
        except PermissionError:
            logger.error(f"Permission denied to kill process {pid}")
            return False
        except Exception as e:
            logger.error(f"Error stopping existing instance: {e}")
            return False

    def acquire(self) -> bool:
        """Try to acquire the singleton lock.
        
        Returns:
            True if lock acquired (we're the only instance),
            False if another instance is already running.
        """
        try:
            self._lock_fd = open(self._lock_file, 'w')
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write our PID to separate file (lock file gets truncated on open)
            self._write_pid()
            logger.debug(f"Singleton lock acquired: {self._lock_file}")
            return True
        except OSError:
            # Lock is held by another process
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            return False

    def release(self) -> None:
        """Release the singleton lock."""
        self._remove_pid()
        if self._lock_fd:
            try:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
            except Exception:
                pass  # nosec B110 - Cleanup code, safe to ignore errors
            self._lock_fd = None
            logger.debug("Singleton lock released")


# Global singleton lock instance for convenience
_default_lock: Optional[SingletonLock] = None


def get_singleton_lock(lock_name: str = "network-monitor") -> SingletonLock:
    """Get or create the default singleton lock.
    
    Args:
        lock_name: Name for the lock file.
        
    Returns:
        The singleton lock instance.
    """
    global _default_lock
    if _default_lock is None:
        _default_lock = SingletonLock(lock_name)
    return _default_lock
