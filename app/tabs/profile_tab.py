"""
Business Profile tab — company info, logo, colors, settings, email, backup.
PySide6 migration: CTk → Qt, pack → QLayout, filedialog → QFileDialog,
messagebox → QMessageBox, BooleanVar → QCheckBox.isChecked(),
CTkScrollableFrame → QScrollArea, color swatches → QPushButton grid.
"""
from __future__ import annotations

import io
import json
import logging
import os
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from app.icon_utils import get_icon
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from app.color_utils import (
    DEFAULT_ACCENT, PRESET_COLORS,
    is_valid_hex, normalise,
)
from app.pdf_gen import WEASY_TEMPLATES
from app.storage import get_output_dir, load_profile, save_profile

log = logging.getLogger(__name__)

ACCENT        = "#2563EB"
TEMPLATE_LIST = list(WEASY_TEMPLATES.keys())

def _accent_btn(text: str, icon_name: str | None = None,
                w: int = 140, h: int = 32,
                color: str = ACCENT) -> QPushButton:
    btn = QPushButton(f"  {text}" if icon_name else text)
    if icon_name:
        btn.setIcon(get_icon(icon_name))
    btn.setFixedSize(w, h)
    btn.setStyleSheet(
        f"QPushButton{{background:{color}; color:white; border:none;"
        f" border-radius:6px; font-weight:600; padding:0 10px;}}"
        f"QPushButton:hover{{background:#1d4ed8;}}"
        f"QPushButton:pressed{{background:#1e3a8a;}}"
        f"QPushButton:disabled{{background:#9ca3af; color:#e5e7eb;}}")
    return btn


def _storage_files() -> dict[str, Path]:
    from app.storage import (
        CUSTOMER_FILE, INVOICE_FILE,
        PROFILE_FILE, TEMPLATE_FILE,
    )
    return {
        "invoices.json":          INVOICE_FILE,
        "customers.json":         CUSTOMER_FILE,
        "invoice_templates.json": TEMPLATE_FILE,
        "profile.json":           PROFILE_FILE,
    }


# ── Reusable card ─────────────────────────────────────────────────────────────

