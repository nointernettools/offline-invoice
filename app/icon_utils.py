"""
app/icon_utils.py
Provides get_icon(name) by loading custom PNG assets from the icons/ directory.

"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtGui import QIcon

# Resolve the icons/ folder relative to this file, so it works regardless
# of the working directory the app is launched from.
_ICONS_DIR = Path(__file__).parent / "assets"


def get_icon(name: str) -> QIcon:
    """
    Return a QIcon loaded from assets/<name>.png.

    Usage:
        get_icon("send")        # loads assets/send.png
        get_icon("send.png")    # extension stripped automatically
        get_icon("customer-2")  # loads assets/customer-2.png

    Falls back to an empty QIcon if the file does not exist.
    """
    # Strip extension if accidentally passed with one
    key = name.rsplit(".", 1)[0].lower()
    path = _ICONS_DIR / f"{key}.png"

    if not path.exists():
        # Warn during development so missing icons are caught early
        import warnings
        warnings.warn(f"[icon_utils] Icon not found: {path}", stacklevel=2)
        return QIcon()

    return QIcon(str(path))