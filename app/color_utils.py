"""
Color utilities for accent color theming.
"""

DEFAULT_ACCENT = "#2563eb"

PRESET_COLORS = [
    ("#2563eb", "Blue"),
    ("#1e3a8a", "Navy"),
    ("#7c3aed", "Purple"),
    ("#db2777", "Pink"),
    ("#dc2626", "Red"),
    ("#ea580c", "Orange"),
    ("#d97706", "Amber"),
    ("#16a34a", "Green"),
    ("#0891b2", "Cyan"),
    ("#0f766e", "Teal"),
    ("#475569", "Slate"),
    ("#111827", "Charcoal"),
]


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hex_color: str) -> float:
    """Relative luminance per WCAG 2.1."""
    rgb = [c / 255.0 for c in hex_to_rgb(hex_color)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def text_on_accent(hex_color: str) -> str:
    """Return '#ffffff' or '#111827' depending on which has better contrast."""
    lum = luminance(hex_color)
    white_contrast = (lum + 0.05) / (0.0 + 0.05)   # contrast vs black bg (approx)
    return "#ffffff" if lum < 0.35 else "#111827"


def accent_light(hex_color: str, factor: float = 0.85) -> str:
    """Return a lightened version of the accent for subtle backgrounds."""
    r, g, b = hex_to_rgb(hex_color)
    r2 = int(r + (255 - r) * factor)
    g2 = int(g + (255 - g) * factor)
    b2 = int(b + (255 - b) * factor)
    return f"#{r2:02x}{g2:02x}{b2:02x}"


def accent_dark(hex_color: str, factor: float = 0.7) -> str:
    """Return a darkened version of the accent."""
    r, g, b = hex_to_rgb(hex_color)
    return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"


def is_valid_hex(s: str) -> bool:
    s = s.strip().lstrip("#")
    return len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s)


def normalise(hex_color: str) -> str:
    """Ensure leading # and lowercase."""
    h = hex_color.strip().lstrip("#")
    return f"#{h.lower()}" if is_valid_hex(h) else DEFAULT_ACCENT