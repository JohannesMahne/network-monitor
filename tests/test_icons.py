"""Tests for icon generation."""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.views.icons import IconGenerator, get_icon_generator, create_status_icon


class TestIconGenerator:
    """Tests for IconGenerator class."""

    @pytest.fixture
    def icon_gen(self):
        """Create an IconGenerator instance."""
        return IconGenerator()

    def test_init_creates_temp_dir(self, icon_gen):
        """Test that initialization creates temp directories."""
        assert icon_gen._temp_dir.exists()
        assert icon_gen._sparkline_dir.exists()

    def test_get_color_rgba_green(self, icon_gen):
        """Test getting RGBA for green."""
        color = icon_gen._get_color_rgba("green")
        assert len(color) == 4
        # Green should have higher G value
        assert color[1] > color[0]  # G > R

    def test_get_color_rgba_invalid(self, icon_gen):
        """Test getting RGBA for invalid color defaults to gray."""
        color = icon_gen._get_color_rgba("invalid")
        assert color == icon_gen._get_color_rgba("gray")

    def test_get_color_hex_green(self, icon_gen):
        """Test getting hex for green."""
        color = icon_gen._get_color_hex("green")
        assert color.startswith("#")
        assert len(color) == 7

    def test_create_status_icon(self, icon_gen):
        """Test creating a status icon."""
        path = icon_gen.create_status_icon("green")
        
        assert Path(path).exists()
        assert path.endswith(".png")

    def test_create_status_icon_cached(self, icon_gen):
        """Test that status icons are cached."""
        path1 = icon_gen.create_status_icon("green", size=22)
        path2 = icon_gen.create_status_icon("green", size=22)
        
        assert path1 == path2

    def test_create_status_icon_different_colors(self, icon_gen):
        """Test creating status icons with different colors."""
        green_path = icon_gen.create_status_icon("green")
        red_path = icon_gen.create_status_icon("red")
        
        assert green_path != red_path
        assert Path(green_path).exists()
        assert Path(red_path).exists()

    def test_create_gauge_icon(self, icon_gen):
        """Test creating a gauge icon."""
        path = icon_gen.create_gauge_icon("green")
        
        assert Path(path).exists()
        assert path.endswith(".png")

    def test_create_gauge_icon_cached(self, icon_gen):
        """Test that gauge icons are cached."""
        path1 = icon_gen.create_gauge_icon("yellow")
        path2 = icon_gen.create_gauge_icon("yellow")
        
        assert path1 == path2

    def test_create_sparkline(self, icon_gen):
        """Test creating a sparkline graph."""
        values = [1, 2, 3, 4, 5, 4, 3, 2, 1]
        path = icon_gen.create_sparkline(values)
        
        assert Path(path).exists()
        assert path.endswith(".png")

    def test_create_sparkline_cached(self, icon_gen):
        """Test that sparklines with same values are cached."""
        values = [1, 2, 3, 4, 5]
        path1 = icon_gen.create_sparkline(values)
        path2 = icon_gen.create_sparkline(values)
        
        assert path1 == path2

    def test_create_sparkline_different_values(self, icon_gen):
        """Test that different values create different sparklines."""
        path1 = icon_gen.create_sparkline([1, 2, 3])
        path2 = icon_gen.create_sparkline([3, 2, 1])
        
        # Hashes will differ
        assert path1 != path2

    def test_create_sparkline_with_color(self, icon_gen):
        """Test creating a sparkline with custom color."""
        path = icon_gen.create_sparkline([1, 2, 3], color="#FF0000")
        
        assert Path(path).exists()

    def test_create_sparkline_pil_fallback(self, icon_gen):
        """Test creating sparkline using PIL only."""
        values = [1, 2, 3, 4, 5]
        path = icon_gen.create_sparkline(values, use_matplotlib=False)
        
        assert Path(path).exists()

    def test_create_sparkline_empty_values(self, icon_gen):
        """Test creating sparkline with empty values."""
        path = icon_gen.create_sparkline([])
        
        assert Path(path).exists()

    def test_create_sparkline_single_value(self, icon_gen):
        """Test creating sparkline with single value."""
        path = icon_gen.create_sparkline([5])
        
        assert Path(path).exists()

    def test_cleanup(self, icon_gen):
        """Test cleanup removes cached files."""
        # Create some icons
        icon_gen.create_status_icon("green")
        icon_gen.create_sparkline([1, 2, 3])
        
        # Cleanup
        icon_gen.cleanup()
        
        assert icon_gen._cache == {}

    def test_cleanup_old_sparklines(self, icon_gen):
        """Test cleanup of old sparklines."""
        # Create a sparkline
        path = icon_gen.create_sparkline([1, 2, 3])
        
        # Cleanup with very short max age
        icon_gen.cleanup_old_sparklines(max_age_seconds=0)
        
        # File should be removed
        assert not Path(path).exists() or path not in icon_gen._cache


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_icon_generator_singleton(self):
        """Test that get_icon_generator returns same instance."""
        gen1 = get_icon_generator()
        gen2 = get_icon_generator()
        
        assert gen1 is gen2

    def test_create_status_icon_function(self):
        """Test the module-level create_status_icon function."""
        path = create_status_icon("blue")
        
        assert Path(path).exists()


class TestIconSizes:
    """Tests for different icon sizes."""

    @pytest.fixture
    def icon_gen(self):
        """Create an IconGenerator instance."""
        return IconGenerator()

    def test_status_icon_custom_size(self, icon_gen):
        """Test creating status icon with custom size."""
        path = icon_gen.create_status_icon("green", size=32)
        
        assert Path(path).exists()
        # Check if size is in filename
        assert "32" in path

    def test_gauge_icon_custom_size(self, icon_gen):
        """Test creating gauge icon with custom size."""
        path = icon_gen.create_gauge_icon("red", size=48)
        
        assert Path(path).exists()
        assert "48" in path


class TestSparklineRendering:
    """Tests for sparkline rendering specifics."""

    @pytest.fixture
    def icon_gen(self):
        """Create an IconGenerator instance."""
        return IconGenerator()

    def test_sparkline_matplotlib(self, icon_gen):
        """Test matplotlib sparkline rendering."""
        values = [10, 20, 15, 25, 30, 20, 10]
        path = icon_gen.create_sparkline(values, use_matplotlib=True)
        
        assert Path(path).exists()

    def test_sparkline_pil(self, icon_gen):
        """Test PIL sparkline rendering."""
        values = [10, 20, 15, 25, 30, 20, 10]
        path = icon_gen.create_sparkline(values, use_matplotlib=False)
        
        assert Path(path).exists()

    def test_sparkline_custom_dimensions(self, icon_gen):
        """Test sparkline with custom dimensions."""
        values = [1, 2, 3, 4, 5]
        path = icon_gen.create_sparkline(
            values,
            width=100,
            height=30,
            use_matplotlib=False
        )
        
        assert Path(path).exists()

    def test_sparkline_flat_values(self, icon_gen):
        """Test sparkline with all same values."""
        values = [5, 5, 5, 5, 5]
        path = icon_gen.create_sparkline(values)
        
        assert Path(path).exists()
