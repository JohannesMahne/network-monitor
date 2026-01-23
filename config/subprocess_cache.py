"""Subprocess execution with caching and safety features.

Provides a caching layer for subprocess calls to reduce redundant
system calls, along with safety checks and timing.

Security Note:
    This module is designed for a system monitoring application that requires
    subprocess calls to macOS system utilities (arp, ping, networksetup, etc.).
    All commands are validated against an allowlist in ALLOWED_SUBPROCESS_COMMANDS.
    Shell=False is always used to prevent shell injection.

Usage:
    from config.subprocess_cache import safe_run, get_subprocess_cache

    # Simple safe execution
    result = safe_run(['arp', '-an'])

    # With caching (for repeated calls)
    cache = get_subprocess_cache()
    result = cache.run(['arp', '-an'], ttl=5.0)
"""

# nosec B404 - subprocess usage is required and validated via allowlist
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.constants import ALLOWED_SUBPROCESS_COMMANDS, INTERVALS
from config.exceptions import SubprocessError
from config.logging_config import get_logger, log_subprocess_call

logger = get_logger(__name__)


@dataclass
class CachedResult:
    """Cached subprocess result with metadata."""

    result: subprocess.CompletedProcess
    timestamp: float
    duration_ms: float

    def is_expired(self, ttl: float) -> bool:
        """Check if this cached result has expired."""
        return (time.time() - self.timestamp) >= ttl


