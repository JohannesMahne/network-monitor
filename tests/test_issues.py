"""Tests for issue detection."""
from datetime import datetime
from unittest.mock import patch

import pytest

from monitor.issues import IssueDetector, IssueType, NetworkIssue


class TestNetworkIssue:
    """Tests for NetworkIssue dataclass."""

    def test_basic_creation(self):
        """Test creating a NetworkIssue instance."""
        issue = NetworkIssue(
            timestamp=datetime.now(),
            issue_type=IssueType.HIGH_LATENCY,
            description="High latency detected"
        )
        assert issue.issue_type == IssueType.HIGH_LATENCY
        assert "latency" in issue.description.lower()

    def test_to_dict(self):
        """Test converting issue to dictionary."""
        issue = NetworkIssue(
            timestamp=datetime(2026, 1, 20, 10, 30, 0),
            issue_type=IssueType.DISCONNECT,
            description="Connection lost",
            details={"duration": 5}
        )
        data = issue.to_dict()
        assert data["type"] == "disconnect"
        assert data["description"] == "Connection lost"
        assert data["details"]["duration"] == 5

    def test_from_dict(self):
        """Test creating issue from dictionary."""
        data = {
            "timestamp": "2026-01-20T10:30:00",
            "type": "high_latency",
            "description": "Latency spike",
            "details": {"latency_ms": 150}
        }
        issue = NetworkIssue.from_dict(data)
        assert issue.issue_type == IssueType.HIGH_LATENCY
        assert issue.details["latency_ms"] == 150


class TestIssueType:
    """Tests for IssueType enum."""

    def test_values(self):
        """Test enum values."""
        assert IssueType.DISCONNECT.value == "disconnect"
        assert IssueType.RECONNECT.value == "reconnect"
        assert IssueType.HIGH_LATENCY.value == "high_latency"
        assert IssueType.SPEED_DROP.value == "speed_drop"
        assert IssueType.CONNECTION_CHANGE.value == "connection_change"


