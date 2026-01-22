#!/usr/bin/env python3
"""
Generate the Network Monitor app icon.
Creates a .icns file for macOS application bundle.
"""
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

# Icon sizes required for macOS icns
ICON_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def create_network_icon(size: int) -> Image.Image:
    """Create a network monitor icon at the specified size."""
    # Create high-res canvas (2x for antialiasing)
    scale = 2
    canvas_size = size * scale
    img = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Colors - teal/cyan network theme
    bg_color = (20, 184, 166)  # Teal
    accent_color = (255, 255, 255)  # White
    shadow_color = (17, 153, 138)  # Darker teal
    
    # Draw rounded rectangle background
    padding = canvas_size * 0.1
    corner_radius = canvas_size * 0.22
    
    # Background with slight shadow effect
    draw.rounded_rectangle(
        [padding + 4, padding + 4, canvas_size - padding + 4, canvas_size - padding + 4],
        radius=corner_radius,
        fill=(0, 0, 0, 40)
    )
    draw.rounded_rectangle(
        [padding, padding, canvas_size - padding, canvas_size - padding],
        radius=corner_radius,
        fill=bg_color
    )
    
    # Draw network signal waves (WiFi-like arcs)
    center_x = canvas_size // 2
    center_y = canvas_size * 0.55
    
    # Draw three arcs
    arc_widths = [canvas_size * 0.15, canvas_size * 0.28, canvas_size * 0.41]
    for i, width in enumerate(arc_widths):
        arc_bbox = [
            center_x - width,
            center_y - width,
            center_x + width,
            center_y + width
        ]
        # Draw arc (top portion only)
        draw.arc(arc_bbox, start=225, end=315, fill=accent_color, width=max(3, int(canvas_size * 0.035)))
    
    # Draw center dot
    dot_radius = canvas_size * 0.045
    draw.ellipse(
        [center_x - dot_radius, center_y - dot_radius,
         center_x + dot_radius, center_y + dot_radius],
        fill=accent_color
    )
    
    # Draw speed arrows (up and down)
    arrow_y_up = canvas_size * 0.25
    arrow_y_down = canvas_size * 0.75
    arrow_x_left = canvas_size * 0.25
    arrow_x_right = canvas_size * 0.75
    arrow_size = canvas_size * 0.08
    
    # Up arrow (left side)
    up_points = [
        (arrow_x_left, arrow_y_up + arrow_size),
        (arrow_x_left - arrow_size * 0.6, arrow_y_up + arrow_size),
        (arrow_x_left, arrow_y_up - arrow_size * 0.3),
        (arrow_x_left + arrow_size * 0.6, arrow_y_up + arrow_size),
        (arrow_x_left, arrow_y_up + arrow_size),
    ]
    draw.polygon(up_points, fill=accent_color)
    
    # Down arrow (right side)
    down_points = [
        (arrow_x_right, arrow_y_down - arrow_size),
        (arrow_x_right - arrow_size * 0.6, arrow_y_down - arrow_size),
        (arrow_x_right, arrow_y_down + arrow_size * 0.3),
        (arrow_x_right + arrow_size * 0.6, arrow_y_down - arrow_size),
        (arrow_x_right, arrow_y_down - arrow_size),
    ]
    draw.polygon(down_points, fill=accent_color)
    
    # Resize down with high-quality antialiasing
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    
    return img


def create_iconset(output_dir: Path):
    """Create all icon sizes for the iconset."""
    iconset_dir = output_dir / "NetworkMonitor.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)
    
    for size in ICON_SIZES:
        # Standard resolution
        icon = create_network_icon(size)
        icon.save(iconset_dir / f"icon_{size}x{size}.png")
        
        # Retina resolution (2x) for sizes up to 512
        if size <= 512:
            icon_2x = create_network_icon(size * 2)
            icon_2x.save(iconset_dir / f"icon_{size}x{size}@2x.png")
    
    return iconset_dir


def create_icns(iconset_dir: Path, output_path: Path):
    """Convert iconset to icns using iconutil."""
    try:
        subprocess.run(
            ['iconutil', '-c', 'icns', str(iconset_dir), '-o', str(output_path)],
            check=True,
            capture_output=True
        )
        print(f"Created: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error creating icns: {e.stderr.decode()}")
        raise


def main():
    # Determine output path
    script_dir = Path(__file__).parent.parent
    assets_dir = script_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    
    output_path = assets_dir / "NetworkMonitor.icns"
    
    # Create iconset in temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        iconset_dir = create_iconset(tmpdir)
        create_icns(iconset_dir, output_path)
    
    print(f"Icon created successfully: {output_path}")
    
    # Also save a PNG preview
    preview = create_network_icon(512)
    preview_path = assets_dir / "icon_preview.png"
    preview.save(preview_path)
    print(f"Preview saved: {preview_path}")


if __name__ == '__main__':
    main()
