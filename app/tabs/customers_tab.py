"""
Customers tab — searchable CRM list with invoice stats.
PySide6 migration: CTk widgets → Qt, pack → QLayout,
CTkToplevel modal → QDialog, StringVar → QLineEdit signals,
CTkScrollableFrame → QScrollArea.
"""
from __future__ import annotations

import csv
import io
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from app.icon_utils import get_icon

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.storage import (
    delete_customer, load_all_customers,
    load_invoices, save_customer,
)

ACCENT = "#2563EB"


def _msg_box(parent, title: str, text: str, kind: str = "info") -> QMessageBox:
    """Styled, shadow-free QMessageBox."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    icon_map = {
        "info":     QMessageBox.Information,
        "warning":  QMessageBox.Warning,
        "critical": QMessageBox.Critical,
        "question": QMessageBox.Question,
    }
    box.setIcon(icon_map.get(kind, QMessageBox.NoIcon))
    box.setStyleSheet(
        "QMessageBox { background: white; border-radius: 8px; }"
        "QMessageBox QLabel { color: #1f2937; font-size: 13px;"
        "  background: white; padding: 4px 0; }"
        "QMessageBox QPushButton { background: #2563EB; color: white;"
        "  border: none; border-radius: 6px; padding: 6px 20px;"
        "  font-weight: 600; min-width: 80px; }"
        "QMessageBox QPushButton:hover { background: #1d4ed8; }"
        "QMessageBox QPushButton[text='Cancel'],"
        "QMessageBox QPushButton[text='No'] {"
        "  background: white; color: #374151;"
        "  border: 1px solid #d1d5db; }"
        "QMessageBox QPushButton[text='Cancel']:hover,"
        "QMessageBox QPushButton[text='No']:hover {"
        "  background: #f9fafb; }")
    return box

def _info(parent, title: str, text: str):
    box = _msg_box(parent, title, text, "info")
    box.exec()

def _alert(parent, title: str, text: str):
    box = _msg_box(parent, title, text, "warning")
    box.exec()

def _critical(parent, title: str, text: str):
    box = _msg_box(parent, title, text, "critical")
    box.exec()

def _confirm(parent, title: str, text: str) -> bool:
    box = _msg_box(parent, title, text, "question")
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def _action_btn(text: str, icon_name: str | None = None,
            w: int = 80, h: int = 28,
            color: str = ACCENT) -> QPushButton:
    btn = QPushButton(f" {text}" if icon_name else text)
    if icon_name:
        btn.setIcon(get_icon(icon_name))
    btn.setFixedSize(w, h)
    btn.setStyleSheet(
        f"QPushButton{{background:{color}; color:white; border:none;"
        f" border-radius:4px; font-size:11px; font-weight:600;}}"
        f"QPushButton:hover{{background:#1d4ed8;}}"
        f"QPushButton:pressed{{background:#1e3a8a;}}"
        f"QPushButton:disabled{{background:#e5e7eb; color:#9ca3af;}}")
    return btn


class CustomersTab:
    """Builds and owns the Customers tab UI (PySide6)."""


    def __init__(self, parent: QWidget, app):
        self.app = app
        self._search_job: QTimer | None = None
        self._build(parent)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self, parent: QWidget):
        root = QVBoxLayout(parent)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        # ── Top bar ───────────────────────────────────────────────────────────
        top = QFrame()
        top.setStyleSheet("background:transparent;")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)

        title = QLabel("Customers")
        title.setStyleSheet(
            "font-size:15px; font-weight:700; color:#1f2937;"
            " background:transparent;")
        tl.addWidget(title)
        tl.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name or email…")
        self._search.setFixedWidth(240)
        self._search.textChanged.connect(self._debounce_search)
        tl.addWidget(self._search)

        imp_btn = _action_btn("Import CSV", "folder", w=120, h=30)
        imp_btn.clicked.connect(self._import_csv)
        tl.addWidget(imp_btn)

        exp_btn = _action_btn("Export CSV", "down-arrow", w=120, h=30)
        exp_btn.clicked.connect(self._export_csv)
        tl.addWidget(exp_btn)

        new_btn = _action_btn("+ New Customer", None, w=150, h=30)
        new_btn.clicked.connect(lambda: self.open_modal())
        tl.addWidget(new_btn)

        root.addWidget(top)

        # ── Column headers ────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame{{background:{ACCENT}; border-radius:6px; border:none;}}")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(10, 7, 10, 7)
        hl.setSpacing(0)

        for txt, w, align in [
            ("Name",         150, Qt.AlignLeft | Qt.AlignVCenter),
            ("Email",        170, Qt.AlignCenter),
            ("Phone",        100, Qt.AlignCenter),
            ("Address",      150, Qt.AlignCenter),
            ("City",          90, Qt.AlignCenter),
            ("State",         60, Qt.AlignCenter),
            ("ZIP",           70, Qt.AlignCenter),
            ("Invoices",      70, Qt.AlignCenter),
            ("Total Billed",  90, Qt.AlignCenter),
            ("Last Invoice",  90, Qt.AlignCenter),
        ]:
            lbl = QLabel(txt)
            lbl.setFixedWidth(w)
            lbl.setAlignment(align)
            lbl.setStyleSheet(
                "color:white; font-size:11px; font-weight:700;"
                " background:transparent;")
            hl.addWidget(lbl)

        hl.addStretch()
        root.addWidget(hdr)

        # ── Scroll area ───────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea{background:#f3f4f6; border:none;}")
        root.addWidget(self._scroll)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background:#f3f4f6;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 2, 0, 2)
        self._list_layout.setSpacing(3)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._list_widget)

        self.refresh()

    # ── Search debounce ───────────────────────────────────────────────────────

    def _debounce_search(self):
        if self._search_job:
            self._search_job.stop()
        self._search_job = QTimer()
        self._search_job.setSingleShot(True)
        self._search_job.timeout.connect(self.refresh)
        self._search_job.start(300)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        # Clear all rows
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query  = self._search.text().strip().lower()
        all_c  = load_all_customers()
        shown  = [c for c in all_c
                  if not query
                  or query in c.get("name",  "").lower()
                  or query in c.get("email", "").lower()]

        # Build invoice lookup once
        all_inv = load_invoices()
        inv_by_client: dict[str, list] = {}
        for i in all_inv:
            key = i.get("client", "").lower()
            inv_by_client.setdefault(key, []).append(i)

        if not shown:
            empty = QFrame()
            empty.setStyleSheet(
                "QFrame{background:white; border-radius:8px; border:none;}")
            el = QVBoxLayout(empty)
            el.setContentsMargins(12, 28, 12, 28)
            lbl = QLabel(
                "  No customers yet — add one or generate an invoice "
                "to auto-save a client.")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                "color:#9ca3af; font-size:13px; background:transparent;")
            el.addWidget(lbl)
            self._list_layout.addWidget(empty)
            return

        for c in shown:
            cust_inv = inv_by_client.get(c.get("name", "").lower(), [])
            self._row(c, cust_inv)

    # ── Row ───────────────────────────────────────────────────────────────────

    def _row(self, c: dict, cust_inv: list):
        inv_count = len(cust_inv)
        inv_total = sum(float(i.get("total", 0)) for i in cust_inv)
        sym = ({"USD": "$", "EUR": "€", "GBP": "£",
                "CAD": "$", "AUD": "$"}.get(
            cust_inv[-1].get("currency", "USD"), "$")
            if cust_inv else "$")
        last_date = max(
            (i.get("issue_date", "") for i in cust_inv), default="—")

        row = QFrame()
        row.setStyleSheet(
            "QFrame{background:white; border-radius:6px; border:none;}")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setFixedHeight(44)

        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 0, 8, 0)
        rl.setSpacing(0)

        def _cell(text: str, width: int,
                  accent: bool = False, muted: bool = False,
                  bold: bool = False,
                  align: Qt.AlignmentFlag = Qt.AlignCenter) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            style = "background:transparent; "
            if accent:
                style += f"color:{ACCENT}; font-weight:700; font-size:11px;"
            elif bold:
                style += f"color:{ACCENT}; font-weight:700; font-size:11px;"
            elif muted:
                style += "color:#9ca3af; font-size:11px;"
            else:
                style += "color:#6b7280; font-size:11px;"
            lbl.setStyleSheet(style)
            lbl.setAlignment(align)
            return lbl

        rl.addWidget(_cell(c.get("name",  "—"), 150,
                           accent=True, align=Qt.AlignLeft | Qt.AlignVCenter))
        rl.addWidget(_cell(c.get("email", "—"), 170, muted=True))
        rl.addWidget(_cell(c.get("phone", "—"), 100, muted=True))
        rl.addWidget(_cell(c.get("address", "—"), 150, muted=True))
        rl.addWidget(_cell(c.get("city",    "—"),  90, muted=True))
        rl.addWidget(_cell(c.get("state",   "—"),  60, muted=True))
        rl.addWidget(_cell(c.get("zip",     "—"),  70, muted=True))
        rl.addWidget(_cell(
            f"{inv_count} inv." if inv_count else "—", 70,
            accent=bool(inv_count), muted=not inv_count))
        rl.addWidget(_cell(
            f"{sym}{inv_total:,.2f}" if inv_count else "—", 90,
            bold=bool(inv_count), muted=not inv_count))
        rl.addWidget(_cell(last_date, 90, muted=True))
        rl.addStretch()

        # Action buttons — spaced like history tab
        btn_row = QWidget(); btn_row.setStyleSheet("background:transparent;")
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0); btn_layout.setSpacing(4)

        use_btn = _action_btn("Use", None, w=64, h=26)
        use_btn.clicked.connect(lambda _, customer=c: self._use(customer))
        btn_layout.addWidget(use_btn)

        edit_btn = _action_btn("Edit", "edit", w=80, h=26)
        edit_btn.clicked.connect(lambda _, customer=c: self.open_modal(customer))
        btn_layout.addWidget(edit_btn)

        del_btn = QPushButton()
        del_btn.setIcon(get_icon("delete"))
        del_btn.setFixedSize(28, 26)
        del_btn.setStyleSheet(
            "QPushButton{background:#fee2e2; border:none; border-radius:4px;}"
            "QPushButton:hover{background:#f72d2d;}")
        del_btn.clicked.connect(lambda _, cid=c["id"]: self._delete(cid))
        btn_layout.addWidget(del_btn)

        rl.addWidget(btn_row)
        self._list_layout.addWidget(row)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _use(self, c: dict):
        it = self.app.invoice_tab
        it.v_client_name.setText(c.get("name",    ""))
        it.v_client_email.setText(c.get("email",   ""))
        it.v_client_phone.setText(c.get("phone",   ""))
        it.v_client_addr.setText(c.get("address", ""))
        it.v_client_city.setText(c.get("city",    ""))
        it.v_client_state.setText(c.get("state",   ""))
        it.v_client_zip.setText(c.get("zip",     ""))
        it.schedule_preview()
        self.app._win.set_tab("Invoice")

    def _delete(self, customer_id: str):
        if _confirm(self._scroll.window(), "Delete Customer",
                    "Remove this customer? This cannot be undone."):
            delete_customer(customer_id)
            self.refresh()

    def _export_csv(self):
        win = self._scroll.window()
        customers = load_all_customers()
        if not customers:
            _alert(win, "Nothing to Export", "No customers to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            win, "Export Customers", "customers.csv",
            "CSV files (*.csv);;All files (*.*)")
        if not path:
            return
        columns = ["name","email","phone","address","city","state","zip","notes"]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(customers)
            n = len(customers)
            _info(win, "Export Complete",
                  f"Exported {n} customer{'s' if n != 1 else ''} to:\n{path}")
        except OSError as exc:
            _critical(win, "Export Failed", str(exc))

    def _import_csv(self):
        win = self._scroll.window()
        path, _ = QFileDialog.getOpenFileName(
            win, "Import Customers from CSV", "",
            "CSV files (*.csv);;All files (*.*)")
        if not path:
            return
        required = {"name"}
        added = skipped = 0
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or not required.issubset(
                        {h.lower() for h in reader.fieldnames}):
                    _critical(win, "Invalid CSV",
                               "CSV must have at least a 'name' column.")
                    return
                # Normalise header keys to lowercase
                for raw in reader:
                    row = {k.lower(): v.strip() for k, v in raw.items()}
                    name = row.get("name", "").strip()
                    if not name:
                        skipped += 1
                        continue
                    save_customer({
                        "id":      "",
                        "name":    name,
                        "email":   row.get("email",   ""),
                        "phone":   row.get("phone",   ""),
                        "address": row.get("address", ""),
                        "city":    row.get("city",    ""),
                        "state":   row.get("state",   ""),
                        "zip":     row.get("zip",     ""),
                        "notes":   row.get("notes",   ""),
                    })
                    added += 1
        except OSError as exc:
            _critical(win, "Import Failed", str(exc))
            return
        self.refresh()
        msg = f"Imported {added} customer{'s' if added != 1 else ''}."
        if skipped:
            msg += f"  {skipped} row{'s' if skipped != 1 else ''} skipped (missing name)."
        _info(win, "Import Complete", msg)

    # ── Modal ─────────────────────────────────────────────────────────────────

    def open_modal(self, existing: dict | None = None):
        win = self._scroll.window()
        ex  = existing or {}

        dlg = QDialog(win)
        dlg.setWindowTitle("Edit Customer" if existing else "New Customer")
        dlg.setFixedWidth(440)
        dlg.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 14, 20, 14)
        hdr_lbl = QLabel("Edit Customer" if existing else "New Customer")
        hdr_lbl.setAlignment(Qt.AlignCenter)
        hdr_lbl.setStyleSheet(
            "color:white; font-size:15px; font-weight:700;"
            " background:transparent;")
        hl.addWidget(hdr_lbl)
        layout.addWidget(hdr)

        # ── Form ──────────────────────────────────────────────────────────────
        form = QWidget()
        form.setStyleSheet("background:white;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(20, 12, 20, 8)
        fl.setSpacing(4)

        def _field(label: str, value: str = "") -> QLineEdit:
            lbl = QLabel(label)
            lbl.setStyleSheet(
                "font-size:12px; color:#374151; background:transparent;")
            fl.addWidget(lbl)
            entry = QLineEdit(value)
            entry.setFixedHeight(34)
            fl.addWidget(entry)
            return entry

        f_name    = _field("Name *",  ex.get("name",    ""))
        f_email   = _field("Email",   ex.get("email",   ""))
        f_phone   = _field("Phone",   ex.get("phone",   ""))
        f_address = _field("Address", ex.get("address", ""))

        # City / State / ZIP row
        csz_lbl = QLabel("City / State / ZIP")
        csz_lbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        fl.addWidget(csz_lbl)

        csz_row = QWidget()
        csz_row.setStyleSheet("background:transparent;")
        csz_layout = QGridLayout(csz_row)
        csz_layout.setContentsMargins(0, 0, 0, 0)
        csz_layout.setSpacing(6)
        csz_layout.setColumnStretch(0, 3)
        csz_layout.setColumnStretch(1, 1)
        csz_layout.setColumnStretch(2, 1)

        f_city  = QLineEdit(ex.get("city",  ""))
        f_state = QLineEdit(ex.get("state", ""))
        f_zip   = QLineEdit(ex.get("zip",   ""))

        for col, (widget, placeholder) in enumerate([
            (f_city,  "City"),
            (f_state, "State"),
            (f_zip,   "ZIP"),
        ]):
            widget.setPlaceholderText(placeholder)
            widget.setFixedHeight(34)
            csz_layout.addWidget(widget, 0, col)

        fl.addWidget(csz_row)

        # Notes
        notes_lbl = QLabel("Notes")
        notes_lbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        fl.addWidget(notes_lbl)
        f_notes = QPlainTextEdit()
        f_notes.setFixedHeight(70)
        f_notes.setPlainText(ex.get("notes", ""))
        fl.addWidget(f_notes)

        layout.addWidget(form)

        # ── Footer ────────────────────────────────────────────────────────────
        foot = QFrame()
        foot.setStyleSheet(
            "background:white; border-top:1px solid #f3f4f6;")
        footl = QHBoxLayout(foot)
        footl.setContentsMargins(20, 8, 20, 16)
        footl.setSpacing(8)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(100, 32)
        cancel_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#f9fafb;}")
        cancel_btn.clicked.connect(dlg.reject)
        footl.addWidget(cancel_btn)
        footl.addStretch()

        save_btn = _action_btn("Save Customer", "save", w=150, h=32)
        footl.addWidget(save_btn)

        layout.addWidget(foot)

        def on_save():
            name = f_name.text().strip()
            if not name:
                _alert(dlg, "Missing Name", "Name is required.")
                return
            save_customer({
                "id":      ex.get("id", ""),
                "name":    name,
                "email":   f_email.text().strip(),
                "phone":   f_phone.text().strip(),
                "address": f_address.text().strip(),
                "city":    f_city.text().strip(),
                "state":   f_state.text().strip(),
                "zip":     f_zip.text().strip(),
                "notes":   f_notes.toPlainText().strip(),
            })
            self.refresh()
            dlg.accept()

        save_btn.clicked.connect(on_save)

        # Centre over parent window
        dlg.adjustSize()
        px = win.x() + (win.width()  - dlg.width())  // 2
        py = win.y() + (win.height() - dlg.height()) // 2
        dlg.move(px, py)
        dlg.exec()