class _Card(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame{background:white; border-radius:8px; border:none;}")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self._vbox = QVBoxLayout(self)
        self._vbox.setContentsMargins(0, 0, 0, 12)
        self._vbox.setSpacing(0)

        hdr = QLabel(title)
        hdr.setContentsMargins(12, 8, 12, 2)
        hdr.setStyleSheet(
            f"color:{ACCENT}; font-weight:700; font-size:13px;"
            " background:transparent;")
        self._vbox.addWidget(hdr)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background:#e5e7eb; margin:0 12px;")
        self._vbox.addWidget(div)

    @property
    def body(self) -> QVBoxLayout:
        return self._vbox


# ── Row helper ────────────────────────────────────────────────────────────────

def _row_entry(parent_layout: QVBoxLayout,
               label: str,
               placeholder: str = "",
               password: bool = False) -> QLineEdit:
    """Add a label+entry pair to a card body layout. Returns the QLineEdit."""
    row = QWidget()
    row.setStyleSheet("background:transparent;")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(12, 3, 12, 3)
    rl.setSpacing(8)

    lbl = QLabel(label)
    lbl.setFixedWidth(120)
    lbl.setStyleSheet(
        "font-size:12px; color:#374151; background:transparent;")
    rl.addWidget(lbl)

    entry = QLineEdit()
    entry.setPlaceholderText(placeholder)
    if password:
        entry.setEchoMode(QLineEdit.Password)
    rl.addWidget(entry)

    parent_layout.addWidget(row)
    return entry


# ── Tab ───────────────────────────────────────────────────────────────────────

class ProfileTab:

    def __init__(self, parent: QWidget, app):
        self.app            = app
        self._logo_path:  str | None = None
        self._accent_color: str      = DEFAULT_ACCENT
        self._swatch_btns:  dict[str, QPushButton] = {}
        self._build(parent)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self, parent: QWidget):
        root = QVBoxLayout(parent)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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
        outer.setSpacing(6)
        outer.setAlignment(Qt.AlignTop)

        # ── 1. Business Information ───────────────────────────────────────────
        biz = _Card("Business Information")
        outer.addWidget(biz)

        self.p_name   = _row_entry(biz.body, "Company *",
                                   "Your Business LLC")
        self.p_email  = _row_entry(biz.body, "Email *",
                                   "hello@yourbusiness.com")
        self.p_phone  = _row_entry(biz.body, "Phone",
                                   "e.g. 123-456-7890")
        self.p_addr   = _row_entry(biz.body, "Address", "Street address")

        # City / State / ZIP inline
        csz_w = QWidget(); csz_w.setStyleSheet("background:transparent;")
        csz_l = QHBoxLayout(csz_w)
        csz_l.setContentsMargins(12, 3, 12, 3); csz_l.setSpacing(6)

        csz_lbl = QLabel("City, State, ZIP")
        csz_lbl.setFixedWidth(120)
        csz_lbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        csz_l.addWidget(csz_lbl)

        self.p_city  = QLineEdit(); self.p_city.setPlaceholderText("City")
        self.p_state = QLineEdit(); self.p_state.setPlaceholderText("State")
        self.p_state.setFixedWidth(68)
        self.p_zip   = QLineEdit(); self.p_zip.setPlaceholderText("ZIP")
        self.p_zip.setFixedWidth(76)

        csz_l.addWidget(self.p_city, stretch=1)
        csz_l.addWidget(self.p_state)
        csz_l.addWidget(self.p_zip)
        biz.body.addWidget(csz_w)

        self.p_prefix = _row_entry(biz.body, "Inv. Prefix", "e.g. INV-")

        # Spacer
        sp = QWidget(); sp.setFixedHeight(4)
        sp.setStyleSheet("background:transparent;")
        biz.body.addWidget(sp)

        # ── 2. Company Logo ───────────────────────────────────────────────────
        logo_card = _Card("Company Logo")
        outer.addWidget(logo_card)

        req = QLabel(
            "PNG · JPG · JPEG · GIF   |   Recommended: 300×100 px"
            "   |   Max: 500×200 px   |   Transparent PNG preferred")
        req.setContentsMargins(20, 4, 12, 4)
        req.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:#f9fafb;"
            " border-radius:6px;")
        logo_card.body.addWidget(req)

        logo_row = QWidget(); logo_row.setStyleSheet("background:transparent;")
        lrl = QHBoxLayout(logo_row)
        lrl.setContentsMargins(12, 0, 12, 8); lrl.setSpacing(8)

        self.logo_label = QLabel("  No logo selected")
        self.logo_label.setFixedSize(200, 30)
        self.logo_label.setStyleSheet(
            "background:#f3f4f6; border-radius:6px; color:#9ca3af;"
            " font-size:12px; padding-left:6px;")
        lrl.addWidget(self.logo_label)

        sel_btn = _accent_btn("Select…", "folder", w=110, h=30)
        sel_btn.clicked.connect(self._pick_logo)
        lrl.addWidget(sel_btn)

        clr_btn = _accent_btn("Clear", w=80, h=30)
        clr_btn.clicked.connect(self._clear_logo)
        lrl.addWidget(clr_btn)
        lrl.addStretch()
        logo_card.body.addWidget(logo_row)

        # ── 3. PDF Output Folder ──────────────────────────────────────────────
        out_card = _Card("PDF Output Folder")
        outer.addWidget(out_card)

        out_row = QWidget(); out_row.setStyleSheet("background:transparent;")
        orl = QHBoxLayout(out_row)
        orl.setContentsMargins(12, 0, 12, 8); orl.setSpacing(8)

        self.p_outdir = QLineEdit()
        self.p_outdir.setPlaceholderText("Folder where invoices are saved…")
        orl.addWidget(self.p_outdir, stretch=1)

        browse_btn = _accent_btn("Browse…", "folder", w=110, h=30)
        browse_btn.clicked.connect(self._pick_outdir)
        orl.addWidget(browse_btn)
        out_card.body.addWidget(out_row)

