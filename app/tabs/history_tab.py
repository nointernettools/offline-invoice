"""
History tab — invoice list, bulk actions, stats summary, send dialog.
PySide6 migration: CTk → Qt, BooleanVar checkboxes → QCheckBox dict,
CTkInputDialog → QInputDialog, CTkToplevel modals → QDialog,
CTkScrollableFrame → QScrollArea, toast → QLabel overlay.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from app.icon_utils import get_icon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.pdf_gen import WEASY_TEMPLATES
from app.storage import INVOICE_FILE, load_invoices

ACCENT        = "#2563EB"
TEMPLATE_LIST = list(WEASY_TEMPLATES.keys())

CURRENCIES = {
    "USD ($)": ("USD", "$"),
    "EUR (€)": ("EUR", "€"),
    "GBP (£)": ("GBP", "£"),
    "CAD ($)": ("CAD", "$"),
    "AUD ($)": ("AUD", "$"),
}

log = logging.getLogger(__name__)

# Alternating row colors for Excel-style table
ROW_ODD  = "#ffffff"
ROW_EVEN = "#f8fafc"
ROW_OVER = "#fff1f2"
ROW_OVER_EVEN = "#ffe4e6"


def _effective_status(inv: dict, today: date) -> str:
    s = inv.get("status", "Sent")
    if s == "Sent":
        try:
            if datetime.strptime(inv["due_date"], "%Y-%m-%d").date() < today:
                return "Overdue"
        except Exception:
            pass
    return s


def _action_btn(text: str, icon_name: str | None = None,
                w: int = 72, h: int = 26,
                color: str = ACCENT) -> QPushButton:
    """Accent-colored action button that bypasses flat/unpolish issues."""
    btn = QPushButton(f" {text}" if icon_name else text)
    if icon_name:
        btn.setIcon(get_icon(icon_name))
    btn.setFixedSize(w, h)
    btn.setStyleSheet(
        f"QPushButton{{background:{color}; color:white; border:none;"
        f" border-radius:4px; font-size:10px; font-weight:600;}}"
        f"QPushButton:hover{{background:#1d4ed8;}}"
        f"QPushButton:pressed{{background:#1e3a8a;}}"
        f"QPushButton:disabled{{background:#e5e7eb; color:#9ca3af;}}")
    return btn


# ── Tab ───────────────────────────────────────────────────────────────────────

class HistoryTab:

    def __init__(self, parent: QWidget, app):
        self.app = app
        self._row_checks: dict[str, QCheckBox] = {}
        self._search_job: QTimer | None = None
        self._current_filter = "All"
        self._filter_btns: dict[str, QPushButton] = {}
        self._build(parent)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self, parent: QWidget):
        from app.storage import get_output_dir

        root = QVBoxLayout(parent)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(4)

        # ── Top bar ───────────────────────────────────────────────────────────
        top = QFrame()
        top.setStyleSheet(
            "QFrame{background:white; border-radius:8px; border:none;}")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 10, 8); tl.setSpacing(6)

        title = QLabel("Invoice History")
        title.setStyleSheet(
            "font-size:14px; font-weight:700; color:#1f2937;"
            " background:transparent;")
        tl.addWidget(title)
        tl.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by client…")
        self._search.setFixedWidth(200)
        self._search.textChanged.connect(self._debounce_search)
        tl.addWidget(self._search)

        for txt, icon_name, cmd in [
            ("Export CSV", "down-arrow", self._export_csv),
            ("Refresh",    "refresh",    self.refresh),
            ("Folder",     "folder",
             lambda: self.app.invoice_tab._open_file(
                 str(get_output_dir()))),
        ]:
            btn = _action_btn(txt, icon_name, w=120, h=28)
            btn.clicked.connect(cmd)
            tl.addWidget(btn)

        root.addWidget(top)

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = QWidget(); fbar.setStyleSheet("background:transparent;")
        fl = QHBoxLayout(fbar)
        fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(4)

        for label in ("All", "Paid", "Sent", "Draft", "Overdue"):
            btn = QPushButton(label)
            btn.setFixedSize(80, 26)
            if label == "All":
                btn.setStyleSheet(
                    f"QPushButton{{background:{ACCENT}; color:white;"
                    f" border:none; border-radius:4px; font-size:11px;}}"
                    f"QPushButton:hover{{background:#1d4ed8;}}")
            else:
                btn.setStyleSheet(
                    "QPushButton{background:#e5e7eb; color:#374151;"
                    " border:none; border-radius:4px; font-size:11px;}"
                    "QPushButton:hover{background:#d1d5db;}")
            btn.clicked.connect(lambda _, l=label: self._set_filter(l))
            fl.addWidget(btn)
            self._filter_btns[label] = btn

        fl.addStretch()
        root.addWidget(fbar)

        # ── Bulk toolbar ──────────────────────────────────────────────────────
        bulk = QFrame()
        bulk.setFixedHeight(34)
        bulk.setStyleSheet(
            "QFrame{background:white; border-radius:6px; border:none;}")
        bl = QHBoxLayout(bulk)
        bl.setContentsMargins(8, 4, 8, 4); bl.setSpacing(4)

        self._sel_all_cb = QCheckBox("All")
        self._sel_all_cb.setStyleSheet(
            "font-size:11px; background:transparent;")
        self._sel_all_cb.stateChanged.connect(self._on_select_all)
        bl.addWidget(self._sel_all_cb)

        div = QFrame(); div.setFixedSize(1, 20)
        div.setStyleSheet("background:#e5e7eb;")
        bl.addWidget(div)

        for txt, icon_name, color, cmd in [
            ("Paid",   "paid",   "#166534", lambda: self._bulk_status("Paid")),
            ("Sent",   "sent",   "#1e40af", lambda: self._bulk_status("Sent")),
            ("Delete", "delete", "#dc2626", self._bulk_delete),
        ]:
            b = _action_btn(txt, icon_name, w=100, h=24, color=color)
            b.clicked.connect(cmd)
            bl.addWidget(b)

        self._sel_count_lbl = QLabel("0 selected")
        self._sel_count_lbl.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        bl.addWidget(self._sel_count_lbl)
        bl.addStretch()
        root.addWidget(bulk)

        # ── Column headers ────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame{{background:{ACCENT}; border-radius:6px 6px 0 0;"
            f" border:none;}}")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 6, 8, 6); hl.setSpacing(0)

        cb_sp = QWidget(); cb_sp.setFixedWidth(36)
        cb_sp.setStyleSheet("background:transparent;")
        hl.addWidget(cb_sp)

        # (text, width, align)
        for txt, w, align in [
            ("Invoice #", 100, Qt.AlignCenter),
            ("Client",    160, Qt.AlignVCenter),
            ("Amount",     90, Qt.AlignCenter),
            ("Received",   90, Qt.AlignCenter),
            ("Status",     80, Qt.AlignCenter),
            ("Issued",     90, Qt.AlignCenter),
            ("Due",        90, Qt.AlignCenter),
        ]:
            lbl = QLabel(txt); lbl.setFixedWidth(w)
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
            "QScrollArea{background:white; border:1px solid #e5e7eb;"
            " border-top:none; border-radius:0 0 6px 6px;}")
        root.addWidget(self._scroll, stretch=1)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background:white;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._list_widget)

        # ── Stats bar ─────────────────────────────────────────────────────────
        summary = QFrame()
        summary.setStyleSheet(
            "QFrame{background:white; border-radius:6px; border:none;}")
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(8, 6, 8, 6); sl.setSpacing(0)

        self._stats: dict[str, QLabel] = {}

        def _stat(key: str, heading: str):
            lbl_h = QLabel(f"{heading}:")
            lbl_h.setStyleSheet(
                "color:#9ca3af; font-size:11px; background:transparent;"
                " padding:0 2px 0 10px;")
            sl.addWidget(lbl_h)
            lbl_v = QLabel("—")
            lbl_v.setStyleSheet(
                f"color:{ACCENT}; font-size:11px; font-weight:700;"
                " background:transparent;")
            sl.addWidget(lbl_v)
            self._stats[key] = lbl_v

        def _div():
            d = QLabel("·")
            d.setStyleSheet(
                "color:#d1d5db; font-size:11px; background:transparent;"
                " padding:0 6px;")
            sl.addWidget(d)

        _stat("count",   "Invoices");  _div()
        _stat("billed",  "Total Billed"); _div()
        _stat("largest", "Largest");   _div()
        _stat("client",  "Top Client"); _div()
        _stat("ltv",     "Avg. Value"); _div()
        _stat("avgdays", "Avg. Days")
        sl.addStretch()

        root.addWidget(summary)

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
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._row_checks = {}
        self._sel_all_cb.setChecked(False)
        self._sel_count_lbl.setText("0 selected")

        self._migrate_records()

        query    = self._search.text().strip().lower()
        status_f = self._current_filter
        all_inv  = load_invoices()
        today    = date.today()

        shown = []
        for i in reversed(all_inv):
            if query and query not in i.get("client", "").lower():
                continue
            eff = _effective_status(i, today)
            if status_f == "All":
                pass
            elif status_f == "Sent":
                if eff not in ("Sent", "Overdue"):
                    continue
            elif eff != status_f:
                continue
            shown.append(i)

        # Stats
        sym = "$"
        if all_inv:
            sym = {"USD": "$", "EUR": "€", "GBP": "£",
                   "CAD": "$", "AUD": "$"}.get(
                all_inv[-1].get("currency", "USD"), "$")
        totals   = [float(i.get("total", 0)) for i in all_inv]
        billed   = sum(totals)
        largest  = max(totals, default=0)
        avg_val  = billed / len(totals) if totals else 0
        day_gaps = []
        for i in all_inv:
            try:
                iss = datetime.strptime(i["issue_date"], "%Y-%m-%d").date()
                due = datetime.strptime(i["due_date"],   "%Y-%m-%d").date()
                day_gaps.append((due - iss).days)
            except Exception:
                pass
        avg_days = round(sum(day_gaps) / len(day_gaps)) if day_gaps else 0
        ct: dict[str, float] = {}
        for i in all_inv:
            c = i.get("client", "")
            ct[c] = ct.get(c, 0) + float(i.get("total", 0))
        top = max(ct, key=ct.get) if ct else "—"
        if len(top) > 16:
            top = top[:14] + "…"
        count_txt = f"{len(all_inv)} invoice{'s' if len(all_inv) != 1 else ''}"
        if query or status_f != "All":
            count_txt += f" ({len(shown)} shown)"

        self._stats["count"].setText(count_txt)
        self._stats["billed"].setText(f"{sym}{billed:,.2f}")
        self._stats["largest"].setText(f"{sym}{largest:,.2f}" if largest else "—")
        self._stats["client"].setText(top)
        self._stats["ltv"].setText(f"{sym}{avg_val:,.2f}" if avg_val else "—")
        self._stats["avgdays"].setText(f"{avg_days}d" if avg_days else "—")

        if not shown:
            empty = QFrame()
            empty.setStyleSheet("QFrame{background:white; border:none;}")
            el = QVBoxLayout(empty); el.setContentsMargins(12, 28, 12, 28)
            msg = ("📄  No invoices yet"
                   if not (query or status_f != "All")
                   else "📄  No matching invoices")
            lbl = QLabel(msg)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(
                "color:#9ca3af; font-size:13px; background:transparent;")
            el.addWidget(lbl)
            self._list_layout.addWidget(empty)
            return

        for idx, inv in enumerate(shown):
            rk = (f"{inv.get('number', '')}_{inv.get('client', '')}"
                  f"_{inv.get('issue_date', '')}_{idx}")
            self._row(inv, _effective_status(inv, today), rk, idx)

    # ── Row ───────────────────────────────────────────────────────────────────

    def _row(self, inv: dict, status: str, row_key: str, idx: int):
        is_over = status == "Overdue"

        # Alternating Excel-style row color
        if is_over:
            bg = ROW_OVER_EVEN if idx % 2 else ROW_OVER
        else:
            bg = ROW_EVEN if idx % 2 else ROW_ODD

        row = QFrame()
        row.setStyleSheet(f"QFrame{{background:{bg}; border:none;}}")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setFixedHeight(40)

        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 0, 8, 0); rl.setSpacing(4)

        # Checkbox
        cb = QCheckBox()
        cb.setFixedWidth(36)
        cb.setStyleSheet("background:transparent;")
        cb.stateChanged.connect(self._update_sel_count)
        self._row_checks[row_key] = cb
        rl.addWidget(cb)

        def _cell(text: str, width: int,
                  accent: bool = False, muted: bool = False,
                  danger: bool = False,
                  align: Qt.AlignmentFlag = Qt.AlignCenter) -> QLabel:
            lbl = QLabel(text); lbl.setFixedWidth(width)
            style = f"background:transparent; font-size:11px; "
            if danger:
                style += "color:#dc2626; font-weight:700;"
            elif accent:
                style += f"color:{ACCENT}; font-weight:700;"
            elif muted:
                style += "color:#9ca3af;"
            else:
                style += "color:#374151;"
            lbl.setStyleSheet(style)
            lbl.setAlignment(align)
            return lbl

        rl.addWidget(_cell(
            inv.get("number", "—"), 100,
            danger=is_over, accent=not is_over))
        rl.addWidget(_cell(
            inv.get("client", "—"), 160,
            align=Qt.AlignLeft | Qt.AlignVCenter))

        sym = {"USD": "$", "EUR": "€", "GBP": "£",
               "CAD": "$", "AUD": "$"}.get(
            inv.get("currency", "USD"), "$")
        try:
            amt = f"{sym}{float(inv.get('total', 0)):,.2f}"
        except (ValueError, TypeError):
            amt = f"{sym}—"
        rl.addWidget(_cell(amt, 90, accent=True))

        # Received cell — sum of logged payments
        payments = inv.get("payments", [])
        paid_sum = sum(float(p.get("amount", 0)) for p in payments)
        total_val = float(inv.get("total", 0)) if inv.get("total") else 0
        if payments:
            if paid_sum >= total_val > 0:
                recv_text = f"{sym}{paid_sum:,.2f}"
                recv_color = "#166534"  # green — fully paid
            else:
                recv_text = f"{sym}{paid_sum:,.2f}"
                recv_color = "#92400e"  # amber — partial
        else:
            recv_text = "—"
            recv_color = None

        recv_container = QWidget()
        recv_container.setFixedWidth(90)
        recv_l = QHBoxLayout(recv_container)
        recv_l.setContentsMargins(0, 0, 0, 0)
        recv_l.setAlignment(Qt.AlignCenter)

        recv_lbl = QLabel(recv_text)
        recv_lbl.setStyleSheet(
            f"background:transparent; font-size:11px; font-weight:700;"
            f" color:{recv_color if recv_color else '#9ca3af'};"
        )
        recv_l.addWidget(recv_lbl)

        if payments and paid_sum >= total_val > 0:
            verified_icon = QLabel()
            verified_icon.setPixmap(get_icon("verified").pixmap(20, 20))
            verified_icon.setStyleSheet("background:transparent;")
            recv_l.addWidget(verified_icon)

        rl.addWidget(recv_container)

        # Separator line
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #e5e7eb;")
        self._list_layout.addWidget(line)

        # Status badge
        STATUS_COLORS = {
            "Paid":    ("#dcfce7", "#166534"),
            "Sent":    ("#dbeafe", "#1e40af"),
            "Draft":   ("#f3f4f6", "#6b7280"),
            "Overdue": ("#fee2e2", "#991b1b"),
        }
        bg_b, fg = STATUS_COLORS.get(status, ("#f3f4f6", "#6b7280"))
        badge = QPushButton(status)
        badge.setFixedSize(72, 22)
        badge.setStyleSheet(
            f"QPushButton{{background:{bg_b}; color:{fg}; border:none;"
            f" border-radius:10px; font-size:10px; font-weight:700;}}"
            f"QPushButton:hover{{opacity:0.85;}}")
        badge.clicked.connect(lambda _, i=inv: self._cycle_status(i))
        rl.addWidget(badge)

        rl.addWidget(_cell(inv.get("issue_date", "—"), 90, muted=True))
        rl.addWidget(_cell(
            inv.get("due_date", "—"), 90,
            danger=is_over, muted=not is_over))
        rl.addStretch()

        # ── Action buttons ────────────────────────────────────────────────────
        pay_btn = _action_btn("Pay", "dollarbag", w=70, h=26, color="#166534")
        pay_btn.clicked.connect(lambda _, i=inv: self._open_payments_modal(i))
        rl.addWidget(pay_btn)

        send_btn = _action_btn("Send", "send", w=72, h=26, color="#0f766e")
        send_btn.clicked.connect(lambda _, i=inv: self._send_invoice(i))
        rl.addWidget(send_btn)

        pdf_ok = bool(inv.get("pdf_path")) and os.path.exists(
            inv.get("pdf_path", ""))
        open_btn = _action_btn("PDF", None, w=56, h=26,
                               color=ACCENT if pdf_ok else "#9ca3af")
        open_btn.setEnabled(pdf_ok)
        open_btn.clicked.connect(
            lambda _, p=inv.get("pdf_path"):
            self.app.invoice_tab._open_file(p))
        rl.addWidget(open_btn)

        tmpl_btn = _action_btn("Template", "star", w=100, h=26)
        tmpl_btn.clicked.connect(lambda _, i=inv: self._save_as_template(i))
        rl.addWidget(tmpl_btn)

        dup_btn = _action_btn("Duplicate", "duplicate", w=100, h=26)
        dup_btn.clicked.connect(lambda _, i=inv: self._duplicate(i))
        rl.addWidget(dup_btn)

        edit_btn = _action_btn("Edit", "edit", w=64, h=26)
        edit_btn.clicked.connect(lambda _, i=inv: self._open_edit_modal(i))
        rl.addWidget(edit_btn)

        del_btn = QPushButton()
        del_btn.setIcon(get_icon("delete"))
        del_btn.setFixedSize(28, 26)
        del_btn.setStyleSheet(
            "QPushButton{background:#fee2e2; border:none; border-radius:4px;}"
            "QPushButton:hover{background:#f72d2d;}")
        del_btn.clicked.connect(lambda _, i=inv: self._delete_one(i))
        rl.addWidget(del_btn)

        self._list_layout.addWidget(row)

    # ── Selection helpers ─────────────────────────────────────────────────────

    def _update_sel_count(self):
        sel = sum(1 for cb in self._row_checks.values() if cb.isChecked())
        tot = len(self._row_checks)
        self._sel_count_lbl.setText(
            f"{sel} selected" if sel else "0 selected")
        self._sel_all_cb.blockSignals(True)
        self._sel_all_cb.setChecked(sel == tot and tot > 0)
        self._sel_all_cb.blockSignals(False)

    def _on_select_all(self, state: int):
        checked = bool(state)
        for cb in self._row_checks.values():
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        sel = len(self._row_checks) if checked else 0
        self._sel_count_lbl.setText(
            f"{sel} selected" if sel else "0 selected")

    def _get_selected(self) -> list[dict]:
        all_inv  = load_invoices()
        today    = date.today()
        query    = self._search.text().strip().lower()
        status_f = self._current_filter
        shown = []
        for i in reversed(all_inv):
            if query and query not in i.get("client", "").lower():
                continue
            eff = _effective_status(i, today)
            if status_f == "All":
                pass
            elif status_f == "Sent":
                if eff not in ("Sent", "Overdue"):
                    continue
            elif eff != status_f:
                continue
            shown.append(i)
        selected = []
        for idx, inv in enumerate(shown):
            rk = (f"{inv.get('number', '')}_{inv.get('client', '')}"
                  f"_{inv.get('issue_date', '')}_{idx}")
            cb = self._row_checks.get(rk)
            if cb and cb.isChecked():
                selected.append(inv)
        return selected

    # ── Filter ────────────────────────────────────────────────────────────────

    def _set_filter(self, label: str):
        self._current_filter = label
        for lbl, btn in self._filter_btns.items():
            if lbl == label:
                btn.setStyleSheet(
                    f"QPushButton{{background:{ACCENT}; color:white;"
                    f" border:none; border-radius:4px; font-size:11px;}}"
                    f"QPushButton:hover{{background:#1d4ed8;}}")
            else:
                btn.setStyleSheet(
                    "QPushButton{background:#e5e7eb; color:#374151;"
                    " border:none; border-radius:4px; font-size:11px;}"
                    "QPushButton:hover{background:#d1d5db;}")
        self.refresh()

    # ── Bulk actions ──────────────────────────────────────────────────────────

    def _bulk_status(self, new_status: str):
        targets = self._get_selected()
        if not targets:
            QMessageBox.warning(
                self._scroll, "No Selection",
                "Check at least one invoice first.")
            return
        all_inv = load_invoices()
        keys = {(i.get("number"), i.get("client"), i.get("issue_date"))
                for i in targets}
        for i in all_inv:
            if (i.get("number"), i.get("client"),
                    i.get("issue_date")) in keys:
                i["status"] = new_status
        self._write(all_inv)
        self.refresh()

    def _bulk_delete(self):
        targets = self._get_selected()
        if not targets:
            QMessageBox.warning(
                self._scroll, "No Selection",
                "Check at least one invoice first.")
            return
        n = len(targets)
        reply = QMessageBox.question(
            self._scroll, "Delete Selected",
            f"Permanently delete {n} invoice{'s' if n > 1 else ''} "
            f"and their PDF files?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        for inv in targets:
            pdf = inv.get("pdf_path", "")
            if pdf and os.path.exists(pdf):
                try:
                    os.remove(pdf)
                except OSError:
                    pass
        keys = {(i.get("number"), i.get("client"), i.get("issue_date"))
                for i in targets}
        self._write([i for i in load_invoices()
                     if (i.get("number"), i.get("client"),
                         i.get("issue_date")) not in keys])
        self.refresh()

    # ── Individual actions ────────────────────────────────────────────────────

    def _cycle_status(self, inv: dict):
        stored = inv.get("status", "Sent")
        inv["status"] = {
            "Draft": "Sent", "Sent": "Paid",
            "Paid": "Sent", "Overdue": "Paid",
        }.get(stored, "Sent")
        self._save_status(inv)
        self.refresh()

    def _delete_one(self, inv: dict):
        pdf_path   = inv.get("pdf_path", "")
        pdf_exists = bool(pdf_path) and os.path.exists(pdf_path)
        msg = (f"Delete invoice {inv.get('number', '?')}?\n\n"
               "This will remove the record from history"
               + (" and permanently delete the PDF file from disk."
                  if pdf_exists else "."))
        reply = QMessageBox.question(
            self._scroll, "Delete Invoice", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        if pdf_exists:
            try:
                os.remove(pdf_path)
            except OSError:
                pass
        self._write([
            i for i in load_invoices()
            if not (i.get("number")     == inv.get("number") and
                    i.get("client")     == inv.get("client") and
                    i.get("issue_date") == inv.get("issue_date"))])
        self.refresh()

    def _duplicate(self, inv: dict):
        all_inv = load_invoices()
        fresh   = next(
            (r for r in all_inv
             if r.get("number")      == inv.get("number")
             and r.get("client")     == inv.get("client")
             and r.get("issue_date") == inv.get("issue_date")),
            inv)
        it = self.app.invoice_tab

        def st(w, v): w.setText(str(v) if v else "")

        st(it.v_client_name,  fresh.get("client",          ""))
        st(it.v_client_email, fresh.get("client_email",    ""))
        st(it.v_client_phone, fresh.get("client_phone",    ""))
        st(it.v_client_addr,  fresh.get("client_address",  ""))
        st(it.v_client_city,  fresh.get("client_city",     ""))
        st(it.v_client_state, fresh.get("client_state",    ""))
        st(it.v_client_zip,   fresh.get("client_zip",      ""))

        today = date.today()
        try:
            iss    = datetime.strptime(fresh["issue_date"], "%Y-%m-%d").date()
            due    = datetime.strptime(fresh["due_date"],   "%Y-%m-%d").date()
            window = max((due - iss).days, 1)
        except Exception:
            window = 30
        st(it.v_issue,   str(today))
        st(it.v_due,     str(today + timedelta(days=window)))
        st(it.v_inv_num, "")

        tmpl = fresh.get("template", "")
        if tmpl and tmpl in TEMPLATE_LIST:
            it.v_template.setCurrentText(tmpl)

        currency = fresh.get("currency", "USD")
        for key, (code, _) in CURRENCIES.items():
            if code == currency:
                it.v_currency.setCurrentText(key)
                break

        st(it.v_tax,           str(fresh.get("tax_rate",   0)))
        st(it.v_tax_label,     fresh.get("tax_label",      "Tax"))
        st(it.v_discount,      str(fresh.get("discount",   0)))
        st(it.v_payment_link,  fresh.get("payment_link",   ""))
        st(it.v_payment_terms, fresh.get("payment_terms",  ""))
        it.v_notes.setPlainText(fresh.get("notes", ""))
        it.v_filename.clear()

        line_items = fresh.get("line_items", [])
        if line_items:
            it.load_items_from(line_items)
        else:
            it.clear_items()
            it.add_item_row()

        it.refresh_totals()
        it.schedule_preview()
        self.app._win.set_tab("Invoice")

    def _save_as_template(self, inv: dict):
        from app.storage import save_template, load_invoices as _li
        all_inv = _li()
        fresh   = next(
            (r for r in all_inv
             if r.get("number")      == inv.get("number")
             and r.get("client")     == inv.get("client")
             and r.get("issue_date") == inv.get("issue_date")),
            inv)
        win = self._scroll.window()
        name, ok = QInputDialog.getText(
            win, "Save as Template",
            f"Name this template:\n"
            f"(e.g. 'Monthly Retainer – {fresh.get('client', '')}')")
        if not ok or not name.strip():
            return
        from app.storage import save_template
        save_template({
            "name":           name.strip(),
            "client":         fresh.get("client",          ""),
            "client_email":   fresh.get("client_email",    ""),
            "client_phone":   fresh.get("client_phone",    ""),
            "client_address": fresh.get("client_address",  ""),
            "client_city":    fresh.get("client_city",     ""),
            "client_state":   fresh.get("client_state",    ""),
            "client_zip":     fresh.get("client_zip",      ""),
            "template":       fresh.get("template",        ""),
            "currency":       fresh.get("currency",        "USD"),
            "tax_rate":       fresh.get("tax_rate",        0),
            "tax_label":      fresh.get("tax_label",       "Tax"),
            "discount":       fresh.get("discount",        0),
            "notes":          fresh.get("notes",           ""),
            "line_items":     fresh.get("line_items",      []),
        })
        if self.app.templates_tab:
            self.app.templates_tab.refresh()
        QMessageBox.information(
            win, "Saved",
            f'Template "{name.strip()}" saved.\n'
            f'Find it in the Templates tab.')

    # ── Edit modal ────────────────────────────────────────────────────────────

    def _open_edit_modal(self, inv: dict):
        all_inv = load_invoices()
        fresh   = next(
            (r for r in all_inv
             if r.get("number")      == inv.get("number")
             and r.get("client")     == inv.get("client")
             and r.get("issue_date") == inv.get("issue_date")),
            inv)
        win = self._scroll.window()

        dlg = QDialog(win)
        dlg.setWindowTitle(f"Edit Invoice {fresh.get('number', '')}")
        dlg.setFixedWidth(520)
        dlg.resize(520, 640)
        dlg.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 12, 20, 12)
        hl_lbl = QLabel(f"Edit Invoice {fresh.get('number', '')}")
        hl_lbl.setAlignment(Qt.AlignCenter)
        hl_lbl.setStyleSheet(
            "color:white; font-size:14px; font-weight:700;"
            " background:transparent;")
        hl.addWidget(hl_lbl)
        layout.addWidget(hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:white; border:none;}")
        layout.addWidget(scroll, stretch=1)

        form_w = QWidget(); form_w.setStyleSheet("background:white;")
        fl = QVBoxLayout(form_w)
        fl.setContentsMargins(20, 12, 20, 8); fl.setSpacing(4)
        scroll.setWidget(form_w)

        def _section(title: str):
            lbl = QLabel(title)
            lbl.setStyleSheet(
                f"color:{ACCENT}; font-size:11px; font-weight:700;"
                " background:transparent; padding-top:10px; padding-bottom:2px;")
            fl.addWidget(lbl)
            div = QFrame(); div.setFixedHeight(1)
            div.setStyleSheet("background:#e5e7eb; margin-bottom:6px;")
            fl.addWidget(div)

        def _field(label: str, value: str = "") -> QLineEdit:
            row = QWidget(); row.setStyleSheet("background:transparent;")
            rl = QHBoxLayout(row); rl.setContentsMargins(0, 2, 0, 2); rl.setSpacing(8)
            lbl = QLabel(label); lbl.setFixedWidth(130)
            lbl.setStyleSheet(
                "font-size:12px; color:#374151; background:transparent;")
            rl.addWidget(lbl)
            e = QLineEdit(str(value) if value else "")
            rl.addWidget(e)
            fl.addWidget(row)
            return e

        _section("Invoice Details")
        f_number = _field("Invoice #",  fresh.get("number",     ""))
        f_issue  = _field("Issue Date", fresh.get("issue_date", ""))
        f_due    = _field("Due Date",   fresh.get("due_date",   ""))

        _section("Status")
        status_row = QWidget(); status_row.setStyleSheet("background:transparent;")
        srl = QHBoxLayout(status_row)
        srl.setContentsMargins(0, 2, 0, 2); srl.setSpacing(8)
        slbl = QLabel("Status"); slbl.setFixedWidth(130)
        slbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        srl.addWidget(slbl)
        f_status = QComboBox()
        f_status.addItems(["Draft", "Sent", "Paid"])
        cur_status = fresh.get("status", "Sent")
        f_status.setCurrentText(cur_status if cur_status != "Overdue" else "Sent")
        f_status.setFixedWidth(120)
        srl.addWidget(f_status); srl.addStretch()
        fl.addWidget(status_row)

        f_paid_date = _field("Paid Date", fresh.get("paid_date", ""))
        hint = QLabel("(optional — fill when marking Paid)")
        hint.setStyleSheet(
            "color:#9ca3af; font-size:10px; background:transparent;")
        fl.addWidget(hint)

        _section("Client")
        f_client = _field("Name",    fresh.get("client",          ""))
        f_email  = _field("Email",   fresh.get("client_email",    ""))
        f_phone  = _field("Phone",   fresh.get("client_phone",    ""))
        f_addr   = _field("Address", fresh.get("client_address",  ""))
        f_city   = _field("City",    fresh.get("client_city",     ""))
        f_state  = _field("State",   fresh.get("client_state",    ""))
        f_zip    = _field("ZIP",     fresh.get("client_zip",      ""))

        _section("Financials")
        f_tax_label = _field("Tax Label",  fresh.get("tax_label", "Tax"))
        f_tax_rate  = _field("Tax Rate %", str(fresh.get("tax_rate",  0)))
        f_discount  = _field("Discount",   str(fresh.get("discount",  0)))

        _section("Notes")
        f_notes = QPlainTextEdit()
        f_notes.setFixedHeight(70)
        f_notes.setPlainText(fresh.get("notes", ""))
        fl.addWidget(f_notes)

        foot = QFrame()
        foot.setStyleSheet("background:white; border-top:1px solid #f3f4f6;")
        footl = QHBoxLayout(foot)
        footl.setContentsMargins(20, 8, 20, 16); footl.setSpacing(8)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(100)
        cancel_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#f9fafb;}")
        cancel_btn.clicked.connect(dlg.reject)
        footl.addWidget(cancel_btn)

        note_lbl = QLabel("Note: editing does not regenerate the PDF.")
        note_lbl.setStyleSheet(
            "color:#9ca3af; font-size:10px; background:transparent;")
        footl.addWidget(note_lbl)
        footl.addStretch()

        save_btn = _action_btn("Save Changes", "save", w=140, h=34)
        footl.addWidget(save_btn)
        layout.addWidget(foot)

        def on_save():
            for lbl, val in [
                ("Issue Date", f_issue.text()),
                ("Due Date",   f_due.text()),
                ("Paid Date",  f_paid_date.text()),
            ]:
                v = val.strip()
                if v:
                    try:
                        datetime.strptime(v, "%Y-%m-%d")
                    except ValueError:
                        QMessageBox.warning(
                            dlg, "Invalid Date",
                            f"{lbl} must be YYYY-MM-DD (or leave blank).")
                        return
            updated = dict(fresh)
            updated.update({
                "number":         f_number.text().strip()    or fresh.get("number",     ""),
                "issue_date":     f_issue.text().strip()     or fresh.get("issue_date", ""),
                "due_date":       f_due.text().strip()       or fresh.get("due_date",   ""),
                "status":         f_status.currentText(),
                "paid_date":      f_paid_date.text().strip(),
                "client":         f_client.text().strip()    or fresh.get("client",     ""),
                "client_email":   f_email.text().strip(),
                "client_phone":   f_phone.text().strip(),
                "client_address": f_addr.text().strip(),
                "client_city":    f_city.text().strip(),
                "client_state":   f_state.text().strip(),
                "client_zip":     f_zip.text().strip(),
                "tax_label":      f_tax_label.text().strip() or "Tax",
                "tax_rate":       float(f_tax_rate.text().strip() or 0),
                "discount":       float(f_discount.text().strip() or 0),
                "notes":          f_notes.toPlainText().strip(),
            })
            self._update_invoice(fresh, updated)
            dlg.accept()
            self.refresh()

        save_btn.clicked.connect(on_save)

        dlg.adjustSize()
        dlg.resize(520, min(dlg.height(), 700))
        px = win.x() + (win.width()  - dlg.width())  // 2
        py = win.y() + (win.height() - dlg.height()) // 2
        dlg.move(px, py)
        dlg.exec()


    # ── Payments modal ────────────────────────────────────────────────────────

    def _open_payments_modal(self, inv: dict):
        """Record partial payments against an invoice."""
        from datetime import date as _date
        win = self._scroll.window()

        # Always work from the freshest copy
        for i in load_invoices():
            if (i.get("number")     == inv.get("number") and
                    i.get("client")     == inv.get("client") and
                    i.get("issue_date") == inv.get("issue_date")):
                inv = i; break

        payments: list[dict] = list(inv.get("payments", []))

        dlg = QDialog(win)
        dlg.setWindowTitle(f"Payments — {inv.get('number', '')}")
        dlg.setFixedWidth(500)
        dlg.setWindowModality(Qt.ApplicationModal)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Header
        hdr = QFrame(); hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 12, 20, 12)
        hl.addWidget(QLabel(
            f"Payment Log  ·  {inv.get('number','')}  ·  "
            f"Total: ${float(inv.get('total',0)):.2f}",
            styleSheet="color:white; font-size:12px; font-weight:700;"
                       " background:transparent;"))
        root.addWidget(hdr)

        body = QWidget(); body.setStyleSheet("background:white;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 10); bl.setSpacing(6)

        # Payment list frame
        list_frame = QFrame()
        list_frame.setStyleSheet(
            "QFrame{background:#f9fafb; border-radius:6px;"
            " border:1px solid #e5e7eb;}")
        lfl = QVBoxLayout(list_frame)
        lfl.setContentsMargins(10, 8, 10, 8); lfl.setSpacing(4)

        # Column header
        hrow = QWidget(); hrow.setStyleSheet("background:transparent;")
        hrl = QHBoxLayout(hrow); hrl.setContentsMargins(0,0,0,0)
        for txt, w in [("Date", 100), ("Amount", 90), ("Note", 212)]:
            lbl = QLabel(txt); lbl.setFixedWidth(w)
            lbl.setStyleSheet(
                "font-size:10px; font-weight:700; color:#6b7280;"
                " background:transparent;")
            hrl.addWidget(lbl)
        lfl.addWidget(hrow)

        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet("background:#e5e7eb;")
        lfl.addWidget(div)

        rows_w = QWidget(); rows_w.setStyleSheet("background:transparent;")
        rows_l = QVBoxLayout(rows_w)
        rows_l.setContentsMargins(0,0,0,0); rows_l.setSpacing(2)
        lfl.addWidget(rows_w)
        bl.addWidget(list_frame)

        # Summary label
        summary_lbl = QLabel("")
        summary_lbl.setStyleSheet(
            "font-size:11px; background:transparent; padding-top:2px;")
        bl.addWidget(summary_lbl)

        def _rebuild():
            while rows_l.count():
                item = rows_l.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            for idx, p in enumerate(payments):
                rw = QWidget(); rw.setStyleSheet("background:transparent;")
                rl2 = QHBoxLayout(rw)
                rl2.setContentsMargins(0,2,0,2); rl2.setSpacing(0)
                for val, w in [
                    (p.get("date",""),          100),
                    (f"${float(p.get('amount',0)):.2f}", 90),
                    (p.get("note",""),           212),
                ]:
                    lb = QLabel(val); lb.setFixedWidth(w)
                    lb.setStyleSheet(
                        "font-size:11px; color:#374151; background:transparent;")
                    rl2.addWidget(lb)
                del_btn = QPushButton()
                del_btn.setIcon(get_icon("delete"))
                del_btn.setFixedSize(28, 26)
                del_btn.setStyleSheet(
                    "QPushButton{background:#fee2e2; border:none; border-radius:4px;}"
                    "QPushButton:hover{background:#f72d2d;}"
                )
                del_btn.clicked.connect(lambda _, i=idx: _remove(i))
                rl2.addWidget(del_btn)
                rows_l.addWidget(rw)
            paid = sum(float(p.get("amount",0)) for p in payments)
            total = float(inv.get("total",0))
            bal = total - paid
            summary_lbl.setText(
                f"Paid: ${paid:.2f}   |   Balance: ${bal:.2f}"
                f"   |   Total: ${total:.2f}")
            summary_lbl.setStyleSheet(
                f"font-size:11px; font-weight:700; background:transparent;"
                f" color:{'#166534' if bal <= 0 else '#92400e'};")

        def _remove(idx):
            payments.pop(idx); _rebuild()

        # Divider
        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#e5e7eb; margin:4px 0;")
        bl.addWidget(sep)

        add_lbl = QLabel("Add Payment")
        add_lbl.setStyleSheet(
            "font-size:12px; font-weight:700; color:#374151; background:transparent;")
        bl.addWidget(add_lbl)

        inp_row = QWidget(); inp_row.setStyleSheet("background:transparent;")
        ipl = QHBoxLayout(inp_row)
        ipl.setContentsMargins(0,0,0,0); ipl.setSpacing(6)

        inp_date = QLineEdit(str(_date.today()))
        inp_date.setPlaceholderText("YYYY-MM-DD"); inp_date.setFixedWidth(110)
        inp_amt  = QLineEdit()
        inp_amt.setPlaceholderText("Amount"); inp_amt.setFixedWidth(90)
        inp_note = QLineEdit()
        inp_note.setPlaceholderText("Note (optional)")
        add_btn  = _action_btn("Add", None, w=60, h=28, color="#166534")

        ipl.addWidget(inp_date); ipl.addWidget(inp_amt)
        ipl.addWidget(inp_note); ipl.addWidget(add_btn)
        bl.addWidget(inp_row)

        def _add():
            try:
                amt = float(inp_amt.text().strip() or 0)
            except ValueError:
                return
            if amt <= 0: return
            payments.append({
                "date":   inp_date.text().strip(),
                "amount": amt,
                "note":   inp_note.text().strip(),
            })
            inp_amt.clear(); inp_note.clear()
            _rebuild()

        add_btn.clicked.connect(_add)
        inp_amt.returnPressed.connect(_add)
        root.addWidget(body)

        # Footer
        foot = QFrame()
        foot.setStyleSheet("background:white; border-top:1px solid #f3f4f6;")
        fl2 = QHBoxLayout(foot)
        fl2.setContentsMargins(16, 8, 16, 14); fl2.setSpacing(8)

        cancel_btn = QPushButton("Cancel"); cancel_btn.setFixedSize(90, 32)
        cancel_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#f9fafb;}")
        cancel_btn.clicked.connect(dlg.reject)
        fl2.addWidget(cancel_btn); fl2.addStretch()

        save_btn = _action_btn("Save Payments", "save", w=150, h=32)
        fl2.addWidget(save_btn)
        root.addWidget(foot)

        def _save():
            paid_total = sum(float(p.get("amount",0)) for p in payments)
            inv_total  = float(inv.get("total",0))
            all_invs   = load_invoices()
            for i in all_invs:
                if (i.get("number")     == inv.get("number") and
                        i.get("client")     == inv.get("client") and
                        i.get("issue_date") == inv.get("issue_date")):
                    i["payments"] = payments
                    if paid_total >= inv_total > 0:
                        i["status"] = "Paid"
                        i.setdefault("paid_date", str(_date.today()))
                    break
            tmp = INVOICE_FILE.with_suffix(".tmp")
            tmp.write_text(
                __import__("json").dumps(all_invs, indent=2), encoding="utf-8")
            __import__("os").replace(tmp, INVOICE_FILE)
            dlg.accept()
            self.refresh()

        save_btn.clicked.connect(_save)
        _rebuild()

        dlg.adjustSize()
        px2 = win.x() + (win.width()  - dlg.width())  // 2
        py2 = win.y() + (win.height() - dlg.height()) // 2
        dlg.move(px2, py2)
        dlg.exec()

    # ── Send Invoice dialog ───────────────────────────────────────────────────

    def _send_invoice(self, inv: dict):
        from app.email_sender import build_body, build_subject, open_mailto, send_smtp
        from app.storage import load_profile

        profile    = load_profile() or {}
        biz_name   = profile.get("name",  "")
        biz_email  = profile.get("email", "")
        client_to  = inv.get("client_email", "").strip()
        pdf_path   = inv.get("pdf_path", "")
        pdf_exists = bool(pdf_path) and os.path.exists(pdf_path)
        smtp_cfg   = profile.get("smtp", {})
        smtp_ok    = bool(smtp_cfg.get("host") and smtp_cfg.get("user"))

        subject = build_subject(inv)
        body    = build_body(inv, biz_name)

        win = self._scroll.window()
        dlg = QDialog(win)
        dlg.setWindowTitle(f"Send Invoice {inv.get('number', '')}")
        dlg.setFixedWidth(480)
        dlg.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 12, 20, 12)
        hl_lbl = QLabel(f"Send Invoice {inv.get('number', '')}")
        hl_lbl.setAlignment(Qt.AlignCenter)
        hl_lbl.setStyleSheet(
            "color:white; font-size:12px; font-weight:700;"
            " background:transparent;")
        hl.addWidget(hl_lbl)
        layout.addWidget(hdr)

        form = QWidget(); form.setStyleSheet("background:white;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(20, 10, 20, 8); fl.setSpacing(4)

        def _lbl(text: str):
            l = QLabel(text)
            l.setStyleSheet(
                "font-size:12px; color:#374151; background:transparent;"
                " padding-top:6px;")
            fl.addWidget(l)

        _lbl("To (email)")
        f_to = QLineEdit(client_to); fl.addWidget(f_to)
        _lbl("Subject")
        f_subject = QLineEdit(subject); fl.addWidget(f_subject)
        _lbl("Message")
        f_body = QPlainTextEdit()
        f_body.setFixedHeight(140)
        f_body.setPlainText(body)
        fl.addWidget(f_body)

        attach_row = QWidget(); attach_row.setStyleSheet("background:transparent;")
        attach_rl = QHBoxLayout(attach_row)
        attach_rl.setContentsMargins(0, 4, 0, 0); attach_rl.setSpacing(4)
        if pdf_exists:
            attach_icon = QLabel()
            attach_icon.setPixmap(
                get_icon("paperclip").pixmap(14, 14))
            attach_icon.setStyleSheet("background:transparent;")
            attach_rl.addWidget(attach_icon)
        attach_lbl = QLabel(
            os.path.basename(pdf_path) if pdf_exists
            else "⚠  PDF not found — locate it before sending")
        attach_lbl.setStyleSheet(
            f"color:{ACCENT if pdf_exists else '#991b1b'};"
            " font-size:11px; background:transparent;")
        attach_rl.addWidget(attach_lbl)
        attach_rl.addStretch()
        fl.addWidget(attach_row)

        self._send_status_lbl = QLabel("")
        self._send_status_lbl.setWordWrap(True)
        self._send_status_lbl.setStyleSheet(
            "color:#6b7280; font-size:11px; background:transparent;")
        fl.addWidget(self._send_status_lbl)
        layout.addWidget(form)

        if not smtp_ok:
            cfg_hint = QLabel(
                "Configure SMTP in Business Profile to send directly.")
            cfg_hint.setContentsMargins(20, 0, 20, 4)
            cfg_hint.setStyleSheet(
                "color:#9ca3af; font-size:11px; background:white;")
            layout.addWidget(cfg_hint)

        foot = QFrame()
        foot.setStyleSheet("background:white; border-top:1px solid #f3f4f6;")
        footl = QHBoxLayout(foot)
        footl.setContentsMargins(20, 8, 20, 16); footl.setSpacing(6)

        mailto_btn = _action_btn("Open Email App", None, w=140, h=30)
        footl.addWidget(mailto_btn)

        if smtp_ok:
            self._smtp_btn = _action_btn("Send via SMTP", "send", w=130, h=30)
            footl.addWidget(self._smtp_btn)

        footl.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#f9fafb;}")
        cancel_btn.clicked.connect(dlg.reject)
        footl.addWidget(cancel_btn)
        layout.addWidget(foot)

        def _do_mailto():
            to = f_to.text().strip()
            if not to:
                QMessageBox.warning(dlg, "Missing Email",
                                    "Enter a recipient email address.")
                return
            open_mailto(to, f_subject.text().strip(),
                        f_body.toPlainText().strip())
            self._send_status_lbl.setText(
                f"Email client opened. "
                f"{'Attach PDF from: ' + pdf_path if pdf_exists else ''}")
            self._send_status_lbl.setStyleSheet(
                "color:#166534; font-size:11px; background:transparent;")

        def _do_smtp():
            to = f_to.text().strip()
            if not to:
                QMessageBox.warning(dlg, "Missing Email",
                                    "Enter a recipient email address.")
                return
            self._smtp_btn.setEnabled(False)
            self._smtp_btn.setText("Sending…")
            QApplication.processEvents()
            ok, msg = send_smtp(
                smtp_host=smtp_cfg["host"],
                smtp_port=int(smtp_cfg.get("port", 587)),
                smtp_user=smtp_cfg["user"],
                smtp_pass=smtp_cfg.get("pass", ""),
                from_addr=smtp_cfg.get("from") or biz_email,
                to_addr=to,
                subject=f_subject.text().strip(),
                body=f_body.toPlainText().strip(),
                pdf_path=pdf_path if pdf_exists else None,
                use_ssl=smtp_cfg.get("ssl", False),
            )
            if ok:
                if inv.get("status") == "Draft":
                    inv["status"] = "Sent"
                    self._save_status(inv)
                self._send_status_lbl.setText("✓ Sent successfully — closing…")
                self._send_status_lbl.setStyleSheet(
                    "color:#166534; font-size:11px; background:transparent;")
                QApplication.processEvents()
                QTimer.singleShot(1200, lambda: (
                    dlg.accept(), self.refresh(),
                    self._show_toast(f"✓ Invoice sent to {to}"),
                ))
            else:
                self._smtp_btn.setEnabled(True)
                self._smtp_btn.setText("Send via SMTP")
                self._send_status_lbl.setText(f"✗ Failed: {msg}")
                self._send_status_lbl.setStyleSheet(
                    "color:#991b1b; font-size:11px; background:transparent;")

        mailto_btn.clicked.connect(_do_mailto)
        if smtp_ok:
            self._smtp_btn.clicked.connect(_do_smtp)

        dlg.adjustSize()
        px = win.x() + (win.width()  - dlg.width())  // 2
        py = win.y() + (win.height() - dlg.height()) // 2
        dlg.move(px, py)
        dlg.exec()

    # ── Toast ─────────────────────────────────────────────────────────────────

    def _show_toast(self, message: str, duration_ms: int = 3000):
        win = self._scroll.window()
        toast = QLabel(message, win)
        toast.setAlignment(Qt.AlignCenter)
        toast.setStyleSheet(
            "background:#166534; color:white; border-radius:8px;"
            " font-size:12px; font-weight:700; padding:8px 16px;")
        toast.setFixedSize(320, 40)
        tx = (win.width() - 320) // 2
        toast.move(tx, 60)
        toast.raise_()
        toast.show()
        QTimer.singleShot(duration_ms, toast.deleteLater)

    # ── CSV export ────────────────────────────────────────────────────────────

    def _export_csv(self):
        from app.storage import get_output_dir
        win = self._scroll.window()
        all_inv  = load_invoices()
        today    = date.today()
        query    = self._search.text().strip().lower()
        status_f = self._current_filter

        shown = []
        for i in reversed(all_inv):
            if query and query not in i.get("client", "").lower():
                continue
            eff = _effective_status(i, today)
            if status_f == "All":
                pass
            elif status_f == "Sent":
                if eff not in ("Sent", "Overdue"):
                    continue
            elif eff != status_f:
                continue
            shown.append((i, eff))

        if not shown:
            QMessageBox.warning(win, "Nothing to Export",
                                "No invoices match the current filter.")
            return

        default_name = ("invoices" if status_f == "All"
                        else f"invoices_{status_f.lower()}")
        path, _ = QFileDialog.getSaveFileName(
            win, "Export Invoices to CSV",
            str(get_output_dir() / f"{default_name}.csv"),
            "CSV files (*.csv);;All files (*.*)")
        if not path:
            return

        columns = [
            "Invoice #", "Client", "Email", "Phone",
            "Address", "City", "State", "ZIP",
            "Issue Date", "Due Date", "Status",
            "Paid Date", "Currency", "Tax Label",
            "Tax Rate %", "Discount", "Subtotal", "Total",
            "Template", "Notes", "PDF Path",
        ]

        def _subtotal(inv):
            try:
                return f"{sum(float(li.get('qty', 1)) * float(li.get('unit_price', 0)) for li in inv.get('line_items', [])):.2f}"
            except Exception:
                return ""

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for inv, eff_status in shown:
                    writer.writerow({
                        "Invoice #":   inv.get("number",         ""),
                        "Client":      inv.get("client",         ""),
                        "Email":       inv.get("client_email",   ""),
                        "Phone":       inv.get("client_phone",   ""),
                        "Address":     inv.get("client_address", ""),
                        "City":        inv.get("client_city",    ""),
                        "State":       inv.get("client_state",   ""),
                        "ZIP":         inv.get("client_zip",     ""),
                        "Issue Date":  inv.get("issue_date",     ""),
                        "Due Date":    inv.get("due_date",       ""),
                        "Status":      eff_status,
                        "Paid Date":   inv.get("paid_date",      ""),
                        "Currency":    inv.get("currency",       "USD"),
                        "Tax Label":   inv.get("tax_label",      "Tax"),
                        "Tax Rate %":  inv.get("tax_rate",       0),
                        "Discount":    inv.get("discount",       0),
                        "Subtotal":    _subtotal(inv),
                        "Total":       inv.get("total",          ""),
                        "Template":    inv.get("template",       ""),
                        "Notes":       inv.get("notes",          ""),
                        "PDF Path":    inv.get("pdf_path",       ""),
                    })
            n = len(shown)
            reply = QMessageBox.question(
                win, "Export Complete",
                f"Exported {n} invoice{'s' if n > 1 else ''} to:\n{path}\n\n"
                f"Open the file now?",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.app.invoice_tab._open_file(path)
        except OSError as exc:
            QMessageBox.critical(win, "Export Failed", str(exc))

    # ── Storage helpers ───────────────────────────────────────────────────────

    def _save_status(self, updated: dict):
        all_inv = load_invoices()
        for i in all_inv:
            if (i.get("number")     == updated.get("number") and
                    i.get("client")     == updated.get("client") and
                    i.get("issue_date") == updated.get("issue_date")):
                i["status"] = updated.get("status", "Sent")
                break
        self._write(all_inv)

    def _update_invoice(self, original: dict, updated: dict):
        try:
            line_items = updated.get(
                "line_items", original.get("line_items", []))
            subtotal   = sum(
                float(li.get("qty", 1)) * float(li.get("unit_price", 0))
                for li in line_items)
            tax_rate   = float(updated.get("tax_rate", 0))
            discount   = float(updated.get("discount", 0))
            tax_amount = round(subtotal * (tax_rate / 100), 2)
            updated["total"] = round(subtotal + tax_amount - discount, 2)
        except Exception:
            pass
        all_inv = load_invoices()
        for idx, i in enumerate(all_inv):
            if (i.get("number")     == original.get("number") and
                    i.get("client")     == original.get("client") and
                    i.get("issue_date") == original.get("issue_date")):
                all_inv[idx] = updated
                break
        self._write(all_inv)

    @staticmethod
    def _write(invoices: list):
        tmp = INVOICE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(invoices, indent=2), encoding="utf-8")
        os.replace(tmp, INVOICE_FILE)

    @staticmethod
    def _migrate_records():
        all_inv = load_invoices()
        changed = False
        for i in all_inv:
            if "line_items" not in i:
                for k, v in [
                    ("line_items", []), ("template", ""),
                    ("tax_rate", 0), ("tax_label", "Tax"),
                    ("payment_link", ""), ("payment_terms", ""),
                    ("discount", 0), ("notes", ""),
                    ("client_email", ""), ("client_phone", ""),
                    ("client_address", ""), ("client_city", ""),
                    ("client_state", ""), ("client_zip", ""),
                ]:
                    i.setdefault(k, v)
                changed = True
            elif "tax_label" not in i:
                i["tax_label"] = "Tax"; changed = True
            if "payment_link" not in i:
                i["payment_link"] = ""; changed = True
            if "payment_terms" not in i:
                i["payment_terms"] = ""; changed = True
        if changed:
            tmp = INVOICE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(all_inv, indent=2), encoding="utf-8")
            os.replace(tmp, INVOICE_FILE)