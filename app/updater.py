"""
app/updater.py
Checks GitHub Releases for a newer version of Offline Invoice.
Runs in a background thread — never blocks the UI.

Usage (call once at startup from MainWindow):
    from app.updater import check_for_update
    check_for_update(APP_VERSION, parent_widget)

How to publish a release:
    1. Push a tag:  git tag v1.0.1 && git push origin v1.0.1
    2. Create a GitHub Release on that tag — the checker will find it automatically.
    3. Upload the new .exe / installer as a release asset.

Set GITHUB_REPO below to your own "owner/repo" string.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import URLError

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
GITHUB_REPO    = "your-username/offline-invoice"   # ← change this
RELEASES_URL   = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE  = f"https://github.com/{GITHUB_REPO}/releases/latest"
REQUEST_TIMEOUT = 8   # seconds


# ── Version comparison ────────────────────────────────────────────────────────

def _parse(v: str) -> tuple[int, ...]:
    """Turn '1.2.3' or 'v1.2.3' into (1, 2, 3)."""
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def _is_newer(remote: str, local: str) -> bool:
    try:
        return _parse(remote) > _parse(local)
    except Exception:
        return False


# ── Background signal bridge ──────────────────────────────────────────────────

class _UpdateSignal(QObject):
    found = Signal(str, str)   # (latest_version, download_url)


# ── Update dialog ─────────────────────────────────────────────────────────────

ACCENT = "#2563EB"


class UpdateDialog(QDialog):
    """Clean, non-blocking update notification dialog."""

    def __init__(self, current: str, latest: str,
                 download_url: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setFixedWidth(420)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._download_url = download_url
        self._build(current, latest)

        if parent:
            px = parent.x() + (parent.width()  - self.width())  // 2
            py = parent.y() + (parent.height() - self.height()) // 2
            self.move(px, py)

    def _build(self, current: str, latest: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(24, 18, 24, 18); hl.setSpacing(4)

        title = QLabel("🎉  Update Available")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color:white; font-size:15px; font-weight:700;"
            " background:transparent;")
        hl.addWidget(title)
        root.addWidget(hdr)

        # Body
        body = QWidget(); body.setStyleSheet("background:white;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(28, 20, 28, 8); bl.setSpacing(8)

        def _row(label: str, value: str):
            w = QWidget(); w.setStyleSheet("background:transparent;")
            wl = QHBoxLayout(w)
            wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(8)
            lbl = QLabel(label)
            lbl.setFixedWidth(100)
            lbl.setStyleSheet(
                "font-size:12px; color:#9ca3af; background:transparent;")
            val = QLabel(value)
            val.setStyleSheet(
                "font-size:12px; font-weight:700; color:#111827;"
                " background:transparent;")
            wl.addWidget(lbl); wl.addWidget(val); wl.addStretch()
            bl.addWidget(w)

        _row("Current version:", f"v{current}")
        _row("Latest version:", f"v{latest}")

        info = QLabel(
            "A new version of Offline Invoice is available.\n"
            "Download it from GitHub to get the latest features and fixes.")
        info.setWordWrap(True)
        info.setStyleSheet(
            "font-size:12px; color:#6b7280; background:transparent;"
            " padding-top:8px;")
        bl.addWidget(info)
        root.addWidget(body)

        # Footer
        foot = QFrame()
        foot.setStyleSheet(
            "background:white; border-top:1px solid #f3f4f6;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 10, 24, 16); fl.setSpacing(8)

        skip_btn = QPushButton("Skip for Now")
        skip_btn.setFixedSize(130, 34)
        skip_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#f9fafb;}")
        skip_btn.clicked.connect(self.reject)
        fl.addWidget(skip_btn)
        fl.addStretch()

        dl_btn = QPushButton("Download Update  →")
        dl_btn.setFixedSize(180, 34)
        dl_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT}; color:white; border:none;"
            f" border-radius:6px; font-weight:600;}}"
            f"QPushButton:hover{{background:#1d4ed8;}}"
            f"QPushButton:pressed{{background:#1e3a8a;}}")
        dl_btn.clicked.connect(self._open_download)
        fl.addWidget(dl_btn)
        root.addWidget(foot)

    def _open_download(self):
        url = self._download_url or RELEASES_PAGE
        try:
            if sys.platform == "win32":
                os.startfile(url)
            elif sys.platform == "darwin":
                subprocess.run(["open", url], check=False)
            else:
                subprocess.run(["xdg-open", url], check=False)
        except Exception as exc:
            log.warning("Could not open browser: %s", exc)
        self.accept()


# ── Public entry point ────────────────────────────────────────────────────────

def check_for_update(current_version: str, parent: QWidget) -> None:
    """
    Spawn a daemon thread that hits the GitHub API.
    If a newer release is found, emit a signal that shows UpdateDialog
    on the main thread — completely non-blocking.
    """
    bridge = _UpdateSignal()

    def _show(latest_ver: str, dl_url: str):
        dlg = UpdateDialog(current_version, latest_ver, dl_url, parent)
        dlg.exec()

    bridge.found.connect(_show, Qt.QueuedConnection)

    def _worker():
        try:
            req = Request(
                RELEASES_URL,
                headers={"Accept": "application/vnd.github+json",
                         "User-Agent": "offline-invoice-updater"})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())

            latest_tag = data.get("tag_name", "")
            if not latest_tag:
                return

            # Find the first .exe asset, fall back to releases page
            assets    = data.get("assets", [])
            dl_url    = next(
                (a["browser_download_url"] for a in assets
                 if a.get("name", "").endswith(".exe")),
                RELEASES_PAGE)

            if _is_newer(latest_tag, current_version):
                log.info("Update available: %s", latest_tag)
                bridge.found.emit(latest_tag.lstrip("v"), dl_url)
            else:
                log.debug("App is up to date (%s)", current_version)

        except URLError as exc:
            log.debug("Update check failed (network): %s", exc)
        except Exception as exc:
            log.debug("Update check error: %s", exc)

    t = Thread(target=_worker, daemon=True)
    t.start()
