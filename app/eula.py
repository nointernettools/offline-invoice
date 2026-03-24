"""
app/eula.py
End-User License Agreement dialog — shown once on first launch.
Stores acceptance in profile so it never appears again.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

ACCENT = "#2563EB"

EULA_TEXT = """\
OFFLINE INVOICE — END-USER LICENSE AGREEMENT
Last updated: 2025

PLEASE READ THIS AGREEMENT CAREFULLY BEFORE USING THIS SOFTWARE.

1. LICENSE GRANT
   Subject to the terms of this Agreement, you are granted a non-exclusive,
   non-transferable license to install and use one (1) copy of Offline Invoice
   ("the Software") on a single computer you own or control.

2. RESTRICTIONS
   You may not:
   (a) Copy, redistribute, sublicense, sell, or transfer the Software to any
       third party without prior written consent;
   (b) Reverse-engineer, decompile, disassemble, or attempt to derive the
       source code of the Software;
   (c) Remove or alter any proprietary notices, labels, or marks on the Software;
   (d) Use the Software to develop a competing product.

3. OWNERSHIP
   The Software is licensed, not sold. The developer retains all intellectual
   property rights in the Software, including all copies made by you.

4. PRIVACY & DATA
   Offline Invoice stores all invoice, customer, and business data LOCALLY on
   your computer only. No invoice data, customer data, or business information
   is transmitted to any server.

   The following data MAY leave your machine:
   • Your license key — sent to the licensing server solely for activation
     and validation (Gumroad API).
   • Your current app version number — sent anonymously to check for updates
     via the GitHub Releases API.

   No personal data, invoice content, or financial data is ever transmitted.

5. DISCLAIMER OF WARRANTIES
   THE SOFTWARE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   IMPLIED. THE DEVELOPER DOES NOT WARRANT THAT THE SOFTWARE WILL BE ERROR-FREE
   OR UNINTERRUPTED.

6. LIMITATION OF LIABILITY
   IN NO EVENT SHALL THE DEVELOPER BE LIABLE FOR ANY INDIRECT, INCIDENTAL,
   SPECIAL, OR CONSEQUENTIAL DAMAGES ARISING OUT OF OR RELATED TO YOUR USE OF
   THE SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.

7. TERMINATION
   This license is effective until terminated. It will terminate automatically
   if you fail to comply with any term of this Agreement.

8. GOVERNING LAW
   This Agreement shall be governed by the laws of the jurisdiction in which
   the developer is located, without regard to conflict-of-law principles.

By clicking "I Agree", you acknowledge that you have read, understood, and
agree to be bound by the terms of this Agreement.
"""

PRIVACY_TEXT = """\
OFFLINE INVOICE — PRIVACY POLICY
Last updated: 2025

WHAT WE COLLECT
  • License activation: your license key is sent to Gumroad solely to
    verify your purchase. No other data is sent.
  • Update checks: your current app version number is sent anonymously
    to the GitHub Releases API to check for newer versions.

WHAT WE DO NOT COLLECT
  • Invoice data, line items, totals, or financial information.
  • Customer names, emails, addresses, or any client data.
  • Your business name, address, logo, or profile information.
  • Usage analytics, crash reports, or telemetry of any kind.

DATA STORAGE
  All app data is stored exclusively in JSON files on your local computer
  in the app's data directory. We have no access to this data.

THIRD-PARTY SERVICES
  • Gumroad (gumroad.com) — processes license key validation.
    See gumroad.com/privacy for their policy.
  • GitHub (github.com) — provides the releases API for update checks.
    See docs.github.com/en/site-policy/privacy-policies for their policy.

CONTACT
  For privacy questions, contact the developer directly.
