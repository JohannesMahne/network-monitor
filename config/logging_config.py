"""Logging configuration for Network Monitor.

Provides structured logging with file rotation and optional debug output.
All components should use this logging system instead of print().

Usage:
    from config.logging_config import setup_logging, get_logger
    
    # Initialize at app startup
    setup_logging(data_dir=Path.home() / ".network-monitor")
    
    # Get logger in any module
    logger = get_logger(__name__)
    logger.info("Application started")
    logger.error("Something went wrong", exc_info=True)
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from datetime import datetime

from config.constants import STORAGE


# Module-level logger cache
_loggers: dict = {}
_initialized: bool = False
_root_logger: Optional[logging.Logger] = None


class NetworkMonitorFormatter(logging.Formatter):
    """Custom formatter with color support for console output."""
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m',
    }
    
    def __init__(self, use_colors: bool = True):
        self.use_colors = use_colors
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors and sys.stderr.isatty():
            color = self.COLORS.get(record.levelname, '')
            reset = self.COLORS['RESET']
            record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)


def setup_logging(
    data_dir: Optional[Path] = None,
    debug: bool = False,
    console_output: bool = True,
    log_to_file: bool = True
) -> logging.Logger:
    """Initialize the logging system.
    
    Should be called once at application startup. Subsequent calls
    will reconfigure the existing logger.
    
    Args:
        data_dir: Directory for log files. Defaults to ~/.network-monitor/
        debug: Enable debug-level logging.
        console_output: Also log to stderr.
        log_to_file: Write logs to file with rotation.
    
    Returns:
        The root logger for the application.
    
    Example:
        >>> from pathlib import Path
        >>> logger = setup_logging(Path.home() / ".network-monitor", debug=True)
        >>> logger.info("Application initialized")
    """
    global _initialized, _root_logger
    
    if data_dir is None:
        data_dir = Path.home() / STORAGE.DATA_DIR_NAME
    
    # Ensure data directory exists
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Create or get root logger
    root_logger = logging.getLogger('netmon')
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # File handler with rotation
    if log_to_file:
        log_file = data_dir / STORAGE.LOG_FILE
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=STORAGE.LOG_MAX_BYTES,
            backupCount=STORAGE.LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        root_logger.addHandler(file_handler)
    
    # Console handler (stderr)
    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)
        console_handler.setFormatter(NetworkMonitorFormatter(use_colors=True))
        root_logger.addHandler(console_handler)
    
    # Log initialization
    root_logger.info(
        f"Logging initialized - level={'DEBUG' if debug else 'INFO'}, "
        f"file={log_to_file}, console={console_output}"
    )
    
    _initialized = True
    _root_logger = root_logger
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module.
    
    Returns a child logger of the root 'netmon' logger. If logging
    hasn't been initialized, creates a basic logger.
    
    Args:
        name: Usually __name__ of the calling module.
    
    Returns:
        A configured logger instance.
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing started")
        >>> logger.error("Something failed", exc_info=True)
    """
    global _loggers
    
    # Create short name for cleaner logs
    # e.g., "monitor.scanner" instead of full module path
    short_name = name
    if '.' in name:
        parts = name.split('.')
        # Keep last 2 parts at most
        short_name = '.'.join(parts[-2:]) if len(parts) > 1 else parts[-1]
    
    if short_name not in _loggers:
        if not _initialized:
            # Fallback: create a basic logger if setup wasn't called
            logging.basicConfig(level=logging.INFO)
        
        logger = logging.getLogger(f'netmon.{short_name}')
        _loggers[short_name] = logger
    
    return _loggers[short_name]


def log_exception(logger: logging.Logger, message: str, exc: Exception) -> None:
    """Log an exception with full traceback and context.
    
    Args:
        logger: The logger to use.
        message: Descriptive message about what was happening.
        exc: The exception that was caught.
    
    Example:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_exception(logger, "Failed to complete operation", e)
    """
    logger.error(
        f"{message}: {type(exc).__name__}: {exc}",
        exc_info=True,
        extra={'exception_type': type(exc).__name__}
    )


def log_subprocess_call(
    logger: logging.Logger,
    command: list,
    returncode: int,
    duration_ms: float,
    success: bool
) -> None:
    """Log a subprocess call with timing information.
    
    Args:
        logger: The logger to use.
        command: The command that was run.
        returncode: Exit code of the process.
        duration_ms: How long the command took in milliseconds.
        success: Whether the command succeeded.
    """
    level = logging.DEBUG if success else logging.WARNING
    logger.log(
        level,
        f"Subprocess: {' '.join(command[:3])}{'...' if len(command) > 3 else ''} "
        f"-> rc={returncode}, {duration_ms:.1f}ms"
    )


class LogContext:
    """Context manager for logging operation duration.
    
    Example:
        >>> with LogContext(logger, "Device scan"):
        ...     scan_devices()
        # Logs: "Device scan completed in 1234ms"
    """
    
    def __init__(self, logger: logging.Logger, operation: str, level: int = logging.DEBUG):
        self.logger = logger
        self.operation = operation
        self.level = level
        self.start_time: Optional[datetime] = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.log(self.level, f"{self.operation} starting...")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds() * 1000
        
        if exc_type:
            self.logger.error(
                f"{self.operation} failed after {duration:.0f}ms: {exc_val}"
            )
        else:
            self.logger.log(
                self.level,
                f"{self.operation} completed in {duration:.0f}ms"
            )
        
        return False  # Don't suppress exceptions