# ── 4. Brand Accent Color ─────────────────────────────────────────────
        color_card = _Card("Brand Accent Color")
        outer.addWidget(color_card)

        # Single row: swatches + divider + hex input + preview swatch
        color_row = QWidget(); color_row.setStyleSheet("background:transparent;")
        crl = QHBoxLayout(color_row)
        crl.setContentsMargins(12, 6, 12, 8); crl.setSpacing(4)

        # Compact swatch grid — all presets in one flow row
        for hex_val, _name in PRESET_COLORS:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(
                f"QPushButton{{background:{hex_val}; border-radius:11px;"
                f" border:2px solid transparent;}}"
                f"QPushButton:hover{{border-color:white; border-width:2px;}}")
            btn.clicked.connect(lambda _, h=hex_val: self._pick_preset(h))
            crl.addWidget(btn)
            self._swatch_btns[hex_val] = btn

        # Thin divider
        div = QFrame(); div.setFixedSize(1, 22)
        div.setStyleSheet("background:#e5e7eb;")
        crl.addSpacing(4)
        crl.addWidget(div)
        crl.addSpacing(4)

        # Hex input
        self.p_accent_hex = QLineEdit()
        self.p_accent_hex.setPlaceholderText("#2563eb")
        self.p_accent_hex.setFixedWidth(80)
        self.p_accent_hex.setFixedHeight(26)
        self.p_accent_hex.textChanged.connect(self._on_hex_typed)
        crl.addWidget(self.p_accent_hex)

        # Live preview swatch
        self._accent_swatch = QFrame()
        self._accent_swatch.setFixedSize(24, 24)
        self._accent_swatch.setStyleSheet(
            f"background:{DEFAULT_ACCENT}; border-radius:4px; border:none;")
        crl.addWidget(self._accent_swatch)

        # Current hex label
        self._accent_preview_lbl = QLabel(DEFAULT_ACCENT)
        self._accent_preview_lbl.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        crl.addWidget(self._accent_preview_lbl)
        crl.addStretch()
        color_card.body.addWidget(color_row)

        # ── 5. Settings ───────────────────────────────────────────────────────
        act = _Card("Settings")
        outer.addWidget(act)

        self.p_payment_link = _row_entry(
            act.body, "Payment Link",
            "Default PayPal / Stripe / payment URL (optional)…")
        self.p_payment_terms = _row_entry(
            act.body, "Footer Terms",
            "e.g. Net 30 · Late payments subject to 1.5%/month")

        hint = QLabel(
            "↑  Both saved once here — auto-filled on every new invoice")
        hint.setContentsMargins(12, 0, 12, 8)
        hint.setStyleSheet(
            "color:#9ca3af; font-size:10px; background:transparent;")
        act.body.addWidget(hint)

        act_row = QWidget(); act_row.setStyleSheet("background:transparent;")
        arl = QHBoxLayout(act_row)
        arl.setContentsMargins(12, 0, 12, 0); arl.setSpacing(8)

        wiz_btn = _accent_btn("Industry Wizard", "industry", w=160, h=32)
        wiz_btn.clicked.connect(self.app.launch_wizard)
        arl.addWidget(wiz_btn)

        about_btn = _accent_btn("About", "about", w=100, h=32)
        about_btn.clicked.connect(self.app.show_about)
        arl.addWidget(about_btn)
        arl.addStretch()
        act.body.addWidget(act_row)

        sp2 = QWidget(); sp2.setFixedHeight(8)
        sp2.setStyleSheet("background:transparent;")
        act.body.addWidget(sp2)

        # ── 6. Email Settings (SMTP) ──────────────────────────────────────────
        smtp_card = _Card("Email Settings  (optional)")
        outer.addWidget(smtp_card)

        smtp_hint = QLabel(
            "Fill these in to send invoices directly from the app "
            "with the PDF attached.\n"
            "Leave blank to use 'Open in Email App' instead "
            "(no setup required).")
        smtp_hint.setContentsMargins(12, 0, 12, 6)
        smtp_hint.setWordWrap(True)
        smtp_hint.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        smtp_card.body.addWidget(smtp_hint)

        self.p_smtp_host = _row_entry(smtp_card.body, "SMTP Host",
                                      "e.g. smtp.gmail.com")
        self.p_smtp_port = _row_entry(smtp_card.body, "Port",
                                      "587  (TLS)  or  465  (SSL)")
        self.p_smtp_user = _row_entry(smtp_card.body, "Username",
                                      "your@email.com")
        self.p_smtp_pass = _row_entry(smtp_card.body, "Password",
                                      "App password or SMTP password",
                                      password=True)
        self.p_smtp_from = _row_entry(smtp_card.body, "From Address",
                                      "Defaults to business email if blank")

        ssl_w = QWidget(); ssl_w.setStyleSheet("background:transparent;")
        ssl_l = QHBoxLayout(ssl_w)
        ssl_l.setContentsMargins(12, 4, 12, 4)
        self._smtp_ssl_cb = QCheckBox("Use SSL (port 465)")
        self._smtp_ssl_cb.setStyleSheet("background:transparent;")
        ssl_l.addWidget(self._smtp_ssl_cb)
        ssl_l.addStretch()
        smtp_card.body.addWidget(ssl_w)

        gmail_tip = QLabel(
            "Gmail tip: use an App Password — "
            "myaccount.google.com → Security → App passwords")
        gmail_tip.setContentsMargins(12, 0, 12, 10)
        gmail_tip.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        smtp_card.body.addWidget(gmail_tip)

        # Save Profile button
        save_row = QWidget(); save_row.setStyleSheet("background:transparent;")
        srl = QHBoxLayout(save_row)
        srl.setContentsMargins(12, 0, 12, 0)
        save_btn = _accent_btn("Save Profile", "save", w=150, h=34)
        save_btn.clicked.connect(self.save)
        srl.addWidget(save_btn)
        srl.addStretch()
        smtp_card.body.addWidget(save_row)

        sp3 = QWidget(); sp3.setFixedHeight(8)
        sp3.setStyleSheet("background:transparent;")
        smtp_card.body.addWidget(sp3)

        # ── 7. Backup & Restore ───────────────────────────────────────────────
        bk = _Card("Data Backup & Restore")
        outer.addWidget(bk)

        bk_hint = QLabel(
            "Backup saves all your invoices, customers, templates and "
            "profile to a single zip file.\n"
            "Restore merges a backup into your current data — "
            "existing records are kept.")
        bk_hint.setContentsMargins(12, 0, 12, 8)
        bk_hint.setWordWrap(True)
        bk_hint.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        bk.body.addWidget(bk_hint)

        bk_row = QWidget(); bk_row.setStyleSheet("background:transparent;")
        brl = QHBoxLayout(bk_row)
        brl.setContentsMargins(12, 0, 12, 0); brl.setSpacing(12)

        export_btn = _accent_btn("Export Backup", "down-arrow", w=170, h=34)
        export_btn.clicked.connect(self._export_backup)
        brl.addWidget(export_btn)

        restore_btn = _accent_btn("Restore Backup", "refresh", w=170, h=34)
        restore_btn.clicked.connect(self._restore_backup)
        brl.addWidget(restore_btn)
        brl.addStretch()
        bk.body.addWidget(bk_row)

        self._backup_status = QLabel("")
        self._backup_status.setContentsMargins(12, 4, 12, 8)
        self._backup_status.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        bk.body.addWidget(self._backup_status)

        outer.addStretch()

    # ── Logo ──────────────────────────────────────────────────────────────────

    def _pick_logo(self):
        win = self.logo_label.window()
        f, _ = QFileDialog.getOpenFileName(
            win, "Select Logo",
            str(Path.home()),
            "Image files (*.png *.jpg *.jpeg *.gif);;All files (*.*)")
        if f:
            self._logo_path    = f
            self.app.logo_path = f
            self.logo_label.setText(f"  {os.path.basename(f)}")
            self.logo_label.setStyleSheet(
                "background:#f3f4f6; border-radius:6px; color:#374151;"
                " font-size:12px; padding-left:6px;")

    def _clear_logo(self):
        self._logo_path    = None
        self.app.logo_path = None
        self.logo_label.setText("  No logo selected")
        self.logo_label.setStyleSheet(
            "background:#f3f4f6; border-radius:6px; color:#9ca3af;"
            " font-size:12px; padding-left:6px;")

    # ── Color ─────────────────────────────────────────────────────────────────

    def _pick_preset(self, hex_val: str):
        self._accent_color    = hex_val
        self.app.accent_color = hex_val
        self.p_accent_hex.setText(hex_val)
        self._accent_swatch.setStyleSheet(
            f"background:{hex_val}; border-radius:6px; border:none;")
        self._accent_preview_lbl.setText(hex_val)
        self._update_swatch_borders(hex_val)
        # accent_color stored for PDF rendering only — UI color is unchanged
        if self.app.invoice_tab:
            self.app.invoice_tab.schedule_preview()

    def _on_hex_typed(self):
        raw = self.p_accent_hex.text().strip()
        if is_valid_hex(raw):
            norm = normalise(raw)
            self._accent_color    = norm
            self.app.accent_color = norm
            self._accent_swatch.setStyleSheet(
                f"background:{norm}; border-radius:6px; border:none;")
            self._accent_preview_lbl.setText(norm)
            self._update_swatch_borders(norm)
            # accent_color stored for PDF rendering only — UI color is unchanged
            try:
                if self.app.invoice_tab:
                    self.app.invoice_tab.schedule_preview()
            except AttributeError:
                pass

    def _update_swatch_borders(self, selected: str):
        for h, btn in self._swatch_btns.items():
            border = "white" if h == selected else "#888888"
            btn.setStyleSheet(
                f"QPushButton{{background:{h}; border-radius:13px;"
                f" border:2px solid {border};}}"
                f"QPushButton:hover{{border-color:{h}; border-width:3px;}}")

    # ── Output dir ────────────────────────────────────────────────────────────

    def _pick_outdir(self):
        win = self.p_outdir.window()
        d = QFileDialog.getExistingDirectory(
            win, "Select Output Folder",
            self.p_outdir.text() or str(Path.home()))
        if d:
            self.p_outdir.setText(d)

    # ── Backup & Restore ──────────────────────────────────────────────────────

    def _export_backup(self):
        stamp        = datetime.now().strftime("%Y-%m-%d")
        default_name = f"OfflineInvoice_backup_{stamp}.zip"
        win = self._backup_status.window()

        path, _ = QFileDialog.getSaveFileName(
            win, "Export Backup",
            str(Path.home() / "Desktop" / default_name),
            "Zip archive (*.zip);;All files (*.*)")
        if not path:
            return

        files    = _storage_files()
        included = []
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, src in files.items():
                    if src.exists():
                        zf.write(src, arcname=name)
                        included.append(name)
                        log.info("Backup: included %s (%d bytes)",
                                 name, src.stat().st_size)

            size_kb = Path(path).stat().st_size // 1024
            summary = ", ".join(included) or "no data files found"
            log.info("Backup exported to %s  (%d KB)", path, size_kb)

            self._backup_status.setText(
                f"Backup saved  ·  {size_kb} KB  ·  {stamp}")
            self._backup_status.setStyleSheet(
                "color:#166534; font-size:11px; background:transparent;"
                " padding-left:12px;")
            QMessageBox.information(
                win, "Backup Complete",
                f"Backup saved to:\n{path}\n\n"
                f"Included: {summary}\n"
                f"Size: {size_kb} KB")

        except OSError as exc:
            log.error("Backup failed: %s", exc)
            QMessageBox.critical(win, "Backup Failed", str(exc))

    def _restore_backup(self):
        win = self._backup_status.window()
        path, _ = QFileDialog.getOpenFileName(
            win, "Select Backup File",
            str(Path.home() / "Desktop"),
            "Zip archive (*.zip);;All files (*.*)")
        if not path:
            return

        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
        except (zipfile.BadZipFile, OSError) as exc:
            log.error("Restore: invalid zip: %s", exc)
            QMessageBox.critical(
                win, "Invalid File",
                "The selected file is not a valid backup zip.")
            return

        expected = {"invoices.json", "customers.json",
                    "invoice_templates.json", "profile.json"}
        if not (expected & set(names)):
            QMessageBox.critical(
                win, "Invalid Backup",
                f"This zip doesn't appear to be an Offline Invoice backup.\n"
                f"Expected one of: {', '.join(sorted(expected))}\n"
                f"Found: {', '.join(names) or 'nothing'}")
            return

        reply = QMessageBox.question(
            win, "Restore Backup",
            f"Restore from:\n{path}\n\n"
            "Records from the backup will be merged into your current data.\n"
            "Existing records are not deleted.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        from app.storage import (
            CUSTOMER_FILE, INVOICE_FILE,
            PROFILE_FILE, TEMPLATE_FILE,
            load_all_customers, load_all_templates, load_invoices,
        )

        restored: list[str] = []
        skipped:  list[str] = []

        try:
            with zipfile.ZipFile(path, "r") as zf:

                # Invoices
                if "invoices.json" in names:
                    backup_inv = json.loads(zf.read("invoices.json"))
                    live_inv   = load_invoices()
                    live_keys  = {
                        (i.get("number"), i.get("client"), i.get("issue_date"))
                        for i in live_inv
                    }
                    added = 0
                    for inv in backup_inv:
                        k = (inv.get("number"), inv.get("client"),
                             inv.get("issue_date"))
                        if k not in live_keys:
                            live_inv.append(inv)
                            live_keys.add(k)
                            added += 1
                    INVOICE_FILE.write_text(
                        json.dumps(live_inv, indent=2), encoding="utf-8")
                    restored.append(f"{added} invoice(s)")
                    skipped.append(
                        f"{len(backup_inv) - added} invoice(s) already exist")
                    log.info("Restore invoices: +%d added, %d skipped",
                             added, len(backup_inv) - added)

                # Customers
                if "customers.json" in names:
                    backup_cust = json.loads(zf.read("customers.json"))
                    live_cust   = load_all_customers()
                    live_emails = {c.get("email", "").lower()
                                   for c in live_cust if c.get("email")}
                    live_names  = {c.get("name", "").lower()
                                   for c in live_cust}
                    added = 0
                    for c in backup_cust:
                        n = c.get("name",  "").lower()
                        e = c.get("email", "").lower()
                        if n in live_names or (e and e in live_emails):
                            continue
                        c = {**c, "id": str(uuid.uuid4())}
                        live_cust.append(c)
                        live_names.add(n)
                        if e:
                            live_emails.add(e)
                        added += 1
                    CUSTOMER_FILE.write_text(
                        json.dumps(live_cust, indent=2), encoding="utf-8")
                    restored.append(f"{added} customer(s)")
                    skipped.append(
                        f"{len(backup_cust) - added} customer(s) already exist")

                # Templates
                if "invoice_templates.json" in names:
                    backup_tmpl = json.loads(
                        zf.read("invoice_templates.json"))
                    live_tmpl   = load_all_templates()
                    live_ids    = {t.get("id") for t in live_tmpl}
                    added = 0
                    for t in backup_tmpl:
                        if t.get("id") not in live_ids:
                            live_tmpl.append(t)
                            live_ids.add(t.get("id"))
                            added += 1
                    TEMPLATE_FILE.write_text(
                        json.dumps(live_tmpl, indent=2), encoding="utf-8")
                    restored.append(f"{added} template(s)")

                # Profile
                if "profile.json" in names:
                    backup_prof = json.loads(zf.read("profile.json"))
                    existing    = load_profile()
                    if existing and existing.get("name"):
                        overwrite = QMessageBox.question(
                            win, "Overwrite Profile?",
                            "A profile already exists. Replace it with "
                            "the backup profile?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No,
                        ) == QMessageBox.Yes
                        if overwrite:
                            PROFILE_FILE.write_text(
                                json.dumps(backup_prof, indent=2),
                                encoding="utf-8")
                            restored.append("profile")
                        else:
                            skipped.append("profile (kept existing)")
                    else:
                        PROFILE_FILE.write_text(
                            json.dumps(backup_prof, indent=2),
                            encoding="utf-8")
                        restored.append("profile")

        except (json.JSONDecodeError, OSError, KeyError) as exc:
            log.error("Restore failed: %s", exc)
            QMessageBox.critical(
                win, "Restore Failed",
                f"An error occurred during restore:\n{exc}")
            return

        self.load()
        if self.app.history_tab:
            self.app.history_tab.refresh()
        if self.app.customers_tab:
            self.app.customers_tab.refresh()
        if self.app.templates_tab:
            self.app.templates_tab.refresh()

        summary = ("\n  • ".join(["Restored:"] + restored)
                   if restored else "Nothing new to restore.")
        if skipped:
            summary += "\n\nSkipped:\n  • " + "\n  • ".join(skipped)

        self._backup_status.setText(
            f"Restore complete  ·  "
            f"{datetime.now().strftime('%H:%M')}")
        self._backup_status.setStyleSheet(
            "color:#166534; font-size:11px; background:transparent;"
            " padding-left:12px;")
        log.info("Restore complete: %s", summary)
        QMessageBox.information(win, "Restore Complete", summary)

    # ── Save / Load ───────────────────────────────────────────────────────────

    def save(self):
        name = self.p_name.text().strip()
        if not name:
            QMessageBox.warning(
                self.p_name.window(),
                "Missing Company Name",
                "Company name is required.\n\n"
                "Invoices will use this name as the business header — "
                "please fill it in before saving.")
            self.p_name.setFocus()
            return

        inv_tab = self.app.invoice_tab
        current_items = []
        for desc_w, qty_w, price_w in inv_tab._items:
            desc = desc_w.text().strip()
            if desc:
                try:
                    qty   = float(qty_w.text()   or 1)
                    price = float(price_w.text() or 0)
                except ValueError:
                    qty, price = 1, 0.0
                current_items.append(
                    {"description": desc, "qty": qty, "unit_price": price})

        d = {
            "name":               self.p_name.text(),
            "email":              self.p_email.text(),
            "phone":              self.p_phone.text(),
            "address":            self.p_addr.text(),
            "city":               self.p_city.text(),
            "state":              self.p_state.text(),
            "zip":                self.p_zip.text(),
            "logo":               self._logo_path or "",
            "prefix":             self.p_prefix.text(),
            "output_dir":         self.p_outdir.text(),
            "payment_link":       self.p_payment_link.text().strip(),
            "payment_terms":      self.p_payment_terms.text().strip(),
            "accent_color":       self._accent_color,
            "template":           inv_tab.v_template.currentText(),
            "default_line_items": current_items,
            "smtp": {
                "host": self.p_smtp_host.text().strip(),
                "port": self.p_smtp_port.text().strip() or "587",
                "user": self.p_smtp_user.text().strip(),
                "pass": self.p_smtp_pass.text(),
                "from": self.p_smtp_from.text().strip(),
                "ssl":  self._smtp_ssl_cb.isChecked(),
            },
        }
        existing = load_profile() or {}
        for carry in ("industry", "tax_label", "default_terms",
                      "default_notes"):
            if carry in existing:
                d[carry] = existing[carry]

        save_profile(d)
        log.info("Profile saved")
        QMessageBox.information(
            self.p_name.window(), "Saved", "Profile saved!")
        if self.app.invoice_tab:
            self.app.invoice_tab.schedule_preview()

    def load(self):
        p = load_profile()
        saved_outdir = (p or {}).get("output_dir", "").strip()
        self.p_outdir.setText(
            saved_outdir if saved_outdir else str(get_output_dir()))
        if not p:
            return

        for widget, key in [
            (self.p_name,   "name"),
            (self.p_email,  "email"),
            (self.p_phone,  "phone"),
            (self.p_addr,   "address"),
            (self.p_city,   "city"),
            (self.p_state,  "state"),
            (self.p_zip,    "zip"),
            (self.p_prefix, "prefix"),
        ]:
            widget.setText(p.get(key, ""))

        # Logo
        logo = p.get("logo", "")
        if logo and os.path.exists(logo):
            self._logo_path    = logo
            self.app.logo_path = logo
            self.logo_label.setText(f"  {os.path.basename(logo)}")
            self.logo_label.setStyleSheet(
                "background:#f3f4f6; border-radius:6px; color:#374151;"
                " font-size:12px; padding-left:6px;")
        else:
            self._logo_path    = None
            self.app.logo_path = None

        # Accent color
        saved_accent          = p.get("accent_color", DEFAULT_ACCENT)
        self._accent_color    = normalise(saved_accent)
        self.app.accent_color = self._accent_color
        self.p_accent_hex.setText(self._accent_color)
        self._accent_swatch.setStyleSheet(
            f"background:{self._accent_color}; border-radius:6px; border:none;")
        self._accent_preview_lbl.setText(self._accent_color)
        self._update_swatch_borders(self._accent_color)
        # accent_color is stored for invoice PDF rendering only — not applied to UI

        # Invoice tab defaults
        it = self.app.invoice_tab
        if it is None:          
            return
        saved_tmpl = p.get("template", "")
        if saved_tmpl and saved_tmpl in TEMPLATE_LIST:
            it.v_template.setCurrentText(saved_tmpl)

        saved_tax_label = p.get("tax_label", "")
        if saved_tax_label:
            it.v_tax_label.setText(saved_tax_label)

        saved_link = p.get("payment_link", "")
        self.p_payment_link.setText(saved_link)
        if saved_link:
            it.v_payment_link.setText(saved_link)

        saved_terms = p.get("payment_terms", "")
        self.p_payment_terms.setText(saved_terms)
        if saved_terms:
            it.v_payment_terms.setText(saved_terms)

        saved_notes = p.get("default_notes", "")
        if saved_notes:
            it.v_notes.setPlainText(saved_notes)

        saved_items    = p.get("default_line_items")
        saved_industry = p.get("industry", "")
        items_to_load  = None
        if saved_items:
            items_to_load = saved_items
        elif saved_industry:
            from app.industry_packs import PACKS_BY_ID
            pack = PACKS_BY_ID.get(saved_industry)
            if pack:
                items_to_load = pack.line_items
        if items_to_load:
            it.load_items_from(items_to_load)

        # SMTP settings
        smtp = p.get("smtp", {})
        self.p_smtp_host.setText(smtp.get("host", ""))
        self.p_smtp_port.setText(smtp.get("port", ""))
        self.p_smtp_user.setText(smtp.get("user", ""))
        self.p_smtp_pass.setText(smtp.get("pass", ""))
        self.p_smtp_from.setText(smtp.get("from", ""))
        self._smtp_ssl_cb.setChecked(bool(smtp.get("ssl", False)))

    # ── Called by App._apply_pack ─────────────────────────────────────────────

    def apply_accent(self, hex_val: str):
        self._accent_color    = hex_val
        self.app.accent_color = hex_val
        self.p_accent_hex.setText(hex_val)
        self._accent_swatch.setStyleSheet(
            f"background:{hex_val}; border-radius:6px; border:none;")
        self._accent_preview_lbl.setText(hex_val)
        self._update_swatch_borders(hex_val)
        # accent_color is used by pdf_gen for invoice template colors only

    def apply_tax_label(self, label: str):
        it = self.app.invoice_tab
        if it and hasattr(it, "v_tax_label"):
            it.v_tax_label.setText(label)