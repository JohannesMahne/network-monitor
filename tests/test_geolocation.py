"""Tests for monitor/geolocation.py - IP geolocation service."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from monitor.geolocation import GeolocationService


class TestGeolocationService:
    """Tests for GeolocationService class."""

    def test_init_creates_cache(self, tmp_path):
        """Test service initialization creates empty cache."""
        service = GeolocationService(data_dir=tmp_path)
        assert service._cache == {}
        assert service.data_dir == tmp_path

    def test_init_loads_existing_cache(self, tmp_path):
        """Test service loads existing cache from disk."""
        # Create a cache file
        cache_file = tmp_path / "geolocation_cache.json"
        cache_data = {
            "8.8.8.8": {"country_code": "US", "country": "United States", "timestamp": time.time()}
        }
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        service = GeolocationService(data_dir=tmp_path)

        assert "8.8.8.8" in service._cache
        assert service._cache["8.8.8.8"]["country_code"] == "US"

    def test_init_filters_expired_cache(self, tmp_path):
        """Test service filters expired cache entries."""
        cache_file = tmp_path / "geolocation_cache.json"
        old_timestamp = time.time() - (8 * 24 * 60 * 60)  # 8 days ago
        cache_data = {"8.8.8.8": {"country_code": "US", "timestamp": old_timestamp}}
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        service = GeolocationService(data_dir=tmp_path)

        assert "8.8.8.8" not in service._cache  # Expired

    def test_is_private_ip_10_range(self):
        """Test _is_private_ip for 10.x.x.x range."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("10.0.0.1") is True
        assert service._is_private_ip("10.255.255.255") is True

    def test_is_private_ip_192_168_range(self):
        """Test _is_private_ip for 192.168.x.x range."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("192.168.0.1") is True
        assert service._is_private_ip("192.168.255.255") is True

    def test_is_private_ip_172_range(self):
        """Test _is_private_ip for 172.16-31.x.x range."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("172.16.0.1") is True
        assert service._is_private_ip("172.31.255.255") is True
        assert service._is_private_ip("172.15.0.1") is False  # Not in range
        assert service._is_private_ip("172.32.0.1") is False  # Not in range

    def test_is_private_ip_loopback(self):
        """Test _is_private_ip for 127.x.x.x loopback."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("127.0.0.1") is True
        assert service._is_private_ip("127.255.255.255") is True

    def test_is_private_ip_link_local(self):
        """Test _is_private_ip for 169.254.x.x link-local."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("169.254.0.1") is True
        assert service._is_private_ip("169.254.255.255") is True

    def test_is_private_ip_public(self):
        """Test _is_private_ip returns False for public IPs."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("8.8.8.8") is False
        assert service._is_private_ip("1.1.1.1") is False
        assert service._is_private_ip("142.250.80.46") is False

    def test_is_private_ip_invalid(self):
        """Test _is_private_ip returns True for invalid IPs."""
        service = GeolocationService(data_dir=Path("/tmp"))
        service._cache = {}

        assert service._is_private_ip("not.an.ip") is True
        assert service._is_private_ip("") is True
        assert service._is_private_ip("1.2.3") is True  # Not enough octets

    def test_lookup_country_private_ip(self, tmp_path):
        """Test lookup_country returns None for private IPs."""
        service = GeolocationService(data_dir=tmp_path)

        result = service.lookup_country("192.168.1.1")

        assert result is None

    def test_lookup_country_empty_ip(self, tmp_path):
        """Test lookup_country returns None for empty IP."""
        service = GeolocationService(data_dir=tmp_path)

        result = service.lookup_country("")

        assert result is None

    def test_lookup_country_cached(self, tmp_path):
        """Test lookup_country uses cache."""
        service = GeolocationService(data_dir=tmp_path)
        service._cache["8.8.8.8"] = {"country_code": "US", "timestamp": time.time()}

        result = service.lookup_country("8.8.8.8")

        assert result == "US"

    def test_lookup_country_cache_expired(self, tmp_path):
        """Test lookup_country ignores expired cache."""
        service = GeolocationService(data_dir=tmp_path)
        old_timestamp = time.time() - (8 * 24 * 60 * 60)  # 8 days ago
        service._cache["8.8.8.8"] = {"country_code": "US", "timestamp": old_timestamp}

        # Mock API call - use full path to ensure we're patching the right thing
        with patch.object(service, "_save_cache"):  # Don't save during test
            with patch("monitor.geolocation.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = b'{"status": "success", "countryCode": "DE"}'
                mock_response.__enter__ = MagicMock(return_value=mock_response)
                mock_response.__exit__ = MagicMock(return_value=False)
                mock_urlopen.return_value = mock_response

                result = service.lookup_country("8.8.8.8")

        assert result == "DE"  # Fresh lookup, not cached value

    @patch("urllib.request.urlopen")
    def test_lookup_country_api_success(self, mock_urlopen, tmp_path):
        """Test lookup_country with successful API call."""
        service = GeolocationService(data_dir=tmp_path)

        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"status": "success", "countryCode": "US", "country": "United States"}'
        )
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = service.lookup_country("8.8.8.8")

        assert result == "US"
        assert "8.8.8.8" in service._cache

    def test_lookup_country_api_failure(self, tmp_path):
        """Test lookup_country handles API failure."""
        from urllib.error import URLError

        service = GeolocationService(data_dir=tmp_path)
        # Clear any cached entry
        service._cache.clear()

        with patch("monitor.geolocation.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = URLError("Connection refused")

            result = service.lookup_country("8.8.8.8")

        assert result is None

    def test_lookup_country_api_fail_status(self, tmp_path):
        """Test lookup_country handles API fail status."""
        service = GeolocationService(data_dir=tmp_path)
        # Clear any cached entry
        service._cache.clear()

        with patch("monitor.geolocation.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"status": "fail", "message": "private range"}'
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_response

            result = service.lookup_country("8.8.8.8")

        assert result is None

    def test_get_country_name_known(self, tmp_path):
        """Test get_country_name for known countries."""
        service = GeolocationService(data_dir=tmp_path)

        assert service.get_country_name("US") == "USA"
        assert service.get_country_name("GB") == "UK"
        assert service.get_country_name("DE") == "Germany"
        assert service.get_country_name("JP") == "Japan"

    def test_get_country_name_unknown(self, tmp_path):
        """Test get_country_name returns code for unknown countries."""
        service = GeolocationService(data_dir=tmp_path)

        assert service.get_country_name("ZZ") == "ZZ"
        assert service.get_country_name("XX") == "XX"

    def test_save_cache(self, tmp_path):
        """Test _save_cache writes to disk."""
        service = GeolocationService(data_dir=tmp_path)
        service._cache["8.8.8.8"] = {"country_code": "US", "timestamp": time.time()}

        service._save_cache()

        cache_file = tmp_path / "geolocation_cache.json"
        assert cache_file.exists()

        with open(cache_file) as f:
            data = json.load(f)
        assert "8.8.8.8" in data