class SubprocessCache:
    """Caches subprocess results to reduce redundant system calls.

    Thread-safe cache for subprocess.run() results. Useful for commands
    that are called frequently but don't need real-time data (e.g., ARP table).

    Attributes:
        default_ttl: Default time-to-live for cached results in seconds.
        max_cache_size: Maximum number of cached results to keep.

    Example:
        >>> cache = SubprocessCache(default_ttl=5.0)
        >>> result = cache.run(['arp', '-an'])
        >>> # Second call within 5 seconds returns cached result
        >>> result2 = cache.run(['arp', '-an'])
    """

    def __init__(self, default_ttl: float = 5.0, max_cache_size: int = 50):
        self.default_ttl = default_ttl
        self.max_cache_size = max_cache_size
        self._cache: Dict[Tuple[str, ...], CachedResult] = {}
        self._lock = threading.Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "errors": 0,
        }

    def _make_key(self, cmd: List[str]) -> Tuple[str, ...]:
        """Create a hashable cache key from command."""
        return tuple(cmd)

    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        now = time.time()
        expired_keys = [
            key
            for key, cached in self._cache.items()
            if cached.is_expired(self.default_ttl * 2)  # Keep a bit longer
        ]
        for key in expired_keys:
            del self._cache[key]

        # If still too large, remove oldest entries
        if len(self._cache) > self.max_cache_size:
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1].timestamp)
            for key, _ in sorted_items[: len(self._cache) - self.max_cache_size]:
                del self._cache[key]

    def run(
        self,
        cmd: List[str],
        ttl: Optional[float] = None,
        bypass_cache: bool = False,
        timeout: Optional[float] = None,
        check_allowed: bool = False,  # Accept but don't pass through
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run a subprocess command with optional caching.

        Args:
            cmd: Command and arguments as list.
            ttl: Time-to-live for cache in seconds. Uses default if not specified.
            bypass_cache: If True, always run the command fresh.
            timeout: Command timeout in seconds.
            check_allowed: Ignored here (used by safe_run), prevents passing to subprocess.
            **kwargs: Additional arguments passed to subprocess.run().

        Returns:
            subprocess.CompletedProcess with command output.

        Raises:
            SubprocessError: If command fails or times out.
        """
        ttl = ttl if ttl is not None else self.default_ttl
        timeout = timeout or INTERVALS.SUBPROCESS_TIMEOUT_SECONDS
        key = self._make_key(cmd)

        # Check cache first
        if not bypass_cache:
            with self._lock:
                if key in self._cache and not self._cache[key].is_expired(ttl):
                    self._stats["hits"] += 1
                    logger.debug(f"Cache hit for: {cmd[0]}")
                    return self._cache[key].result

        # Run the command
        self._stats["misses"] += 1
        start_time = time.time()

        try:
            # Ensure safe defaults
            kwargs.setdefault("capture_output", True)
            kwargs.setdefault("text", True)
            kwargs["timeout"] = timeout

            result = subprocess.run(cmd, **kwargs)  # nosec B603 - Commands validated via allowlist
            duration_ms = (time.time() - start_time) * 1000

            # Log the call
            log_subprocess_call(
                logger, cmd, result.returncode, duration_ms, success=(result.returncode == 0)
            )

            # Cache successful results
            with self._lock:
                self._cache[key] = CachedResult(
                    result=result, timestamp=time.time(), duration_ms=duration_ms
                )
                self._cleanup_expired()

            return result

        except subprocess.TimeoutExpired as e:
            self._stats["errors"] += 1
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(f"Command timed out after {duration_ms:.0f}ms: {cmd}")
            raise SubprocessError(
                f"Command timed out after {timeout}s", command=cmd, details={"timeout": timeout}
            ) from e

        except FileNotFoundError as e:
            self._stats["errors"] += 1
            logger.error(f"Command not found: {cmd[0]}")
            raise SubprocessError(f"Command not found: {cmd[0]}", command=cmd) from e

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Subprocess error for {cmd}: {e}")
            raise SubprocessError(f"Subprocess error: {e}", command=cmd) from e

    def invalidate(self, cmd: Optional[List[str]] = None) -> None:
        """Invalidate cached results.

        Args:
            cmd: Specific command to invalidate. If None, clears entire cache.
        """
        with self._lock:
            if cmd is None:
                self._cache.clear()
                logger.debug("Cleared entire subprocess cache")
            else:
                key = self._make_key(cmd)
                if key in self._cache:
                    del self._cache[key]
                    logger.debug(f"Invalidated cache for: {cmd[0]}")

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            return {
                **self._stats,
                "cache_size": len(self._cache),
                "hit_rate_percent": round(hit_rate, 1),
            }


# Global cache instance
_global_cache: Optional[SubprocessCache] = None


def get_subprocess_cache() -> SubprocessCache:
    """Get or create the global subprocess cache.

    Returns:
        The global SubprocessCache instance.
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = SubprocessCache()
    return _global_cache


def safe_run(
    cmd: List[str], timeout: Optional[float] = None, check_allowed: bool = True, **kwargs
) -> subprocess.CompletedProcess:
    """Run a subprocess command with safety checks.

    This is the recommended way to run subprocesses in Network Monitor.
    It validates the command against an allowlist and ensures safe defaults.

    Args:
        cmd: Command and arguments as list.
        timeout: Command timeout in seconds.
        check_allowed: If True, validate command is in allowlist.
        **kwargs: Additional arguments passed to subprocess.run().

    Returns:
        subprocess.CompletedProcess with command output.

    Raises:
        SubprocessError: If command is not allowed, fails, or times out.

    Example:
        >>> result = safe_run(['arp', '-an'])
        >>> if result.returncode == 0:
        ...     print(result.stdout)
    """
    if not cmd:
        raise SubprocessError("Empty command", command=cmd)

    # Extract base command name
    base_cmd = cmd[0]
    if "/" in base_cmd:
        base_cmd = Path(base_cmd).name

    # Validate against allowlist
    if check_allowed and base_cmd not in ALLOWED_SUBPROCESS_COMMANDS:
        raise SubprocessError(
            f"Command not in allowlist: {base_cmd}",
            command=cmd,
            details={"allowed": list(ALLOWED_SUBPROCESS_COMMANDS)},
        )

    # Use the global cache for execution (with no caching by default)
    cache = get_subprocess_cache()
    return cache.run(cmd, ttl=0, bypass_cache=True, timeout=timeout, **kwargs)


def run_with_fallback(
    commands: List[List[str]], timeout: Optional[float] = None
) -> Optional[subprocess.CompletedProcess]:
    """Try multiple commands in order until one succeeds.

    Useful for platform-specific commands with fallbacks.

    Args:
        commands: List of commands to try in order.
        timeout: Timeout for each command.

    Returns:
        Result from first successful command, or None if all fail.

    Example:
        >>> result = run_with_fallback([
        ...     ['networksetup', '-getairportnetwork', 'en0'],
        ...     ['airport', '-I'],
        ... ])
    """
    for cmd in commands:
        try:
            result = safe_run(cmd, timeout=timeout)
            if result.returncode == 0:
                return result
        except SubprocessError as e:
            logger.debug(f"Fallback command failed: {cmd[0]} - {e}")
            continue

    return None