"""


class EulaDialog(QDialog):
    """
    Shown once on first launch. User must scroll through and check agreement.
    Returns QDialog.Accepted only when the checkbox is ticked and Agree clicked.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("License Agreement — Offline Invoice")
        self.setFixedSize(600, 580)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build()

        if parent:
            px = parent.x() + (parent.width()  - self.width())  // 2
            py = parent.y() + (parent.height() - self.height()) // 2
            self.move(px, py)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(24, 16, 24, 14); hl.setSpacing(4)

        title = QLabel("License Agreement & Privacy Policy")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color:white; font-size:15px; font-weight:700;"
            " background:transparent;")
        hl.addWidget(title)

        sub = QLabel(
            "Please read and accept the terms below to use Offline Invoice.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(
            "color:#bfdbfe; font-size:11px; background:transparent;")
        hl.addWidget(sub)
        root.addWidget(hdr)

        # ── Tab row ───────────────────────────────────────────────────────────
        tab_row = QWidget()
        tab_row.setStyleSheet("background:#f3f4f6;")
        trl = QHBoxLayout(tab_row)
        trl.setContentsMargins(16, 8, 16, 0); trl.setSpacing(4)

        self._eula_btn  = self._tab_btn("License Agreement", active=True)
        self._priv_btn  = self._tab_btn("Privacy Policy",    active=False)
        self._eula_btn.clicked.connect(lambda: self._show_tab("eula"))
        self._priv_btn.clicked.connect(lambda: self._show_tab("privacy"))
        trl.addWidget(self._eula_btn)
        trl.addWidget(self._priv_btn)
        trl.addStretch()
        root.addWidget(tab_row)

        # ── Text area ─────────────────────────────────────────────────────────
        body = QWidget(); body.setStyleSheet("background:white;")
        bodyl = QVBoxLayout(body)
        bodyl.setContentsMargins(0, 0, 0, 0)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlainText(EULA_TEXT)
        self._text.setStyleSheet(
            "QPlainTextEdit { background:white; border:none;"
            " font-family: 'Segoe UI', 'Inter', Arial, sans-serif;"
            " font-size: 13px; line-height: 1.6;"
            " color: #1f2937; padding: 16px 24px; }"
            "QScrollBar:vertical { width: 8px; }"
            "QScrollBar::handle:vertical { background:#d1d5db;"
            " border-radius:4px; }")
        bodyl.addWidget(self._text)
        root.addWidget(body, stretch=1)

        # ── Agreement checkbox ────────────────────────────────────────────────
        agree_frame = QFrame()
        agree_frame.setStyleSheet(
            "background:#f9fafb; border-top:1px solid #e5e7eb;")
        afl = QVBoxLayout(agree_frame)
        afl.setContentsMargins(20, 12, 20, 4); afl.setSpacing(6)

        self._check = QCheckBox(
            "I have read and agree to the License Agreement and Privacy Policy")
        self._check.setStyleSheet(
            "font-size:12px; font-weight:600; color:#1f2937;"
            " background:transparent;")
        self._check.stateChanged.connect(self._on_check)
        afl.addWidget(self._check)
        root.addWidget(agree_frame)

        # ── Footer buttons ────────────────────────────────────────────────────
        foot = QFrame()
        foot.setStyleSheet("background:white; border-top:1px solid #e5e7eb;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 10, 20, 16); fl.setSpacing(8)

        decline_btn = QPushButton("Decline & Exit")
        decline_btn.setFixedSize(140, 34)
        decline_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#fee2e2; color:#dc2626;"
            " border-color:#dc2626;}")
        decline_btn.clicked.connect(self.reject)
        fl.addWidget(decline_btn)
        fl.addStretch()

        self._agree_btn = QPushButton("I Agree — Continue  →")
        self._agree_btn.setFixedSize(200, 34)
        self._agree_btn.setEnabled(False)
        self._agree_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT}; color:white; border:none;"
            f" border-radius:6px; font-weight:600;}}"
            f"QPushButton:hover{{background:#1d4ed8;}}"
            f"QPushButton:disabled{{background:#9ca3af; color:#e5e7eb;}}")
        self._agree_btn.clicked.connect(self.accept)
        fl.addWidget(self._agree_btn)
        root.addWidget(foot)

    def _tab_btn(self, label: str, active: bool) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(30)
        btn.setCheckable(True)
        btn.setChecked(active)
        self._style_tab_btn(btn, active)
        return btn

    def _style_tab_btn(self, btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                f"QPushButton{{background:white; color:{ACCENT};"
                f" border:1px solid #e5e7eb; border-bottom:2px solid {ACCENT};"
                f" border-radius:4px 4px 0 0; font-weight:600; padding:0 16px;}}")
        else:
            btn.setStyleSheet(
                "QPushButton{background:transparent; color:#6b7280;"
                " border:none; font-weight:400; padding:0 16px;}"
                "QPushButton:hover{color:#374151;}")

    def _show_tab(self, tab: str):
        self._text.setPlainText(
            EULA_TEXT if tab == "eula" else PRIVACY_TEXT)
        from PySide6.QtGui import QTextCursor
        self._text.moveCursor(QTextCursor.MoveOperation.Start)
        self._style_tab_btn(self._eula_btn, tab == "eula")
        self._style_tab_btn(self._priv_btn, tab == "privacy")

    def _on_check(self):
        self._agree_btn.setEnabled(self._check.isChecked())


def eula_accepted() -> bool:
    """Return True if the user has already accepted the EULA."""
    from app.storage import load_profile
    p = load_profile() or {}
    return bool(p.get("eula_accepted"))


def mark_eula_accepted():
    """Persist EULA acceptance to profile."""
    from app.storage import load_profile, save_profile
    p = load_profile() or {}
    p["eula_accepted"] = True
    save_profile(p)


def show_eula_if_needed(parent: QWidget) -> bool:
    """
    Show EULA dialog if not yet accepted.
    Returns True if accepted (or already accepted), False if declined.
    If declined, the caller should exit the app.
    """
    if eula_accepted():
        return True
    dlg = EulaDialog(parent)
    if dlg.exec() == QDialog.Accepted:
        mark_eula_accepted()
        return True
    return False