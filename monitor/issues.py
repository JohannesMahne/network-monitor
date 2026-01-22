"""Network issue detection and logging."""
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from enum import Enum

from config import get_logger, THRESHOLDS, NETWORK, INTERVALS
from config.subprocess_cache import safe_run

logger = get_logger(__name__)


class IssueType(Enum):
    """Types of network issues."""
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"
    HIGH_LATENCY = "high_latency"
    SPEED_DROP = "speed_drop"
    CONNECTION_CHANGE = "connection_change"


@dataclass
class NetworkIssue:
    """Represents a detected network issue."""
    timestamp: datetime
    issue_type: IssueType
    description: str
    details: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "type": self.issue_type.value,
            "description": self.description,
            "details": self.details
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'NetworkIssue':
        """Create from dictionary."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            issue_type=IssueType(data["type"]),
            description=data["description"],
            details=data.get("details", {})
        )


class IssueDetector:
    """Detects and logs network issues."""
    
    # Thresholds for issue detection - use constants
    HIGH_LATENCY_MS = THRESHOLDS.HIGH_LATENCY_MS
    SPEED_DROP_THRESHOLD = THRESHOLDS.SPEED_DROP_RATIO
    PING_HOST = NETWORK.DEFAULT_PING_HOST
    
    def __init__(self, max_issues: int = None):
        self._issues: List[NetworkIssue] = []
        self._max_issues = max_issues or THRESHOLDS.MAX_ISSUES_STORED
        self._was_connected = True
        self._last_disconnect_time: Optional[float] = None
        self._last_latency_check: float = 0
        self._latency_check_interval = INTERVALS.LATENCY_CHECK_SECONDS * 3  # Less frequent for issue check
        self._average_speed: float = 0
        logger.debug("IssueDetector initialized")
    
    def check_connectivity(self, is_connected: bool) -> Optional[NetworkIssue]:
        """Check for connectivity changes and log issues."""
        issue = None
        
        if not is_connected and self._was_connected:
            # Just disconnected
            self._last_disconnect_time = time.time()
            issue = NetworkIssue(
                timestamp=datetime.now(),
                issue_type=IssueType.DISCONNECT,
                description="Network connection lost"
            )
            self._add_issue(issue)
        
        elif is_connected and not self._was_connected:
            # Just reconnected
            duration = 0
            if self._last_disconnect_time:
                duration = int(time.time() - self._last_disconnect_time)
            
            issue = NetworkIssue(
                timestamp=datetime.now(),
                issue_type=IssueType.RECONNECT,
                description=f"Network reconnected after {duration}s",
                details={"downtime_seconds": duration}
            )
            self._add_issue(issue)
            self._last_disconnect_time = None
        
        self._was_connected = is_connected
        return issue
    
    def check_latency(self, force: bool = False) -> Optional[NetworkIssue]:
        """Check network latency via ping."""
        current_time = time.time()
        
        if not force and (current_time - self._last_latency_check) < self._latency_check_interval:
            return None
        
        self._last_latency_check = current_time
        latency = self._ping()
        
        if latency is None:
            # Ping failed, might indicate issues
            return None
        
        if latency > self.HIGH_LATENCY_MS:
            issue = NetworkIssue(
                timestamp=datetime.now(),
                issue_type=IssueType.HIGH_LATENCY,
                description=f"High latency detected: {latency:.0f}ms",
                details={"latency_ms": latency}
            )
            self._add_issue(issue)
            return issue
        
        return None
    
    def check_speed_drop(self, current_speed: float, average_speed: float) -> Optional[NetworkIssue]:
        """Check for significant speed drops."""
        if average_speed <= 0:
            return None
        
        self._average_speed = average_speed
        ratio = current_speed / average_speed
        
        # Only alert if speed dropped significantly AND average was meaningful
        if ratio < self.SPEED_DROP_THRESHOLD and average_speed > THRESHOLDS.MIN_SPEED_FOR_DROP_ALERT:
            issue = NetworkIssue(
                timestamp=datetime.now(),
                issue_type=IssueType.SPEED_DROP,
                description=f"Speed dropped to {ratio*100:.0f}% of average",
                details={
                    "current_speed": current_speed,
                    "average_speed": average_speed,
                    "ratio": ratio
                }
            )
            self._add_issue(issue)
            return issue
        
        return None
    
    def log_connection_change(self, old_conn: str, new_conn: str) -> NetworkIssue:
        """Log a connection change event."""
        issue = NetworkIssue(
            timestamp=datetime.now(),
            issue_type=IssueType.CONNECTION_CHANGE,
            description=f"Connection changed: {old_conn} → {new_conn}",
            details={"from": old_conn, "to": new_conn}
        )
        self._add_issue(issue)
        return issue
    
    def _ping(self, host: str = None) -> Optional[float]:
        """Ping and return latency in milliseconds."""
        target = host or self.PING_HOST
        try:
            result = safe_run(
                ['ping', '-c', '1', '-W', '2', target],
                timeout=INTERVALS.PING_TIMEOUT_SECONDS + 3  # Allow for ping timeout + overhead
            )
            if result.returncode == 0:
                import re
                # Try multiple patterns for different ping output formats
                
                # Pattern 1: "time=9.742 ms" or "time<1 ms"
                match = re.search(r'time[=<](\d+\.?\d*)\s*ms', result.stdout)
                if match:
                    return float(match.group(1))
                
                # Pattern 2: macOS format "round-trip min/avg/max/stddev = X/Y/Z/W ms"
                match = re.search(r'round-trip.*?=\s*[\d.]+/([\d.]+)/', result.stdout)
                if match:
                    return float(match.group(1))
                
                # Pattern 3: Just look for any number before "ms"
                match = re.search(r'(\d+\.?\d*)\s*ms', result.stdout)
                if match:
                    return float(match.group(1))
        except Exception:
            pass
        return None
    
    def get_current_latency(self) -> Optional[float]:
        """Get current latency in milliseconds (public method)."""
        return self._ping()
    
    def get_latency_to_host(self, host: str) -> Optional[float]:
        """Get latency to a specific host in milliseconds."""
        return self._ping(host)
    
    def _add_issue(self, issue: NetworkIssue) -> None:
        """Add an issue to the log, maintaining max size."""
        self._issues.append(issue)
        if len(self._issues) > self._max_issues:
            self._issues.pop(0)
    
    def get_recent_issues(self, count: int = 10) -> List[NetworkIssue]:
        """Get the most recent issues."""
        return self._issues[-count:]
    
    def get_all_issues(self) -> List[NetworkIssue]:
        """Get all logged issues."""
        return self._issues.copy()
    
    def get_issues_as_dicts(self) -> List[dict]:
        """Get all issues as dictionaries for JSON serialization."""
        return [issue.to_dict() for issue in self._issues]
    
    def load_issues(self, issues_data: List[dict]) -> None:
        """Load issues from dictionary data."""
        self._issues = [NetworkIssue.from_dict(d) for d in issues_data]
    
    def clear_issues(self) -> None:
        """Clear all logged issues."""
        self._issues.clear()
