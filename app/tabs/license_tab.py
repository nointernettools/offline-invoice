"""
License tab — activate, view status, deactivate.
PySide6 migration: CTkScrollableFrame → QScrollArea,
CTkProgressBar → QProgressBar, messagebox → QMessageBox.
"""
from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.license import (
    TRIAL_INVOICE_LIMIT,
    activate, deactivate, load_license,
)

ACCENT = "#2563EB"


# ── Card helper ───────────────────────────────────────────────────────────────

class _Card(QFrame):
    """White rounded card with accent header label + divider."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: white; border-radius: 8px; border: none; }")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self._vbox = QVBoxLayout(self)
        self._vbox.setContentsMargins(0, 0, 0, 12)
        self._vbox.setSpacing(0)

        hdr = QLabel(title)
        hdr.setContentsMargins(12, 10, 12, 4)
        hdr.setStyleSheet(
            f"color:{ACCENT}; font-weight:700; font-size:13px;"
            " background:transparent;")
        self._vbox.addWidget(hdr)

        div = QFrame()
        div.setFixedHeight(1)
        div.setContentsMargins(12, 0, 12, 0)
        div.setStyleSheet("background:#e5e7eb; margin:0 12px;")
        self._vbox.addWidget(div)

    @property
    def body(self) -> QVBoxLayout:
        return self._vbox


# ── Tab ───────────────────────────────────────────────────────────────────────

class LicenseTab:
    """Builds and owns the License tab UI (PySide6)."""

    def __init__(self, parent: QWidget, app):
        self.app = app
        self._build(parent)
        self.refresh()

    def _build(self, parent: QWidget):
        root = QVBoxLayout(parent)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:#f3f4f6; border:none;}")
        root.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet("background:#f3f4f6;")
        scroll.setWidget(container)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)
        outer.setAlignment(Qt.AlignTop)

        # ── Status card ───────────────────────────────────────────────────────
        sc = _Card("License Status")
        outer.addWidget(sc)

        self._status_icon = QLabel("")
        self._status_icon.setAlignment(Qt.AlignCenter)
        fi = QFont(); fi.setPointSize(28)
        self._status_icon.setFont(fi)
        self._status_icon.setStyleSheet(
            "background:transparent; padding:8px 0 4px;")
        sc.body.addWidget(self._status_icon)

        self._status_title = QLabel("")
        self._status_title.setAlignment(Qt.AlignCenter)
        ft = QFont(); ft.setPointSize(14); ft.setBold(True)
        self._status_title.setFont(ft)
        self._status_title.setStyleSheet("background:transparent;")
        sc.body.addWidget(self._status_title)

        self._status_sub = QLabel("")
        self._status_sub.setAlignment(Qt.AlignCenter)
        self._status_sub.setStyleSheet(
            "color:#6b7280; font-size:12px; background:transparent;"
            " padding-bottom:8px;")
        sc.body.addWidget(self._status_sub)

        # Trial progress
        self._trial_frame = QWidget()
        self._trial_frame.setStyleSheet("background:transparent;")
        tfl = QVBoxLayout(self._trial_frame)
        tfl.setContentsMargins(20, 0, 20, 12)
        tfl.setSpacing(4)

        self._trial_bar = QProgressBar()
        self._trial_bar.setFixedHeight(10)
        self._trial_bar.setTextVisible(False)
        self._trial_bar.setRange(0, 100)
        tfl.addWidget(self._trial_bar)

        self._trial_lbl = QLabel("")
        self._trial_lbl.setAlignment(Qt.AlignCenter)
        self._trial_lbl.setStyleSheet(
            "color:#6b7280; font-size:11px; background:transparent;")
        tfl.addWidget(self._trial_lbl)

        sc.body.addWidget(self._trial_frame)

        # ── Activation card ───────────────────────────────────────────────────
        ac = _Card("Activate License")
        outer.addWidget(ac)

        kr = QWidget(); kr.setStyleSheet("background:transparent;")
        krl = QHBoxLayout(kr)
        krl.setContentsMargins(12, 4, 12, 6); krl.setSpacing(8)
        kl = QLabel("License Key")
        kl.setFixedWidth(110)
        kl.setStyleSheet("font-size:12px; color:#374151; background:transparent;")
        krl.addWidget(kl)
        self._key_entry = QLineEdit()
        self._key_entry.setPlaceholderText(
            "XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX")
        krl.addWidget(self._key_entry)
        ac.body.addWidget(kr)

        br = QWidget(); br.setStyleSheet("background:transparent;")
        brl = QHBoxLayout(br)
        brl.setContentsMargins(12, 0, 12, 4)
        brl.addStretch()
        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setFixedSize(140, 34)
        self._activate_btn.clicked.connect(self._on_activate)
        brl.addWidget(self._activate_btn)
        ac.body.addWidget(br)

        hint = QLabel(
            "Your license key is emailed to you by Gumroad after purchase.")
        hint.setContentsMargins(12, 0, 12, 10)
        hint.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        ac.body.addWidget(hint)

        # ── Purchase card ─────────────────────────────────────────────────────
        bc = _Card("Get Offline Invoice")
        outer.addWidget(bc)

        for line in [
            "✓  Unlimited invoices",
            "✓  All 5 professional templates",
            "✓  Customer CRM",
            "✓  Recurring invoice templates",
            "✓  QR code payment links",
            "✓  CSV export  ·  Invoice history  ·  Overdue alerts",
            "✓  One-time purchase — no subscription",
        ]:
            lbl = QLabel(line)
            lbl.setContentsMargins(20, 2, 12, 2)
            lbl.setStyleSheet(
                "font-size:12px; color:#374151; background:transparent;")
            bc.body.addWidget(lbl)

        sp = QWidget(); sp.setFixedHeight(8)
        sp.setStyleSheet("background:transparent;")
        bc.body.addWidget(sp)

        gw = QWidget(); gw.setStyleSheet("background:transparent;")
        gl = QHBoxLayout(gw); gl.setContentsMargins(12, 0, 12, 0)
        gb = QPushButton("Buy on Gumroad  →")
        gb.setFixedSize(200, 36)
        gb.clicked.connect(self._open_gumroad)
        gl.addWidget(gb); gl.addStretch()
        bc.body.addWidget(gw)

        # ── Deactivate card ───────────────────────────────────────────────────
        self._deact_card = _Card("Manage License")
        outer.addWidget(self._deact_card)

        dl = QLabel(
            "Deactivating removes the license from this machine.\n"
            "You can re-activate on the same or a different machine.")
        dl.setContentsMargins(12, 4, 12, 0)
        dl.setStyleSheet(
            "color:#6b7280; font-size:12px; background:transparent;")
        self._deact_card.body.addWidget(dl)

        dw = QWidget(); dw.setStyleSheet("background:transparent;")
        dwl = QHBoxLayout(dw); dwl.setContentsMargins(12, 8, 12, 0)
        self._deact_btn = QPushButton("Deactivate This Machine")
        self._deact_btn.setFixedSize(200, 32)
        self._deact_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#dc2626;"
            " border:1px solid #dc2626; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#fee2e2;}")
        self._deact_btn.clicked.connect(self._on_deactivate)
        dwl.addWidget(self._deact_btn); dwl.addStretch()
        self._deact_card.body.addWidget(dw)

        outer.addStretch()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        from app.storage import load_invoices
        status = load_license()
        self.app.license_status = status

        if status.licensed:
            self._status_icon.setText("✅")
            self._status_title.setText("Licensed")
            self._status_title.setStyleSheet(
                "color:#166534; font-size:16px; font-weight:700;"
                " background:transparent;")
            self._status_sub.setText(f"Licensed to {status.email}")
            self._trial_frame.hide()
            self._deact_card.show()
            self._key_entry.setEnabled(False)
            self._activate_btn.setEnabled(False)
            self._activate_btn.setText("Already Activated")
        else:
            remaining = max(0, TRIAL_INVOICE_LIMIT - len(load_invoices()))
            self._status_icon.setText("⏳" if remaining > 0 else "🔒")
            self._status_title.setText("Trial Mode")
            color = "#92400e" if remaining > 0 else "#991b1b"
            self._status_title.setStyleSheet(
                f"color:{color}; font-size:16px; font-weight:700;"
                " background:transparent;")
            self._status_sub.setText(
                f"{remaining} free invoice"
                f"{'s' if remaining != 1 else ''} remaining"
                if remaining > 0 else
                "Trial limit reached — activate to continue generating invoices")
            self._trial_frame.show()
            used = TRIAL_INVOICE_LIMIT - remaining
            self._trial_bar.setValue(
                int(used / TRIAL_INVOICE_LIMIT * 100))
            self._trial_lbl.setText(
                f"{used} of {TRIAL_INVOICE_LIMIT} free invoices used")
            self._deact_card.hide()
            self._key_entry.setEnabled(True)
            self._activate_btn.setEnabled(True)
            self._activate_btn.setText("Activate")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_activate(self):
        key = self._key_entry.text().strip()
        if not key:
            QMessageBox.warning(
                self._key_entry.window(), "No Key",
                "Please enter your license key.")
            return
        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Verifying…")
        QApplication.processEvents()
        result = activate(key)
        if result.licensed:
            self.refresh()
            QMessageBox.information(
                self._activate_btn.window(), "Activated! 🎉",
                f"Offline Invoice is now fully licensed.\n\n"
                f"Licensed to: {result.email}\n\n"
                f"Thank you for your purchase!")
        else:
            self._activate_btn.setEnabled(True)
            self._activate_btn.setText("Activate")
            QMessageBox.critical(
                self._activate_btn.window(),
                "Activation Failed", result.message)

    def _on_deactivate(self):
        reply = QMessageBox.question(
            self._deact_btn.window(), "Deactivate License",
            "Remove the license from this machine?\n\n"
            "You can re-activate using the same key on any machine.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        deactivate()
        self.refresh()
        QMessageBox.information(
            self._deact_btn.window(),
            "Deactivated", "License removed from this machine.")

    @staticmethod
    def _open_gumroad():
        url = "https://yourname.gumroad.com/l/offlineinvoice"
        if sys.platform == "win32":
            os.startfile(url)
        elif sys.platform == "darwin":
            subprocess.run(["open", url])
        else:
            subprocess.run(["xdg-open", url])