"""
app/font_cache.py  (PySide6 version)

The old CTkFont cache is no longer needed — all typography is handled by
the global QSS stylesheet in app/ui.py (_build_qss).

This module is kept as a no-op stub so any file that still imports F
doesn't break during the transition.  Nothing here is used at runtime;
the import resolves cleanly and silently.

If you ever need a QFont object directly (e.g. for a QLabel.setFont call),
create it inline:
    from PySide6.QtGui import QFont
    f = QFont(); f.setPointSize(13); f.setBold(True)
"""

# Empty stub — intentionally nothing here.
# All font styling is handled via the stylesheet in app/ui.py.