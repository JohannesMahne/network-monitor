"""Shared utility functions for network monitoring."""


def format_bytes(bytes_value: float, speed: bool = False) -> str:
    """Format bytes to human-readable string.
    
    Args:
        bytes_value: The number of bytes to format.
        speed: If True, append '/s' suffix for speed display.
    
    Returns:
        Human-readable string like "1.5 MB" or "1.5 MB/s".
    """
    if bytes_value == 0:
        suffix = "/s" if speed else ""
        return f"0 B{suffix}"
    
    suffix = "/s" if speed else ""
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(bytes_value) < 1024.0:
            return f"{bytes_value:.1f} {unit}{suffix}"
        bytes_value /= 1024.0
    return f"{bytes_value:.1f} PB{suffix}"
