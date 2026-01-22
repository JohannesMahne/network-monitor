"""Tests for monitor/scanner.py"""
import pytest
from monitor.scanner import (
    NetworkDevice, DeviceType, DeviceNameStore, OUIDatabase,
    normalize_mac, infer_device_type
)


class TestNormalizeMac:
    """Tests for MAC address normalisation."""
    
    def test_already_normalized(self):
        assert normalize_mac("AA:BB:CC:DD:EE:FF") == "AA:BB:CC:DD:EE:FF"
    
    def test_lowercase(self):
        assert normalize_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    
    def test_dash_separator(self):
        assert normalize_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"
    
    def test_no_leading_zeros(self):
        assert normalize_mac("A:B:C:D:E:F") == "0A:0B:0C:0D:0E:0F"


class TestOUIDatabase:
    """Tests for OUI vendor lookup."""
    
    def test_singleton(self):
        db1 = OUIDatabase()
        db2 = OUIDatabase()
        assert db1 is db2
    
    def test_lookup_unknown(self):
        db = OUIDatabase()
        # Random MAC that's unlikely to be in database
        result = db.lookup("FF:FF:FF:11:22:33")
        # May or may not find it, but shouldn't crash
        assert result is None or isinstance(result, str)


class TestNetworkDevice:
    """Tests for the NetworkDevice dataclass."""
    
    def test_display_name_with_custom_name(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            custom_name="My iPhone"
        )
        assert device.display_name == "My iPhone"
    
    def test_display_name_with_mdns_name(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            mdns_name="Johns-MacBook"
        )
        assert device.display_name == "Johns-MacBook"
    
    def test_display_name_with_model_hint(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            model_hint="MacBook Pro"
        )
        assert device.display_name == "MacBook Pro"
    
    def test_display_name_with_hostname(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            hostname="johns-macbook.local"
        )
        assert device.display_name == "johns-macbook"
    
    def test_display_name_with_vendor(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            vendor="Samsung"
        )
        assert device.display_name == "Samsung"
    
    def test_display_name_fallback_to_ip(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF"
        )
        assert device.display_name == "192.168.1.100"
    
    def test_type_icon(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            device_type=DeviceType.PHONE
        )
        assert device.type_icon == "📱"


class TestInferDeviceType:
    """Tests for device type inference."""
    
    def test_iphone_hostname(self):
        dtype, os_hint, model = infer_device_type(None, "Johns-iPhone")
        assert dtype == DeviceType.PHONE
        assert os_hint == "iOS"
        assert model == "iPhone"
    
    def test_macbook_hostname(self):
        dtype, os_hint, model = infer_device_type(None, "MacBook-Pro")
        assert dtype == DeviceType.LAPTOP
        assert os_hint == "macOS"
    
    def test_apple_vendor_default(self):
        dtype, os_hint, model = infer_device_type("Apple", None)
        assert dtype == DeviceType.LAPTOP  # Default for Apple
    
    def test_samsung_vendor(self):
        dtype, os_hint, model = infer_device_type("Samsung", None)
        assert dtype == DeviceType.PHONE
    
    def test_cisco_vendor(self):
        dtype, os_hint, model = infer_device_type("Cisco", None)
        assert dtype == DeviceType.ROUTER
    
    def test_service_based_inference(self):
        dtype, os_hint, model = infer_device_type(
            None, None, services=["_printer._tcp"]
        )
        assert dtype == DeviceType.PRINTER
