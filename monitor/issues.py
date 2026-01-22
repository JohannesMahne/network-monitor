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
    QUALITY_DROP = "quality_drop"


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
        self._last_quality_score: Optional[int] = None
        self._quality_drop_cooldown: float = 0  # Prevent spamming
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
    
    def check_quality_drop(self, current_score: Optional[int], 
                           latency: Optional[float] = None,
                           jitter: Optional[float] = None) -> Optional[NetworkIssue]:
        """Check for significant quality score drops.
        
        Args:
            current_score: Current quality score (0-100)
            latency: Current latency in ms (for troubleshooting info)
            jitter: Current jitter in ms (for troubleshooting info)
        
        Returns:
            NetworkIssue if quality dropped significantly, None otherwise
        """
        if current_score is None:
            return None
        
        current_time = time.time()
        
        # Cooldown to prevent spam (minimum 60 seconds between quality drop alerts)
        if current_time - self._quality_drop_cooldown < 60:
            self._last_quality_score = current_score
            return None
        
        issue = None
        
        # Detect significant drop (20+ points) or crossing into "poor" territory
        if self._last_quality_score is not None:
            drop = self._last_quality_score - current_score
            
            # Alert if: dropped 20+ points OR dropped into poor (<40) from good (>60)
            if drop >= 20 or (self._last_quality_score >= 60 and current_score < 40):
                # Determine the likely cause
                cause = self._diagnose_quality_drop(current_score, latency, jitter)
                
                issue = NetworkIssue(
                    timestamp=datetime.now(),
                    issue_type=IssueType.QUALITY_DROP,
                    description=f"Quality dropped: {self._last_quality_score}% → {current_score}%",
                    details={
                        "previous_score": self._last_quality_score,
                        "current_score": current_score,
                        "drop_amount": drop,
                        "latency_ms": latency,
                        "jitter_ms": jitter,
                        "likely_cause": cause,
                        "troubleshooting": self._get_troubleshooting_tips(cause)
                    }
                )
                self._add_issue(issue)
                self._quality_drop_cooldown = current_time
        
        self._last_quality_score = current_score
        return issue
    
    def _diagnose_quality_drop(self, score: int, latency: Optional[float], 
                                jitter: Optional[float]) -> str:
        """Diagnose the likely cause of a quality drop."""
        if latency is not None and latency > 150:
            return "high_latency"
        elif jitter is not None and jitter > 30:
            return "high_jitter"
        elif score < 40:
            return "poor_connection"
        else:
            return "network_congestion"
    
    def _get_troubleshooting_tips(self, cause: str) -> List[str]:
        """Get troubleshooting tips based on the cause."""
        tips = {
            "high_latency": [
                "Check if other devices are using bandwidth",
                "Try moving closer to your WiFi router",
                "Restart your router/modem",
                "Check for background downloads or updates",
                "Consider using a wired connection"
            ],
            "high_jitter": [
                "Network connection is unstable",
                "May indicate WiFi interference",
                "Try changing WiFi channel",
                "Check for microwave or other interference",
                "Consider using 5GHz instead of 2.4GHz"
            ],
            "poor_connection": [
                "Connection quality is degraded",
                "Check signal strength",
                "Restart network equipment",
                "Contact your ISP if issue persists",
                "Check for service outages in your area"
            ],
            "network_congestion": [
                "Network may be congested",
                "Too many devices or applications using bandwidth",
                "Try limiting active connections",
                "Schedule large downloads for off-peak hours"
            ]
        }
        return tips.get(cause, ["Check your network connection"])
    
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
