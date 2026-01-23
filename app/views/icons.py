"""Icon generation for Network Monitor.

Handles creation of status icons, gauge icons, and sparkline graphs.
All icons are cached to reduce CPU usage.

Usage:
    from app.views.icons import IconGenerator
    
    icons = IconGenerator()
    path = icons.create_gauge("green")
    sparkline_path = icons.create_sparkline([1, 2, 3, 4, 5], "#007AFF")
"""
import hashlib
import math
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from config import COLORS, STORAGE, UI, get_logger

logger = get_logger(__name__)


class IconGenerator:
    """Generates and caches icons for the menu bar application.
    
    Maintains a cache of generated icons to avoid regenerating
    the same icon multiple times.
    """

    def __init__(self):
        self._temp_dir = Path(tempfile.gettempdir()) / STORAGE.ICON_TEMP_DIR
        self._temp_dir.mkdir(exist_ok=True)
        self._sparkline_dir = Path(tempfile.gettempdir()) / STORAGE.SPARKLINE_TEMP_DIR
        self._sparkline_dir.mkdir(exist_ok=True)
        self._cache: Dict[str, str] = {}
        logger.debug(f"IconGenerator initialized, temp dir: {self._temp_dir}")

    def _get_color_rgba(self, color: str) -> Tuple[int, int, int, int]:
        """Get RGBA tuple for a color name."""
        color_map = {
            'green': COLORS.GREEN_RGBA,
            'yellow': COLORS.YELLOW_RGBA,
            'red': COLORS.RED_RGBA,
            'gray': COLORS.GRAY_RGBA,
            'blue': COLORS.BLUE_RGBA,
        }
        return color_map.get(color, COLORS.GRAY_RGBA)

    def _get_color_hex(self, color: str) -> str:
        """Get hex color string for a color name."""
        color_map = {
            'green': COLORS.GREEN_HEX,
            'yellow': COLORS.YELLOW_HEX,
            'red': COLORS.RED_HEX,
            'gray': COLORS.GRAY_HEX,
            'blue': COLORS.BLUE_HEX,
        }
        return color_map.get(color, COLORS.GRAY_HEX)

    def create_status_icon(self, color: str, size: int = None) -> str:
        """Create a colored circle icon for status display.
        
        Args:
            color: Color name ('green', 'yellow', 'red', 'gray').
            size: Icon size in pixels (default from UI config).
        
        Returns:
            Path to the generated PNG file.
        """
        size = size or UI.STATUS_ICON_SIZE
        cache_key = f"status_{color}_{size}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        fill_color = self._get_color_rgba(color)

        # Draw filled circle with slight padding
        padding = 2
        draw.ellipse(
            [padding, padding, size - padding, size - padding],
            fill=fill_color
        )

        icon_path = self._temp_dir / f'status_{color}_{size}.png'
        img.save(icon_path, 'PNG')

        self._cache[cache_key] = str(icon_path)
        return str(icon_path)

    def create_gauge_icon(self, color: str, size: int = None) -> str:
        """Create a gauge/speedometer icon colored by status.
        
        The gauge needle points right for good, up for OK, left for poor.
        
        Args:
            color: Color name ('green', 'yellow', 'red', 'gray').
            size: Icon size in pixels (default from UI config).
        
        Returns:
            Path to the generated PNG file.
        """
        size = size or UI.STATUS_ICON_SIZE
        cache_key = f"gauge_{color}_{size}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        fill_color = self._get_color_hex(color)

        # Create image with transparency
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Draw gauge arc (speedometer shape)
        padding = 2
        bbox = [padding, padding + 2, size - padding, size - padding + 2]

        # Draw the gauge arc (semi-circle at top)
        draw.arc(bbox, start=180, end=0, fill=fill_color, width=2)

        # Draw needle based on color (status)
        center_x = size // 2
        center_y = size // 2 + 2
        needle_len = size // 2 - 4

        # Needle angle: green=45° (right), yellow=90° (up), red=135° (left)
        if color == "green":
            angle = math.radians(45)
        elif color == "yellow":
            angle = math.radians(90)
        else:
            angle = math.radians(135)

        needle_x = center_x + int(needle_len * math.cos(math.pi - angle))
        needle_y = center_y - int(needle_len * math.sin(math.pi - angle))

        draw.line([(center_x, center_y), (needle_x, needle_y)], fill=fill_color, width=2)

        # Draw center dot
        dot_r = 2
        draw.ellipse(
            [center_x - dot_r, center_y - dot_r, center_x + dot_r, center_y + dot_r],
            fill=fill_color
        )

        icon_path = self._temp_dir / f'gauge_{color}_{size}.png'
        img.save(str(icon_path), 'PNG')

        self._cache[cache_key] = str(icon_path)
        return str(icon_path)

    def create_sparkline(
        self,
        values: List[float],
        color: str = None,
        width: int = None,
        height: int = None,
        use_matplotlib: bool = True
    ) -> str:
        """Create a sparkline graph image.
        
        Args:
            values: List of numeric values to plot.
            color: Hex color string (e.g., '#007AFF') or color name.
            width: Image width in pixels.
            height: Image height in pixels.
            use_matplotlib: If True, use matplotlib for smoother lines.
        
        Returns:
            Path to the generated PNG file.
        """
        width = width or UI.SPARKLINE_WIDTH
        height = height or UI.SPARKLINE_HEIGHT

        # Resolve color
        if color is None:
            color = COLORS.BLUE_HEX
        elif not color.startswith('#'):
            color = self._get_color_hex(color)

        # Create cache key from values hash
        # nosec B324 - MD5 used for cache key, not security
        val_hash = hashlib.md5(str(values).encode(), usedforsecurity=False).hexdigest()[:8]
        cache_key = f"spark_{color.replace('#', '')}_{val_hash}"

        if cache_key in self._cache:
            return self._cache[cache_key]

        if use_matplotlib:
            path = self._create_sparkline_matplotlib(values, color, width, height, cache_key)
        else:
            path = self._create_sparkline_pil(values, color, width, height, cache_key)

        self._cache[cache_key] = path
        return path

    def _create_sparkline_pil(
        self,
        values: List[float],
        color: str,
        width: int,
        height: int,
        cache_key: str
    ) -> str:
        """Create sparkline using PIL only (faster, simpler)."""
        if not values or len(values) < 2:
            values = [0, 0]

        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Normalize values
        min_val = min(values)
        max_val = max(values)
        if max_val == min_val:
            max_val = min_val + 1

        # Convert hex color to RGB
        hex_color = color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

        # Calculate points
        points = []
        for i, v in enumerate(values):
            x = int(i * (width - 1) / (len(values) - 1))
            y = int(height - 1 - (v - min_val) / (max_val - min_val) * (height - 2))
            points.append((x, y))

        # Draw line
        if len(points) >= 2:
            draw.line(points, fill=rgb + (255,), width=1)

        # Draw end dot
        if points:
            x, y = points[-1]
            draw.ellipse([x-2, y-2, x+2, y+2], fill=rgb + (255,))

        img_path = self._sparkline_dir / f'{cache_key}.png'
        img.save(img_path, 'PNG')

        return str(img_path)

    def _create_sparkline_matplotlib(
        self,
        values: List[float],
        color: str,
        width: int,
        height: int,
        cache_key: str
    ) -> str:
        """Create sparkline using matplotlib (smoother)."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        if not values or len(values) < 2:
            values = [0, 0]

        # Create figure with exact pixel dimensions
        dpi = 72
        fig, ax = plt.subplots(figsize=(width/dpi, height/dpi), dpi=dpi)

        # Plot the line - thin and smooth
        ax.plot(values, color=color, linewidth=1.0, solid_capstyle='round')

        # Fill under the line with transparency
        ax.fill_between(range(len(values)), values, alpha=0.15, color=color)

        # Mark the last point
        if values:
            ax.plot(len(values)-1, values[-1], 'o', color=color, markersize=2)

        # Remove all axes and borders (pure sparkline)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Tight layout with no padding
        ax.margins(x=0.02, y=0.1)
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

        img_path = self._sparkline_dir / f'{cache_key}.png'
        fig.savefig(img_path, transparent=True, dpi=dpi, pad_inches=0)
        plt.close(fig)

        return str(img_path)

    def cleanup(self) -> None:
        """Clean up temporary icon files."""
        import shutil

        for temp_dir in [self._temp_dir, self._sparkline_dir]:
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                    temp_dir.mkdir(exist_ok=True)
            except Exception as e:
                logger.warning(f"Could not clean up {temp_dir}: {e}")

        self._cache.clear()
        logger.debug("Icon cache cleared")

    def cleanup_old_sparklines(self, max_age_seconds: int = None) -> None:
        """Remove sparkline images older than max age."""
        import time

        max_age = max_age_seconds or STORAGE.SPARKLINE_MAX_AGE_SECONDS
        cutoff = time.time() - max_age

        try:
            for file in self._sparkline_dir.glob('*.png'):
                if file.stat().st_mtime < cutoff:
                    file.unlink()
                    # Also remove from cache
                    cache_key = file.stem
                    self._cache.pop(cache_key, None)
        except Exception as e:
            logger.debug(f"Sparkline cleanup error: {e}")


# Module-level convenience functions
_default_generator: Optional[IconGenerator] = None


def get_icon_generator() -> IconGenerator:
    """Get or create the default icon generator."""
    global _default_generator
    if _default_generator is None:
        _default_generator = IconGenerator()
    return _default_generator


def create_status_icon(color: str, size: int = None) -> str:
    """Create a status icon using the default generator."""
    return get_icon_generator().create_status_icon(color, size)


def create_gauge_icon(color: str, size: int = None) -> str:
    """Create a gauge icon using the default generator."""
    return get_icon_generator().create_gauge_icon(color, size)


def create_sparkline(values: List[float], color: str = None, **kwargs) -> str:
    """Create a sparkline using the default generator."""
    return get_icon_generator().create_sparkline(values, color, **kwargs)