class TestIssueDetector:
    """Tests for IssueDetector class."""

    @pytest.fixture
    def detector(self):
        """Create an IssueDetector instance."""
        return IssueDetector(max_issues=100)

    def test_init(self, detector):
        """Test detector initialization."""
        assert len(detector._issues) == 0
        assert detector._was_connected is True

    def test_check_connectivity_disconnect(self, detector):
        """Test detecting disconnection."""
        issue = detector.check_connectivity(is_connected=False)

        assert issue is not None
        assert issue.issue_type == IssueType.DISCONNECT
        assert detector._was_connected is False

    def test_check_connectivity_reconnect(self, detector):
        """Test detecting reconnection."""
        # First disconnect
        detector.check_connectivity(is_connected=False)

        # Then reconnect
        issue = detector.check_connectivity(is_connected=True)

        assert issue is not None
        assert issue.issue_type == IssueType.RECONNECT
        assert "reconnected" in issue.description.lower()

    def test_check_connectivity_no_change(self, detector):
        """Test no issue when connection unchanged."""
        # Already connected, check again
        issue = detector.check_connectivity(is_connected=True)

        assert issue is None

    @patch.object(IssueDetector, '_ping')
    def test_check_latency_high(self, mock_ping, detector):
        """Test detecting high latency."""
        mock_ping.return_value = 250.0  # High latency (above 200ms threshold)

        issue = detector.check_latency(force=True)

        assert issue is not None
        assert issue.issue_type == IssueType.HIGH_LATENCY
        assert issue.details["latency_ms"] == 250.0

    @patch.object(IssueDetector, '_ping')
    def test_check_latency_normal(self, mock_ping, detector):
        """Test no issue with normal latency."""
        mock_ping.return_value = 25.0  # Normal latency

        issue = detector.check_latency(force=True)

        assert issue is None

    @patch.object(IssueDetector, '_ping')
    def test_check_latency_failed(self, mock_ping, detector):
        """Test handling ping failure."""
        mock_ping.return_value = None  # Ping failed

        issue = detector.check_latency(force=True)

        # No issue logged for failed ping (might be temporary)
        assert issue is None

    def test_check_speed_drop(self, detector):
        """Test detecting significant speed drop."""
        # Average speed was 100 KB/s (above 1KB/s threshold), now dropped to 5 KB/s
        issue = detector.check_speed_drop(
            current_speed=5000,    # 5 KB/s (5% of average)
            average_speed=100000   # 100 KB/s
        )

        assert issue is not None
        assert issue.issue_type == IssueType.SPEED_DROP

    def test_check_speed_drop_normal(self, detector):
        """Test no issue with normal speed variation."""
        # Speed dropped but not significantly
        issue = detector.check_speed_drop(
            current_speed=8000000,  # 8 MB/s
            average_speed=10000000  # 10 MB/s
        )

        assert issue is None

    def test_check_speed_drop_zero_average(self, detector):
        """Test handling zero average speed."""
        issue = detector.check_speed_drop(
            current_speed=1000000,
            average_speed=0
        )

        assert issue is None

    def test_log_connection_change(self, detector):
        """Test logging connection change."""
        issue = detector.log_connection_change("WiFi:Network1", "WiFi:Network2")

        assert issue.issue_type == IssueType.CONNECTION_CHANGE
        assert "Network1" in issue.description
        assert "Network2" in issue.description

    def test_get_recent_issues(self, detector):
        """Test getting recent issues."""
        # Add some issues
        detector.check_connectivity(is_connected=False)
        detector.check_connectivity(is_connected=True)
        detector.log_connection_change("A", "B")

        issues = detector.get_recent_issues(count=2)
        assert len(issues) == 2

    def test_get_all_issues(self, detector):
        """Test getting all issues."""
        detector.check_connectivity(is_connected=False)
        detector.log_connection_change("A", "B")

        issues = detector.get_all_issues()
        assert len(issues) == 2

    def test_clear_issues(self, detector):
        """Test clearing all issues."""
        detector.check_connectivity(is_connected=False)
        detector.clear_issues()

        assert len(detector.get_all_issues()) == 0

    def test_max_issues_limit(self):
        """Test that issues are limited to max count."""
        detector = IssueDetector(max_issues=5)

        # Add more than max issues
        for i in range(10):
            detector.log_connection_change(f"Net{i}", f"Net{i+1}")

        assert len(detector.get_all_issues()) == 5

    def test_get_issues_as_dicts(self, detector):
        """Test getting issues as dictionaries."""
        detector.log_connection_change("A", "B")

        dicts = detector.get_issues_as_dicts()
        assert len(dicts) == 1
        assert "type" in dicts[0]
        assert "description" in dicts[0]

    def test_load_issues(self, detector):
        """Test loading issues from dict data."""
        data = [
            {
                "timestamp": "2026-01-20T10:30:00",
                "type": "disconnect",
                "description": "Test disconnect",
                "details": {}
            }
        ]
        detector.load_issues(data)

        assert len(detector.get_all_issues()) == 1

    @patch.object(IssueDetector, '_ping')
    def test_get_current_latency(self, mock_ping, detector):
        """Test getting current latency."""
        mock_ping.return_value = 45.0

        latency = detector.get_current_latency()
        assert latency == 45.0

    def test_check_quality_drop(self, detector):
        """Test quality drop detection."""
        # Set initial score
        detector._last_quality_score = 85

        # Significant drop
        issue = detector.check_quality_drop(
            current_score=40,
            latency=150.0,
            jitter=25.0
        )

        assert issue is not None
        assert issue.issue_type == IssueType.QUALITY_DROP

    def test_check_quality_drop_minor(self, detector):
        """Test no issue with minor quality variation."""
        detector._last_quality_score = 85

        # Minor drop (less than 20 points)
        issue = detector.check_quality_drop(current_score=75)

        assert issue is None

    def test_diagnose_quality_drop_latency(self, detector):
        """Test quality drop diagnosis for high latency."""
        cause = detector._diagnose_quality_drop(50, latency=200.0, jitter=10.0)
        assert cause == "high_latency"

    def test_diagnose_quality_drop_jitter(self, detector):
        """Test quality drop diagnosis for high jitter."""
        cause = detector._diagnose_quality_drop(50, latency=30.0, jitter=50.0)
        assert cause == "high_jitter"

    def test_get_troubleshooting_tips(self, detector):
        """Test getting troubleshooting tips."""
        tips = detector._get_troubleshooting_tips("high_latency")
        assert len(tips) > 0
        assert any("router" in tip.lower() for tip in tips)
