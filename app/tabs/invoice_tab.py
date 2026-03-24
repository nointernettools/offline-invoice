"""
Invoice tab — form, live preview, generate.
PySide6 migration: CTk → Qt, pack/grid → QLayout,
threading preview → QThread, ImageTk → QPixmap,
CTkTextbox → QPlainTextEdit, CTkOptionMenu → QComboBox.
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QPixmap
from app.icon_utils import get_icon
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget,
)

from app.invoice import Invoice, LineItem
from app.pdf_gen import WEASY_TEMPLATES, generate
from app.storage import (
    find_client, find_customer_by_name, get_output_dir,
    invoice_number_exists, load_invoices, load_profile,
    next_invoice_number, save_client, save_invoice,
)

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_OK = True
except ImportError:
    PDF2IMAGE_OK = False

from app.poppler_utils import find_poppler

log = logging.getLogger(__name__)

ACCENT        = "#2563EB"
TEMPLATE_LIST = list(WEASY_TEMPLATES.keys())

CURRENCIES = {
    "USD ($)": ("USD", "$"),
    "EUR (€)": ("EUR", "€"),
    "GBP (£)": ("GBP", "£"),
    "CAD ($)": ("CAD", "$"),
    "AUD ($)": ("AUD", "$"),
}


# ── Signal carrier (lets worker thread post to main thread) ──────────────────

class _PreviewSignals(QObject):
    done  = Signal(bytes)   # PNG bytes
    error = Signal(str)     # error message
    busy  = Signal(str)     # status text


# ── Card helper ───────────────────────────────────────────────────────────────

def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setStyleSheet(
        "QFrame{background:white; border-radius:8px; border:none;}")
    f.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    vb = QVBoxLayout(f)
    vb.setContentsMargins(0, 0, 0, 10)
    vb.setSpacing(0)

    hdr = QLabel(title)
    hdr.setContentsMargins(12, 10, 12, 2)
    hdr.setStyleSheet(
        f"color:{ACCENT}; font-weight:700; font-size:13px;"
        " background:transparent;")
    vb.addWidget(hdr)

    div = QFrame()
    div.setFixedHeight(1)
    div.setStyleSheet("background:#e5e7eb; margin:0 12px;")
    vb.addWidget(div)
    return f, vb


def _form_row(body: QVBoxLayout, label: str,
              placeholder: str = "",
              width: int = 100) -> QLineEdit:
    row = QWidget()
    row.setStyleSheet("background:transparent;")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(12, 3, 12, 3)
    rl.setSpacing(8)
    lbl = QLabel(label)
    lbl.setFixedWidth(width)
    lbl.setStyleSheet(
        "font-size:12px; color:#374151; background:transparent;")
    rl.addWidget(lbl)
    entry = QLineEdit()
    entry.setPlaceholderText(placeholder)
    rl.addWidget(entry)
    body.addWidget(row)
    return entry


# ── Tab ───────────────────────────────────────────────────────────────────────

class InvoiceTab:

    def __init__(self, parent: QWidget, app):
        self.app = app
        self._items: list[tuple[QLineEdit, QLineEdit, QLineEdit]] = []
        self._preview_timer: QTimer | None = None
        self._render_lock   = threading.Lock()
        self._autofill_timer: QTimer | None = None
        self._last_preview_hash: str | None = None
        self._PREVIEW_DELAY_MS  = 1200
        self._AUTOFILL_DELAY_MS = 500
        self._signals = _PreviewSignals()
        self._signals.done.connect(self._apply_preview)
        self._signals.error.connect(self._show_preview_error)
        self._signals.busy.connect(self._show_preview_busy)
        self._build(parent)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self, parent: QWidget):
        root = QHBoxLayout(parent)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter)

        # ── Left: scrollable form ─────────────────────────────────────────────
        left_outer = QScrollArea()
        left_outer.setWidgetResizable(True)
        left_outer.setFrameShape(QFrame.NoFrame)
        left_outer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_outer.setStyleSheet(
            "QScrollArea{background:#f3f4f6; border:none;}")

        left_container = QWidget()
        left_container.setStyleSheet("background:#f3f4f6;")
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(8)
        left_layout.setAlignment(Qt.AlignTop)
        left_outer.setWidget(left_container)

        self._build_invoice_details(left_layout)
        self._build_bill_to(left_layout)
        self._build_line_items(left_layout)
        self._build_totals(left_layout)
        self._build_notes(left_layout)
        self._build_actions(left_layout)
        left_layout.addStretch()

        splitter.addWidget(left_outer)

        # ── Right: preview ────────────────────────────────────────────────────
        right = QFrame()
        right.setStyleSheet(
            "QFrame{background:#e5e7eb; border-radius:8px; border:none;}")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(4)

        preview_title = QLabel("Live Preview")
        preview_title.setAlignment(Qt.AlignCenter)
        preview_title.setStyleSheet(
            "color:#9ca3af; font-size:12px; font-weight:700;"
            " background:transparent;")
        right_layout.addWidget(preview_title)

        self._preview_label = QLabel("Rendering preview…")
        self._preview_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "color:#9ca3af; font-size:12px; background:transparent;")
        self._preview_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview_label.setScaledContents(False)
        right_layout.addWidget(self._preview_label)

        splitter.addWidget(right)
        splitter.setSizes([420, 560])

        # Delay initial preview until after the window is fully shown
        # to avoid crashing WeasyPrint/poppler before Qt is ready
        QTimer.singleShot(1500, lambda: self.schedule_preview(delay=0))

    # ── Invoice Details card ──────────────────────────────────────────────────

    def _build_invoice_details(self, layout: QVBoxLayout):
        card, body = _card("Invoice Details")
        layout.addWidget(card)

        self.v_inv_num = _form_row(body, "Invoice #", "e.g. INV-001")
        self.v_inv_num.textChanged.connect(lambda _: self.schedule_preview())
        QTimer.singleShot(0, self._set_next_invoice_number)

        issue_w = QWidget(); issue_w.setStyleSheet("background:transparent;")
        issue_l = QHBoxLayout(issue_w)
        issue_l.setContentsMargins(12, 3, 12, 3); issue_l.setSpacing(8)
        il = QLabel("Issue Date"); il.setFixedWidth(100)
        il.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        issue_l.addWidget(il)
        self.v_issue = QLineEdit(); self.v_issue.setPlaceholderText("YYYY-MM-DD")
        self.v_issue.textChanged.connect(lambda _: self.schedule_preview())
        issue_l.addWidget(self.v_issue)
        today_btn = QPushButton("Today"); today_btn.setFixedSize(52, 24)
        today_btn.clicked.connect(
            lambda: (self.v_issue.setText(str(date.today())),
                     self.schedule_preview()))
        issue_l.addWidget(today_btn)
        body.addWidget(issue_w)

        due_w = QWidget(); due_w.setStyleSheet("background:transparent;")
        due_l = QHBoxLayout(due_w)
        due_l.setContentsMargins(12, 3, 12, 3); due_l.setSpacing(8)
        dl = QLabel("Due Date"); dl.setFixedWidth(100)
        dl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        due_l.addWidget(dl)
        self.v_due = QLineEdit(); self.v_due.setPlaceholderText("YYYY-MM-DD")
        self.v_due.textChanged.connect(lambda _: self.schedule_preview())
        due_l.addWidget(self.v_due)
        plus30_btn = QPushButton("+30d"); plus30_btn.setFixedSize(52, 24)
        plus30_btn.clicked.connect(self.fill_due_date)
        due_l.addWidget(plus30_btn)
        body.addWidget(due_w)

        cur_w = QWidget(); cur_w.setStyleSheet("background:transparent;")
        cur_l = QHBoxLayout(cur_w)
        cur_l.setContentsMargins(12, 4, 12, 4); cur_l.setSpacing(8)
        cl = QLabel("Currency"); cl.setFixedWidth(100)
        cl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        cur_l.addWidget(cl)
        self.v_currency = QComboBox()
        self.v_currency.addItems(list(CURRENCIES.keys()))
        self.v_currency.setFixedWidth(180)
        self.v_currency.currentTextChanged.connect(
            lambda _: self.schedule_preview())
        cur_l.addWidget(self.v_currency)
        cur_l.addStretch()
        body.addWidget(cur_w)

    # ── Bill To card ──────────────────────────────────────────────────────────

    def _build_bill_to(self, layout: QVBoxLayout):
        card, body = _card("Bill To")
        layout.addWidget(card)

        self._recent_chips_frame = QWidget()
        self._recent_chips_frame.setStyleSheet("background:transparent;")
        self._recent_chips_layout = QHBoxLayout(self._recent_chips_frame)
        self._recent_chips_layout.setContentsMargins(12, 5, 12, 4)
        self._recent_chips_layout.setSpacing(4)
        self._recent_chips_layout.setAlignment(Qt.AlignLeft)
        self._recent_chips_frame.hide()
        body.addWidget(self._recent_chips_frame)

        self.v_client_name  = _form_row(body, "Client Name",  "Company or person")
        self.v_client_email = _form_row(body, "Client Email", "email@example.com")
        self.v_client_phone = _form_row(body, "Phone",        "e.g. 123-456-7890")
        self.v_client_addr  = _form_row(body, "Address",      "Street")
        self.v_client_city  = _form_row(body, "City",         "City")
        self.v_client_state = _form_row(body, "State",        "State")
        self.v_client_zip   = _form_row(body, "ZIP",          "ZIP")

        for w in [self.v_client_name, self.v_client_email, self.v_client_phone,
                  self.v_client_addr, self.v_client_city, self.v_client_state,
                  self.v_client_zip]:
            w.textChanged.connect(lambda _: self.schedule_preview())

        self.v_client_name.textChanged.connect(self._on_client_name_change)

        save_cust_btn = QPushButton("+ Save as Customer")
        save_cust_btn.setFixedSize(160, 28)
        save_cust_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT}; color:white; border:none;"
            f" border-radius:6px; font-size:11px; font-weight:600;}}"
            f"QPushButton:hover{{background:#1d4ed8;}}")
        save_cust_btn.clicked.connect(self._save_current_as_customer)
        bw = QWidget(); bw.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(bw); bl.setContentsMargins(12, 2, 12, 10)
        bl.addWidget(save_cust_btn); bl.addStretch()
        body.addWidget(bw)

        self.build_recent_chips()

    # ── Line Items card ───────────────────────────────────────────────────────

    def _build_line_items(self, layout: QVBoxLayout):
        card, body = _card("Line Items")
        layout.addWidget(card)

        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame{{background:{ACCENT}; border-radius:4px; border:none;}}")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(12, 5, 12, 5); hl.setSpacing(0)
        for txt, w in [("Description", 200), ("Qty", 50), ("Price", 90)]:
            lbl = QLabel(txt); lbl.setFixedWidth(w)
            lbl.setStyleSheet(
                "color:white; font-weight:700; font-size:11px;"
                " background:transparent;")
            hl.addWidget(lbl)
        hl.addStretch()
        hw = QWidget(); hw.setStyleSheet("background:transparent;")
        hl2 = QHBoxLayout(hw); hl2.setContentsMargins(12, 0, 12, 4)
        hl2.addWidget(hdr)
        body.addWidget(hw)

        self._items_container = QWidget()
        self._items_container.setStyleSheet("background:transparent;")
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(12, 0, 12, 0)
        self._items_layout.setSpacing(2)
        iw = QWidget(); iw.setStyleSheet("background:transparent;")
        il = QVBoxLayout(iw); il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(self._items_container)
        body.addWidget(iw)

        self.items_rows_container = self._items_container

        self.add_item_row()

        add_btn = QPushButton("+ Add Item")
        add_btn.setFixedSize(110, 28)
        add_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT}; color:white; border:none;"
            f" border-radius:6px; font-size:11px; font-weight:600;}}"
            f"QPushButton:hover{{background:#1d4ed8;}}")
        add_btn.clicked.connect(self.add_item_row)
        aw = QWidget(); aw.setStyleSheet("background:transparent;")
        al = QHBoxLayout(aw); al.setContentsMargins(12, 4, 12, 10)
        al.addWidget(add_btn); al.addStretch()
        body.addWidget(aw)

    # ── Totals card ───────────────────────────────────────────────────────────

    def _build_totals(self, layout: QVBoxLayout):
        card, body = _card("Totals")
        layout.addWidget(card)

        self.v_tax_label = _form_row(body, "Tax Label", "e.g. GST/HST")
        self.v_tax_label.setText("Tax")
        self.v_tax       = _form_row(body, "Tax (%)",   "0")
        self.v_discount  = _form_row(body, "Discount",  "0.00")

        self.v_tax.textChanged.connect(lambda _: self.refresh_totals())
        self.v_discount.textChanged.connect(lambda _: self.refresh_totals())
        self.v_tax_label.textChanged.connect(lambda _: self.schedule_preview())

        self.lbl_subtotal = QLabel("Subtotal:  $0.00")
        self.lbl_subtotal.setAlignment(Qt.AlignRight)
        self.lbl_subtotal.setContentsMargins(12, 1, 12, 1)
        self.lbl_subtotal.setStyleSheet(
            "background:transparent; font-size:12px; color:#374151;")

        self.lbl_tax_amt = QLabel("")
        self.lbl_tax_amt.setAlignment(Qt.AlignRight)
        self.lbl_tax_amt.setContentsMargins(12, 1, 12, 1)
        self.lbl_tax_amt.setStyleSheet(
            "background:transparent; font-size:12px; color:#9ca3af;")

        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet("background:#e5e7eb; margin:4px 12px;")

        self.lbl_grand_total = QLabel("Total Due: $0.00")
        self.lbl_grand_total.setAlignment(Qt.AlignRight)
        self.lbl_grand_total.setContentsMargins(12, 2, 12, 4)
        self.lbl_grand_total.setStyleSheet(
            f"background:transparent; font-size:16px; font-weight:700;"
            f" color:{ACCENT};")

        for w in [self.lbl_subtotal, self.lbl_tax_amt,
                  div, self.lbl_grand_total]:
            body.addWidget(w)

    # ── Notes & Payment card ──────────────────────────────────────────────────

    def _build_notes(self, layout: QVBoxLayout):
        card, body = _card("Notes & Payment")
        layout.addWidget(card)

        nw = QWidget(); nw.setStyleSheet("background:transparent;")
        nl = QVBoxLayout(nw); nl.setContentsMargins(12, 0, 12, 6)
        self.v_notes = QPlainTextEdit()
        self.v_notes.setFixedHeight(80)
        self.v_notes.setPlainText("Thank you for your business!")
        self.v_notes.textChanged.connect(lambda: self.schedule_preview())
        nl.addWidget(self.v_notes)
        body.addWidget(nw)

        terms_w = QWidget(); terms_w.setStyleSheet("background:transparent;")
        tl = QHBoxLayout(terms_w)
        tl.setContentsMargins(12, 0, 12, 0); tl.setSpacing(8)
        tlbl = QLabel("Footer Terms"); tlbl.setFixedWidth(100)
        tlbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        tl.addWidget(tlbl)
        self.v_payment_terms = QLineEdit()
        self.v_payment_terms.setPlaceholderText(
            "e.g. Net 30 · Late payments subject to 1.5%/month")
        self.v_payment_terms.textChanged.connect(lambda _: self.schedule_preview())
        tl.addWidget(self.v_payment_terms)
        body.addWidget(terms_w)

        terms_hint = QLabel(
            "↑  Printed in the invoice footer alongside your contact details")
        terms_hint.setContentsMargins(12, 0, 12, 6)
        terms_hint.setStyleSheet(
            "color:#9ca3af; font-size:10px; background:transparent;")
        body.addWidget(terms_hint)

        pay_w = QWidget(); pay_w.setStyleSheet("background:transparent;")
        pl = QHBoxLayout(pay_w)
        pl.setContentsMargins(12, 0, 12, 0); pl.setSpacing(8)
        plbl = QLabel("Payment Link"); plbl.setFixedWidth(100)
        plbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        pl.addWidget(plbl)
        self.v_payment_link = QLineEdit()
        self.v_payment_link.setPlaceholderText(
            "e.g. paypal.me/yourname or stripe.com/pay/…")
        self.v_payment_link.textChanged.connect(lambda _: self.schedule_preview())
        pl.addWidget(self.v_payment_link)
        body.addWidget(pay_w)

        pay_hint = QLabel(
            "↑  Leave blank to omit QR code  ·  "
            "Accepts any URL: PayPal, Venmo, Stripe, bank transfer…")
        pay_hint.setContentsMargins(12, 0, 12, 6)
        pay_hint.setStyleSheet(
            "color:#9ca3af; font-size:10px; background:transparent;")
        body.addWidget(pay_hint)

# ── Output / Actions card ─────────────────────────────────────────────────
 
    def _build_actions(self, layout: QVBoxLayout):
        card, body = _card("Output")
        layout.addWidget(card)
 
        tmpl_w = QWidget(); tmpl_w.setStyleSheet("background:transparent;")
        tl = QHBoxLayout(tmpl_w)
        tl.setContentsMargins(12, 4, 12, 4); tl.setSpacing(8)
        tlbl = QLabel("Template"); tlbl.setFixedWidth(100)
        tlbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        tl.addWidget(tlbl)
        self.v_template = QComboBox()
        self.v_template.addItems(TEMPLATE_LIST)
        self.v_template.setFixedWidth(200)
        # Explicit white background so the card body background doesn't bleed in
        self.v_template.setStyleSheet(
            "QComboBox { background: white; border: 1px solid #e5e7eb;"
            " border-radius: 6px; padding: 5px 10px; color: #1f2937; min-height: 28px; }"
            "QComboBox:focus { border-color: #2563EB; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
            "QComboBox QAbstractItemView { background: white; border: 1px solid #e5e7eb;"
            " border-radius: 4px; selection-background-color: #dbeafe;"
            " selection-color: #1e40af; outline: none; padding: 2px; }")
        self.v_template.currentTextChanged.connect(
            lambda _: self.schedule_preview())
        tl.addWidget(self.v_template); tl.addStretch()
        body.addWidget(tmpl_w)
 
        fn_w = QWidget(); fn_w.setStyleSheet("background:transparent;")
        fl = QHBoxLayout(fn_w)
        fl.setContentsMargins(12, 0, 12, 0); fl.setSpacing(8)
        flbl = QLabel("File Name"); flbl.setFixedWidth(100)
        flbl.setStyleSheet(
            "font-size:12px; color:#374151; background:transparent;")
        fl.addWidget(flbl)
        self.v_filename = QLineEdit()
        self.v_filename.setPlaceholderText("Custom filename")
        fl.addWidget(self.v_filename)
        body.addWidget(fn_w)
 
        fn_hint = QLabel(".pdf is appended automatically if omitted")
        fn_hint.setContentsMargins(12, 0, 12, 8)
        fn_hint.setStyleSheet(
            "color:#9ca3af; font-size:10px; background:transparent;")
        body.addWidget(fn_hint)
 
        btn_w = QWidget(); btn_w.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(btn_w)
        bl.setContentsMargins(12, 0, 12, 0); bl.setSpacing(8)
 
        # Secondary action — transparent/outline is correct here, keeps Generate PDF
        # as the clear primary CTA. Using objectName so global QSS handles it.
        clear_btn = QPushButton("Clear Form")
        clear_btn.setObjectName("flat")
        clear_btn.setFixedSize(130, 36)
        clear_btn.clicked.connect(self.clear)
        bl.addWidget(clear_btn)
        bl.addStretch()
 
        # Primary action — explicit accent style so it's never transparent
        gen_btn = QPushButton("Generate PDF")
        gen_btn.setFixedSize(160, 36)
        gen_btn.setStyleSheet(
            "QPushButton { background: #2563EB; color: white; border: none;"
            " border-radius: 6px; font-size: 13px; font-weight: 700; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:pressed { background: #1e3a8a; }")
        gen_btn.clicked.connect(self.generate)
        bl.addWidget(gen_btn)
 
        body.addWidget(btn_w)
 
        sp = QWidget(); sp.setFixedHeight(4)
        sp.setStyleSheet("background:transparent;")
        body.addWidget(sp)
    # ── Line item helpers ─────────────────────────────────────────────────────

    def add_item_row(self):
        row_w = QWidget(); row_w.setStyleSheet("background:transparent;")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 2, 0, 2); rl.setSpacing(4)

        desc  = QLineEdit(); desc.setPlaceholderText("Description")
        desc.setFixedWidth(200)
        qty   = QLineEdit("1"); qty.setFixedWidth(50)
        qty.setAlignment(Qt.AlignCenter)
        price = QLineEdit(); price.setFixedWidth(90)
        price.setAlignment(Qt.AlignRight)

        for w in [desc, qty, price]:
            w.textChanged.connect(
                lambda _: (self.refresh_totals(), self.schedule_preview()))
            rl.addWidget(w)

        del_btn = QPushButton()
        del_btn.setIcon(get_icon("delete"))
        del_btn.setFixedSize(28, 26)
        del_btn.setStyleSheet(
            "QPushButton{background:#fee2e2; border:none; border-radius:4px;}"
            "QPushButton:hover{background:#f72d2d;}")
        item_tuple = (desc, qty, price)
        del_btn.clicked.connect(
            lambda _, rw=row_w, it=item_tuple: self._del_row(rw, it))
        rl.addWidget(del_btn)
        rl.addStretch()

        self._items_layout.addWidget(row_w)
        self._items.append(item_tuple)

    def _del_row(self, row_widget: QWidget,
                 item: tuple[QLineEdit, QLineEdit, QLineEdit]):
        row_widget.deleteLater()
        if item in self._items:
            self._items.remove(item)
        self.refresh_totals()
        self.schedule_preview()

    def clear_items(self):
        while self._items_layout.count():
            w = self._items_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._items.clear()

    def load_items_from(self, items: list[dict]):
        self.clear_items()
        for item in items:
            self.add_item_row()
            desc_w, qty_w, price_w = self._items[-1]
            desc_w.setText(item.get("description", ""))
            qty_w.setText(str(item.get("qty", 1)))
            up = item.get("unit_price")
            if up is not None:
                price_w.setText(str(up))

    # ── Totals ────────────────────────────────────────────────────────────────

    def refresh_totals(self):
        sym = CURRENCIES.get(self.v_currency.currentText(), ("USD", "$"))[1]
        sub = 0.0
        for _, qw, pw in self._items:
            try:
                sub += float(qw.text()) * float(pw.text())
            except Exception:
                pass
        try:
            tr = float(self.v_tax.text()      or 0)
            ds = float(self.v_discount.text() or 0)
        except Exception:
            tr = ds = 0.0
        tax_a = sub * (tr / 100)
        grand = sub + tax_a - ds
        self.lbl_subtotal.setText(f"Subtotal:  {sym}{sub:,.2f}")
        self.lbl_tax_amt.setText(
            f"Tax:       {sym}{tax_a:,.2f}" if tr else "")
        self.lbl_grand_total.setText(f"Total Due: {sym}{grand:,.2f}")

# ── Recent chips ──────────────────────────────────────────────────────────
 
    def build_recent_chips(self):
        while self._recent_chips_layout.count():
            item = self._recent_chips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
 
        seen, recents = set(), []
        for inv in reversed(load_invoices()):
            name = inv.get("client", "").strip()
            if name and name not in seen:
                seen.add(name); recents.append(name)
            if len(recents) == 5:
                break
 
        if not recents:
            self._recent_chips_frame.hide()
            return
 
        self._recent_chips_frame.show()
 
        lbl = QLabel("Recent:")
        lbl.setStyleSheet(
            "font-size:11px; font-weight:600; color:#6b7280;"
            " background:transparent; padding-right:2px;")
        self._recent_chips_layout.addWidget(lbl)
 
        for name in recents:
            # Show up to 18 chars before truncating — a bit more breathing room
            label = name if len(name) <= 18 else name[:16] + "…"
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setToolTip(name)   # full name on hover in case it's truncated
            btn.setStyleSheet(
                "QPushButton { background: #eff6ff; color: #2563EB;"
                " border: 1px solid #bfdbfe; border-radius: 10px;"
                " font-size: 11px; font-weight: 500; padding: 0 10px; }"
                "QPushButton:hover { background: #2563EB; color: white;"
                " border-color: #2563EB; }"
                "QPushButton:pressed { background: #1d4ed8; color: white; }")
            btn.clicked.connect(
                lambda _, n=name: self._autofill_from_name(n))
            self._recent_chips_layout.addWidget(btn)

    def _autofill_from_name(self, name: str):
        self.v_client_name.setText(name)
        c = find_customer_by_name(name) or find_client(name)
        if c:
            for widget, key in [
                (self.v_client_email, "email"),
                (self.v_client_phone, "phone"),
                (self.v_client_addr,  "address"),
                (self.v_client_city,  "city"),
                (self.v_client_state, "state"),
                (self.v_client_zip,   "zip"),
            ]:
                if c.get(key, ""):
                    widget.setText(c[key])
        self.schedule_preview()

    def _on_client_name_change(self):
        if self._autofill_timer:
            self._autofill_timer.stop()
        self._autofill_timer = QTimer()
        self._autofill_timer.setSingleShot(True)
        self._autofill_timer.timeout.connect(self._try_autofill)
        self._autofill_timer.start(self._AUTOFILL_DELAY_MS)

    def _try_autofill(self):
        name = self.v_client_name.text().strip()
        c = find_customer_by_name(name) or find_client(name)
        if c:
            for widget, key in [
                (self.v_client_email, "email"),
                (self.v_client_phone, "phone"),
                (self.v_client_addr,  "address"),
                (self.v_client_city,  "city"),
                (self.v_client_state, "state"),
                (self.v_client_zip,   "zip"),
            ]:
                if not widget.text().strip() and c.get(key, ""):
                    widget.setText(c[key])

    def _save_current_as_customer(self):
        from app.storage import save_customer
        name = self.v_client_name.text().strip()
        if not name:
            QMessageBox.warning(
                self.v_client_name.window(),
                "Missing Name", "Please enter a client name first.")
            return
        save_customer({
            "name":    name,
            "email":   self.v_client_email.text().strip(),
            "phone":   self.v_client_phone.text().strip(),
            "address": self.v_client_addr.text().strip(),
            "city":    self.v_client_city.text().strip(),
            "state":   self.v_client_state.text().strip(),
            "zip":     self.v_client_zip.text().strip(),
            "notes":   "",
        })
        ct = self.app._win._tab("customers_tab")
        if ct:
            ct.refresh()
        QMessageBox.information(
            self.v_client_name.window(),
            "Saved", f'"{name}" saved to Customers.')

    def _set_next_invoice_number(self):
        """Pre-fill invoice # with the next auto-incremented value if empty."""
        if not self.v_inv_num.text().strip():
            self.v_inv_num.setText(next_invoice_number())

    def _auto_save_customer(self, inv):
        """
        Silently upsert the invoice client into the Customers tab on generate.
        Merges into existing record if name matches; inserts new if not found.
        """
        from app.storage import find_customer_by_name, save_customer
        name = (inv.client_name or "").strip()
        if not name or name == "Client Name":
            return
        existing = find_customer_by_name(name)
        save_customer({
            "id":      existing.get("id", "") if existing else "",
            "name":    name,
            "email":   inv.client_email   or (existing or {}).get("email",   ""),
            "phone":   inv.client_phone   or (existing or {}).get("phone",   ""),
            "address": inv.client_address or (existing or {}).get("address", ""),
            "city":    inv.client_city    or (existing or {}).get("city",    ""),
            "state":   inv.client_state   or (existing or {}).get("state",   ""),
            "zip":     inv.client_zip     or (existing or {}).get("zip",     ""),
            "notes":   (existing or {}).get("notes", ""),
        })
        ct = self.app._win._tab("customers_tab")
        if ct:
            ct.refresh()

    # ── Due date helper ───────────────────────────────────────────────────────

    def fill_due_date(self):
        raw = self.v_issue.text().strip()
        try:
            base = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            base = date.today()
        self.v_due.setText(str(base + timedelta(days=30)))
        self.schedule_preview()

    # ── Preview ───────────────────────────────────────────────────────────────

    def schedule_preview(self, delay: int | None = None):
        if self._preview_timer:
            self._preview_timer.stop()
        ms = int(delay) if delay is not None else self._PREVIEW_DELAY_MS
        self._preview_timer = QTimer()
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview)
        self._preview_timer.start(ms)

    def _form_hash(self) -> str:
        parts = [
            self.v_client_name.text(),
            self.v_issue.text(), self.v_due.text(),
            self.v_currency.currentText(),
            self.v_template.currentText(),
            self.v_tax.text(), self.v_discount.text(),
            self.v_tax_label.text(),
            self.v_payment_link.text(),
            self.v_payment_terms.text(),
            self.v_notes.toPlainText(),
            self.app.accent_color,
        ]
        for dw, qw, pw in self._items:
            parts += [dw.text(), qw.text(), pw.text()]
        return "|".join(parts)

    def _build_invoice_from_form(self) -> Invoice:
        profile   = load_profile() or {}
        code, sym = CURRENCIES.get(
            self.v_currency.currentText(), ("USD", "$"))
        items = []
        for dw, qw, pw in self._items:
            desc = dw.text().strip()
            if desc:
                try:
                    items.append(
                        LineItem(desc, float(qw.text() or 1),
                                 float(pw.text() or 0)))
                except Exception:
                    pass
        if not items:
            items = [LineItem("Sample Item", 1, 0.00)]
        return Invoice(
            business_name=profile.get("name",    "Your Business LLC"),
            business_email=profile.get("email",  "hello@yourbusiness.com"),
            business_address=profile.get("address", "123 Main St"),
            business_phone=profile.get("phone",  ""),
            business_city=profile.get("city",    ""),
            business_state=profile.get("state",  ""),
            business_zip=profile.get("zip",      ""),
            logo_path=self.app.logo_path or profile.get("logo") or None,
            client_name=self.v_client_name.text()   or "Client Name",
            client_email=self.v_client_email.text() or "",
            client_phone=self.v_client_phone.text() or "",
            client_address=self.v_client_addr.text() or "",
            client_city=self.v_client_city.text()   or "",
            client_state=self.v_client_state.text() or "",
            client_zip=self.v_client_zip.text()     or "",
            invoice_number=self._resolve_invoice_number(
                self.v_inv_num.text()) or "INV-0001",
            issue_date=self.v_issue.text()   or str(date.today()),
            due_date=self.v_due.text()       or str(
                date.today() + timedelta(days=30)),
            currency=code, currency_symbol=sym,
            items=items,
            tax_rate=float(self.v_tax.text()      or 0),
            discount=float(self.v_discount.text() or 0),
            notes=self.v_notes.toPlainText().strip(),
            tax_label=self.v_tax_label.text().strip() or "Tax",
            payment_link=self.v_payment_link.text().strip(),
            payment_terms=self.v_payment_terms.text().strip(),
        )

    def _resolve_invoice_number(self, raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        prefix = (load_profile() or {}).get("prefix", "").strip()
        if not prefix:
            return raw
        if raw.startswith(prefix):
            return raw
        if raw.isdigit():
            return f"{prefix}{raw}"
        return raw

    def _render_preview(self):
        if not PDF2IMAGE_OK:
            self._signals.error.emit(
                "Install pdf2image:\npip install pdf2image")
            return
        template = self.v_template.currentText()
        if template not in WEASY_TEMPLATES:
            self._signals.error.emit("No preview available.")
            return

        current_hash = self._form_hash()
        if current_hash == self._last_preview_hash:
            return
        self._last_preview_hash = current_hash

        self._signals.busy.emit("Rendering…")
        inv = self._build_invoice_from_form()

        def _worker(inv=inv, tmpl=template, ac=self.app.accent_color):
            if not self._render_lock.acquire(blocking=False):
                self._last_preview_hash = None
                return
            try:
                log.info("DEBUG: preview worker started")
                from app.weasy_gen import generate_weasy
                log.info("DEBUG: generate_weasy imported OK")

                with tempfile.TemporaryDirectory() as tmp:
                    log.info("DEBUG: calling generate_weasy")
                    pdf_path = generate_weasy(
                        inv, WEASY_TEMPLATES[tmpl], Path(tmp), accent=ac)
                    log.info("DEBUG: generate_weasy done → %s", pdf_path)

                    poppler = find_poppler()
                    log.info("DEBUG: poppler path → %s", poppler)

                    pages = convert_from_path(
                        pdf_path, dpi=120,
                        first_page=1, last_page=1,
                        poppler_path=poppler,
                        thread_count=2,
                    )

                if not pages:
                    raise RuntimeError("pdf2image returned no pages.")

                from PIL import Image as PilImage
                pil   = pages[0]
                max_w = 900
                new_h = int(pil.height * (max_w / pil.width))
                pil   = pil.resize((max_w, new_h), PilImage.LANCZOS)
                buf   = io.BytesIO()
                pil.save(buf, format="PNG", optimize=False, compress_level=1)
                self._signals.done.emit(buf.getvalue())

            except Exception:
                # Catch everything — a bare exception in a daemon thread
                # silently kills the process on Windows
                err = traceback.format_exc()
                log.error("Preview worker error:\n%s", err)
                self._signals.error.emit(
                    f"Preview unavailable\n\n{err}")
            finally:
                self._render_lock.release()

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_preview(self, png_bytes: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes)
        label_w = self._preview_label.width() or 500
        label_h = self._preview_label.height() or 700
        scaled = pixmap.scaled(
            label_w, label_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation)
        self._preview_label.setPixmap(scaled)

    def _show_preview_error(self, msg: str):
        self._preview_label.clear()
        self._preview_label.setText(msg)

    def _show_preview_busy(self, msg: str):
        self._preview_label.clear()
        self._preview_label.setText(msg)

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(self):
        from app.license import (
            TRIAL_INVOICE_LIMIT, load_license,
            trial_invoices_remaining,
        )
        win = self.v_inv_num.window()
        status = load_license()
        if not status.licensed:
            remaining = trial_invoices_remaining()
            if remaining <= 0:
                reply = QMessageBox.question(
                    win, "Trial Limit Reached 🔒",
                    f"You've used all {TRIAL_INVOICE_LIMIT} free trial "
                    "invoices.\n\nActivate Offline Invoice to generate "
                    "unlimited invoices.\n\nGo to the License tab now?",
                    QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes:
                    self.app._win.set_tab("License")
                return
            if remaining == 1:
                QMessageBox.information(
                    win, "Last Free Invoice",
                    "This is your last free trial invoice.\n"
                    "After this, you'll need to activate to continue.\n\n"
                    "Find your license key in the License tab.")

        profile   = load_profile() or {}
        code, sym = CURRENCIES.get(
            self.v_currency.currentText(), ("USD", "$"))
        items = []
        for dw, qw, pw in self._items:
            if dw.text().strip():
                try:
                    items.append(
                        LineItem(dw.text(),
                                 float(qw.text()),
                                 float(pw.text())))
                except Exception:
                    pass
        inv = Invoice(
            business_name=profile.get("name", ""),
            business_email=profile.get("email", ""),
            business_address=profile.get("address", ""),
            business_phone=profile.get("phone", ""),
            business_city=profile.get("city", ""),
            business_state=profile.get("state", ""),
            business_zip=profile.get("zip", ""),
            logo_path=self.app.logo_path,
            client_name=self.v_client_name.text(),
            client_email=self.v_client_email.text(),
            client_phone=self.v_client_phone.text(),
            client_address=self.v_client_addr.text(),
            client_city=self.v_client_city.text(),
            client_state=self.v_client_state.text(),
            client_zip=self.v_client_zip.text(),
            invoice_number=self._resolve_invoice_number(
                self.v_inv_num.text()),
            issue_date=self.v_issue.text(),
            due_date=self.v_due.text(),
            currency=code, currency_symbol=sym,
            items=items,
            tax_rate=float(self.v_tax.text()      or 0),
            discount=float(self.v_discount.text() or 0),
            notes=self.v_notes.toPlainText().strip(),
            tax_label=self.v_tax_label.text().strip() or "Tax",
            payment_link=self.v_payment_link.text().strip(),
            payment_terms=self.v_payment_terms.text().strip(),
        )
        err = inv.validate()
        if err:
            QMessageBox.critical(win, "Validation Error", "\n".join(err))
            return

        if invoice_number_exists(inv.invoice_number):
            btns = (QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            answer = QMessageBox.question(
                win, "Duplicate Invoice Number",
                f'Invoice "{inv.invoice_number}" already exists in History.\n\n'
                f'• Yes    — generate anyway (creates a second record)\n'
                f'• No     — go back and change the invoice number\n'
                f'• Cancel — do nothing',
                btns, QMessageBox.Cancel)
            if answer in (QMessageBox.No, QMessageBox.Cancel):
                return

        try:
            custom_name = self.v_filename.text().strip() or None
            path = generate(inv, self.v_template.currentText(),
                            get_output_dir(), filename=custom_name)
            save_invoice(inv, path, template=self.v_template.currentText())
            save_client(inv.client_name, inv.client_email,
                        inv.client_address)
            self._auto_save_customer(inv)  # upsert to Customers tab
            ht = self.app._win._tab("history_tab")
            if ht:
                ht.refresh()
            self.build_recent_chips()
            self.v_inv_num.setText(next_invoice_number())  # advance counter
            reply = QMessageBox.question(
                win, "Success",
                "PDF saved!\n\nOpen it now?",
                QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self._open_file(path)
        except Exception as exc:
            QMessageBox.critical(win, "Generation Error", str(exc))

    # ── Clear ─────────────────────────────────────────────────────────────────

    def clear(self):
        self.v_inv_num.setText(next_invoice_number())  # keep counter
        for w in [self.v_client_name, self.v_client_email,
                  self.v_client_phone, self.v_client_addr,
                  self.v_client_city, self.v_client_state,
                  self.v_client_zip,
                  self.v_tax, self.v_discount,
                  self.v_payment_terms, self.v_payment_link,
                  self.v_filename]:
            w.clear()
        self.v_tax_label.setText("Tax")
        self.v_notes.setPlainText("Thank you for your business!")
        self.clear_items()
        self.add_item_row()
        self.refresh_totals()
        self._last_preview_hash = None
        self.schedule_preview()

    # ── Open file ─────────────────────────────────────────────────────────────

    @staticmethod
    def _open_file(p: str | None):
        if p and os.path.exists(p):
            if sys.platform == "win32":
                os.startfile(p)
            else:
                subprocess.run(
                    ["open" if sys.platform == "darwin"
                     else "xdg-open", p])