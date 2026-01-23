"""Tests for monitor/scanner.py"""



from monitor.scanner import (
    DeviceNameStore,
    DeviceType,
    NetworkDevice,
    NetworkScanner,
    OUIDatabase,
    infer_device_type,
    normalize_mac,
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

    def test_mixed_case(self):
        assert normalize_mac("aA:Bb:cC:Dd:eE:fF") == "AA:BB:CC:DD:EE:FF"


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

    def test_lookup_normalizes_mac(self):
        """Test that lookup normalizes MAC address."""
        db = OUIDatabase()
        # Should work with different formats
        result1 = db.lookup("aa:bb:cc:11:22:33")
        result2 = db.lookup("AA:BB:CC:11:22:33")
        # Results should be the same
        assert result1 == result2


class TestNetworkDevice:
    """Tests for the NetworkDevice dataclass."""

    def test_display_name_with_custom_name(self):
        device = NetworkDevice(
            ip_address="192.168.1.100", mac_address="AA:BB:CC:DD:EE:FF", custom_name="My iPhone"
        )
        assert device.display_name == "My iPhone"

    def test_display_name_with_mdns_name(self):
        device = NetworkDevice(
            ip_address="192.168.1.100", mac_address="AA:BB:CC:DD:EE:FF", mdns_name="Johns-MacBook"
        )
        assert device.display_name == "Johns-MacBook"

    def test_display_name_with_model_hint(self):
        device = NetworkDevice(
            ip_address="192.168.1.100", mac_address="AA:BB:CC:DD:EE:FF", model_hint="MacBook Pro"
        )
        assert device.display_name == "MacBook Pro"

    def test_display_name_with_hostname(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            hostname="johns-macbook.local",
        )
        assert device.display_name == "johns-macbook"

    def test_display_name_with_vendor(self):
        device = NetworkDevice(
            ip_address="192.168.1.100", mac_address="AA:BB:CC:DD:EE:FF", vendor="Samsung"
        )
        assert device.display_name == "Samsung"

    def test_display_name_fallback_to_ip(self):
        device = NetworkDevice(ip_address="192.168.1.100", mac_address="AA:BB:CC:DD:EE:FF")
        assert device.display_name == "192.168.1.100"

    def test_type_icon(self):
        device = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            device_type=DeviceType.PHONE,
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
        dtype, os_hint, model = infer_device_type(None, None, services=["_printer._tcp"])
        assert dtype == DeviceType.PRINTER

    def test_roku_hostname(self):
        """Test inferring Roku device."""
        dtype, os_hint, model = infer_device_type(None, "Roku-Ultra")
        assert dtype == DeviceType.TV

    def test_ps5_hostname(self):
        """Test inferring PlayStation."""
        dtype, os_hint, model = infer_device_type(None, "PS5-Gaming")
        assert dtype == DeviceType.GAMING

    def test_xbox_hostname(self):
        """Test inferring Xbox."""
        dtype, os_hint, model = infer_device_type(None, "XboxOne")
        assert dtype == DeviceType.GAMING

    def test_sonos_vendor(self):
        """Test inferring Sonos speaker."""
        dtype, os_hint, model = infer_device_type("Sonos", None)
        assert dtype == DeviceType.SPEAKER

    def test_esp_vendor(self):
        """Test inferring ESP IoT device."""
        dtype, os_hint, model = infer_device_type("Espressif", None)
        assert dtype == DeviceType.IOT


class TestDeviceNameStore:
    """Tests for device name persistence."""

    def test_singleton(self):
        """Test that DeviceNameStore is a singleton."""
        store1 = DeviceNameStore()
        store2 = DeviceNameStore()
        assert store1 is store2

    def test_set_and_get_name(self):
        """Test setting and getting device names."""
        store = DeviceNameStore()
        test_mac = "FF:EE:DD:CC:BB:AA"  # Unlikely to conflict

        store.set_name(test_mac, "Test Device 123")
        assert store.get_name(test_mac) == "Test Device 123"

        # Clean up
        store._names.pop(test_mac, None)

    def test_get_nonexistent_name(self):
        """Test getting name for unknown device."""
        store = DeviceNameStore()
        assert store.get_name("00:00:00:00:00:01") is None


class TestNetworkScanner:
    """Tests for the NetworkScanner class."""

    def test_init(self):
        """Test scanner initialization."""
        scanner = NetworkScanner()
        assert scanner is not None
        assert isinstance(scanner._devices, dict)

    def test_set_and_get_device_name(self):
        """Test setting and getting a device name."""
        scanner = NetworkScanner()
        mac = "FF:00:FF:00:FF:00"  # Use unique MAC

        # Set name via scanner (which uses the name store)
        scanner.set_device_name(mac, "Test Device Sprint10")

        # Now get it back
        name = scanner.get_device_name(mac)
        assert name == "Test Device Sprint10"

        # Clean up - remove from store
        scanner._name_store._names.pop(mac, None)

    def test_get_all_devices(self):
        """Test getting all devices."""
        scanner = NetworkScanner()
        initial_count = len(scanner._devices)

        scanner._devices["AA:BB:CC:DD:EE:01"] = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:01",
        )
        scanner._devices["11:22:33:44:55:01"] = NetworkDevice(
            ip_address="192.168.1.101",
            mac_address="11:22:33:44:55:01",
        )

        devices = scanner.get_all_devices()
        assert len(devices) >= initial_count + 2

    def test_get_online_devices(self):
        """Test getting only online devices."""
        scanner = NetworkScanner()

        scanner._devices["AA:BB:CC:DD:EE:02"] = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:02",
            is_online=True,
        )
        scanner._devices["11:22:33:44:55:02"] = NetworkDevice(
            ip_address="192.168.1.101",
            mac_address="11:22:33:44:55:02",
            is_online=False,
        )

        online = scanner.get_online_devices()
        # At least our online device should be there
        online_macs = [d.mac_address for d in online]
        assert "AA:BB:CC:DD:EE:02" in online_macs
        assert "11:22:33:44:55:02" not in online_macs

    def test_get_device_count(self):
        """Test getting device counts."""
        scanner = NetworkScanner()

        scanner._devices["AA:BB:CC:DD:EE:03"] = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:03",
            is_online=True,
        )
        scanner._devices["11:22:33:44:55:03"] = NetworkDevice(
            ip_address="192.168.1.101",
            mac_address="11:22:33:44:55:03",
            is_online=False,
        )

        online, total = scanner.get_device_count()
        assert total >= 2
        assert online >= 1

    def test_scan_returns_devices(self):
        """Test that scan returns a list."""
        scanner = NetworkScanner()
        # Just verify scan doesn't crash and returns a list
        devices = scanner.scan(force=True, quick=True)
        assert isinstance(devices, list)

    def test_devices_returned_as_list(self):
        """Test that get_all_devices returns a list."""
        scanner = NetworkScanner()

        scanner._devices["AA:AA:AA:AA:AA:04"] = NetworkDevice(
            ip_address="192.168.1.200",
            mac_address="AA:AA:AA:AA:AA:04",
        )
        scanner._devices["BB:BB:BB:BB:BB:04"] = NetworkDevice(
            ip_address="192.168.1.50",
            mac_address="BB:BB:BB:BB:BB:04",
        )

        devices = scanner.get_all_devices()
        assert isinstance(devices, list)
        # Should include our added devices
        macs = [d.mac_address for d in devices]
        assert "AA:AA:AA:AA:AA:04" in macs
        assert "BB:BB:BB:BB:BB:04" in macs


class TestDeviceEquality:
    """Tests for device equality and hashing."""

    def test_devices_equal_by_mac(self):
        """Test that devices are equal if MAC matches."""
        d1 = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
            hostname="device1",
        )
        d2 = NetworkDevice(
            ip_address="192.168.1.200",
            mac_address="AA:BB:CC:DD:EE:FF",
            hostname="device2",
        )
        assert d1 == d2

    def test_devices_not_equal_different_mac(self):
        """Test that devices with different MACs are not equal."""
        d1 = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
        )
        d2 = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="11:22:33:44:55:66",
        )
        assert d1 != d2

    def test_device_hashable(self):
        """Test that devices can be used in sets."""
        d1 = NetworkDevice(
            ip_address="192.168.1.100",
            mac_address="AA:BB:CC:DD:EE:FF",
        )
        d2 = NetworkDevice(
            ip_address="192.168.1.200",
            mac_address="AA:BB:CC:DD:EE:FF",
        )

        device_set = {d1, d2}
        assert len(device_set) == 1  # Same MAC, so should be deduplicated
