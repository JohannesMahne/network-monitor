"""Sparkline renderer for network monitoring graphs.

Provides fast, lightweight sparkline graph generation using PIL/Pillow
with matplotlib fallback.
"""

import hashlib
import io
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from config import STORAGE, get_logger

logger = get_logger(__name__)


def _get_appearance_mode() -> str:
    """Detect macOS appearance mode (dark or light).

    Returns:
        'dark' or 'light'
    """
    try:
        from AppKit import NSAppearance, NSAppearanceNameDarkAqua

        appearance = NSAppearance.currentAppearance()
        if appearance:
            appearance_name = appearance.name()
            if appearance_name == NSAppearanceNameDarkAqua:
                return "dark"
        return "light"
    except Exception:
        # Fallback to light mode if detection fails
        return "light"


def _get_appearance_colors(mode: str) -> Dict[str, str]:
    """Get color palette based on appearance mode.

    Args:
        mode: 'dark' or 'light'

    Returns:
        Dict mapping color names to hex values
    """
    if mode == "dark":
        # Dark mode: slightly brighter, more saturated colors for visibility
        return {
            "upload": "#4CD964",  # Brighter green
            "download": "#5AC8FA",  # Brighter blue
            "latency": "#FF9500",  # Orange (same)
            "quality": "#AF52DE",  # Purple (same)
            "total": "#FF2D55",  # Pink (same)
        }
    else:
        # Light mode: use existing colors
        from config import COLORS

        return {
            "upload": COLORS.UPLOAD_COLOR,
            "download": COLORS.DOWNLOAD_COLOR,
            "latency": COLORS.LATENCY_COLOR,
            "quality": COLORS.QUALITY_COLOR,
            "total": COLORS.TOTAL_COLOR,
        }


class SparklineRenderer:
    """Renders sparkline graphs for network monitoring data.

    Uses PIL/Pillow for fast rendering with matplotlib as fallback.
    Generates PNG images optimized for macOS menu bar display.
    """

    def __init__(self):
        """Initialize the sparkline renderer."""
        self._temp_dir = Path(tempfile.gettempdir()) / STORAGE.SPARKLINE_TEMP_DIR
        self._temp_dir.mkdir(exist_ok=True)
        self._last_appearance_mode: str = _get_appearance_mode()

    def create_image(
        self, values: List[float], color: str = "#007AFF", width: int = 120, height: int = 16
    ) -> str:
        """Generate a sparkline image and return path to PNG file.

        Uses PIL/Pillow for faster rendering and lower memory usage than matplotlib.
        Falls back to matplotlib if PIL rendering fails.

        Args:
            values: List of numeric values to graph
            color: Hex color string (e.g., '#007AFF')
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            Path to the generated PNG file
        """
        if not values or len(values) < 2:
            values = [0, 0]

        try:
            return self._create_pil(values, color, width, height)
        except Exception as e:
            logger.debug(f"PIL sparkline failed, falling back to matplotlib: {e}")
            return self._create_matplotlib(values, color, width, height)

    def _render_pil_image(
        self, values: List[float], color: str = "#007AFF", width: int = 120, height: int = 16
    ):
        """Render a sparkline PIL Image in memory (2x supersampled anti-aliasing)."""
        from PIL import Image, ImageDraw

        if not values or len(values) < 2:
            values = [0, 0]

        scale = 2
        scaled_width = width * scale
        scaled_height = height * scale

        img = Image.new("RGBA", (scaled_width, scaled_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if color.startswith("#") and len(color) == 7:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
        else:
            r, g, b = 0, 122, 255

        line_color = (r, g, b, 255)
        fill_color = (r, g, b, 50)

        padding_x = 4 * scale
        padding_y = 3 * scale
        graph_width = scaled_width - 2 * padding_x
        graph_height = scaled_height - 2 * padding_y

        max_val = max(values) if max(values) > 0 else 1
        min_val = min(values)
        val_range = max_val - min_val if max_val != min_val else 1

        interpolated = []
        for i in range(len(values) - 1):
            v1, v2 = values[i], values[i + 1]
            interpolated.append(v1)
            interpolated.append(v1 + (v2 - v1) * 0.5)
        interpolated.append(values[-1])

        points = []
        denom = max(1, len(interpolated) - 1)
        for i, val in enumerate(interpolated):
            x = padding_x + (i / denom) * graph_width
            normalized = (val - min_val) / val_range
            y = padding_y + (1 - normalized) * graph_height
            points.append((x, y))

        if len(points) >= 2:
            fill_points = list(points)
            fill_points.append((points[-1][0], scaled_height - padding_y))
            fill_points.append((points[0][0], scaled_height - padding_y))
            draw.polygon(fill_points, fill=fill_color)
            draw.line(points, fill=line_color, width=2 * scale)

        if points:
            last_x, last_y = points[-1]
            r_dot = 3 * scale
            draw.ellipse(
                [last_x - r_dot, last_y - r_dot, last_x + r_dot, last_y + r_dot], fill=line_color
            )

        return img.resize((width, height), Image.Resampling.LANCZOS)

    def create_png_bytes(
        self, values: List[float], color: str = "#007AFF", width: int = 120, height: int = 16
    ) -> Optional[bytes]:
        """Generate a sparkline PNG in memory (zero disk I/O, no temp files)."""
        try:
            img = self._render_pil_image(values, color, width, height)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.debug(f"In-memory PIL sparkline failed: {e}")
            return None

    def _create_pil(
        self, values: List[float], color: str = "#007AFF", width: int = 120, height: int = 16
    ) -> str:
        """Create sparkline using PIL/Pillow and write to a deterministic temp file."""
        img = self._render_pil_image(values, color, width, height)
        self._temp_dir.mkdir(exist_ok=True)
        img_path = self._temp_dir / f'spark_{color.replace("#", "")}.png'
        img.save(str(img_path), "PNG")
        return str(img_path)

    def _create_matplotlib(
        self, values: List[float], color: str = "#007AFF", width: int = 120, height: int = 16
    ) -> str:
        """Create sparkline using matplotlib - fallback for complex cases."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # Create figure with exact pixel dimensions
        dpi = 72
        fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)

        # Plot the line - thin and smooth
        ax.plot(values, color=color, linewidth=1.0, solid_capstyle="round")

        # Fill under the line with transparency
        ax.fill_between(range(len(values)), values, alpha=0.15, color=color)

        # Mark the last point
        if values:
            ax.plot(len(values) - 1, values[-1], "o", color=color, markersize=2)

        # Remove all axes and borders (pure sparkline)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Tight layout with no padding
        ax.margins(x=0.02, y=0.1)
        plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

        # Save to temp file
        # nosec B324 - MD5 used for cache key, not security
        val_hash = hashlib.md5(str(values).encode(), usedforsecurity=False).hexdigest()[:8]
        img_path = self._temp_dir / f'spark_{color.replace("#", "")}_{val_hash}.png'

        fig.savefig(img_path, transparent=True, dpi=dpi, pad_inches=0)
        plt.close(fig)

        return str(img_path)
