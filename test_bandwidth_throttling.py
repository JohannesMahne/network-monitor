#!/usr/bin/env python3
"""Test script for bandwidth throttling feature.

This script helps you test the bandwidth throttling alerts by:
1. Enabling bandwidth alerts
2. Setting a low threshold for testing
3. Showing how to trigger alerts

Usage:
    python3 test_bandwidth_throttling.py
"""
import json
from pathlib import Path
from config import STORAGE

def enable_bandwidth_alerts():
    """Enable bandwidth alerts with test settings."""
    settings_file = Path.home() / STORAGE.DATA_DIR_NAME / STORAGE.SETTINGS_FILE
    
    # Load existing settings
    if settings_file.exists():
        with open(settings_file) as f:
            settings = json.load(f)
    else:
        settings = {}
    
    # Enable bandwidth alerts with realistic thresholds for 100 Mbps down / 50 Mbps up
    settings['bandwidth_alerts'] = {
        "enabled": True,
        "threshold_mbps": 50.0,  # Default threshold: 50 Mbps (half of download speed)
        "window_seconds": 30,
        "per_app_thresholds": {
            # Per-app thresholds (optional - apps not listed use default)
            # "Chrome": 60.0,
            # "Safari": 50.0,
            # "Network Monitor": 10.0,  # Lower for the monitor itself
        }
    }
    
    # Save settings
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_file, 'w') as f:
        json.dump(settings, f, indent=2)
    
    print(f"✅ Bandwidth alerts enabled!")
    print(f"   Default threshold: 50.0 Mbps (suitable for 100 Mbps down / 50 Mbps up)")
    print(f"   Window: 30 seconds")
    print(f"\n📝 Settings saved to: {settings_file}")
    print("\n💡 To test:")
    print("   1. Restart Network Monitor")
    print("   2. Start a download/upload that exceeds 50 Mbps")
    print("   3. Wait 30 seconds for the window to collect data")
    print("   4. You should see a notification when threshold is exceeded")
    print("\n💡 For a 100 Mbps down / 50 Mbps up connection:")
    print("   - Default threshold: 50 Mbps (catches high usage)")
    print("   - You can set per-app thresholds in the settings file")
    print("\n💡 To set per-app thresholds, edit the 'per_app_thresholds' section")
    print("   in the settings file, or use the Python API:")

def show_python_api_example():
    """Show how to use the Python API to configure thresholds."""
    print("\n" + "="*60)
    print("Python API Example:")
    print("="*60)
    print("""
from storage.settings import get_settings_manager, BandwidthAlertSettings

settings = get_settings_manager()

# Enable alerts (for 100 Mbps down / 50 Mbps up connection)
alert_settings = BandwidthAlertSettings(
    enabled=True,
    threshold_mbps=50.0,  # 50 Mbps default (half of download speed)
    window_seconds=30
)
settings.set_bandwidth_alert_settings(alert_settings)

# Set per-app thresholds (optional)
settings.set_app_bandwidth_threshold("Chrome", 60.0)  # 60 Mbps for Chrome
settings.set_app_bandwidth_threshold("Safari", 50.0)  # 50 Mbps for Safari
settings.set_app_bandwidth_threshold("Network Monitor", 10.0)  # Lower for monitor
""")

if __name__ == "__main__":
    print("🔧 Bandwidth Throttling Test Setup")
    print("="*60)
    enable_bandwidth_alerts()
    show_python_api_example()
    print("\n" + "="*60)
    print("✅ Setup complete! Restart Network Monitor to apply changes.")
