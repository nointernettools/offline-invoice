"""
Templates tab — browse and use recurring invoice templates.
PySide6 migration: pack/CTk → QVBoxLayout/QHBoxLayout, QScrollArea,
QLineEdit search with QTimer debounce, QDialog for edit modal.
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from app.icon_utils import get_icon

from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.pdf_gen import WEASY_TEMPLATES
from app.storage import delete_template, load_all_templates, save_template

ACCENT        = "#2563EB"

TEMPLATE_LIST = list(WEASY_TEMPLATES.keys())

CURRENCIES = {
    "USD ($)": ("USD", "$"),
    "EUR (€)": ("EUR", "€"),
    "GBP (£)": ("GBP", "£"),
    "CAD ($)": ("CAD", "$"),
    "AUD ($)": ("AUD", "$"),
}



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


class TemplatesTab:
    """Builds and owns the Templates tab UI (PySide6)."""

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
        top.setStyleSheet(
            "QFrame{background:white; border-radius:8px; border:none;}")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 10, 8)
        top_layout.setSpacing(8)

        title_lbl = QLabel("Invoice Templates")
        title_lbl.setStyleSheet(
            "font-size:14px; font-weight:700; color:#1f2937;"
            " background:transparent;")
        top_layout.addWidget(title_lbl)

        hint_lbl = QLabel(
            "Save any invoice as a template from the History tab  ·  "
            "Click ▶ Use to load it into the Invoice tab")
        hint_lbl.setStyleSheet(
            "font-size:11px; color:#9ca3af; background:transparent;")
        top_layout.addWidget(hint_lbl, stretch=1)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search templates…")
        self._search.setFixedWidth(200)
        self._search.textChanged.connect(self._debounce_search)
        top_layout.addWidget(self._search)

        refresh_btn = _action_btn("Refresh", "refresh", w=100, h=28)
        refresh_btn.clicked.connect(self.refresh)
        top_layout.addWidget(refresh_btn)

        root.addWidget(top)

        # ── Column headers ────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame{{background:{ACCENT}; border-radius:6px; border:none;}}")
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(10, 7, 10, 7)
        hdr_layout.setSpacing(0)

        for txt, w in [
            ("Template Name", 200),
            ("Client",        180),
            ("Line Items",     80),
            ("Tax",            80),
            ("Currency",       80),
        ]:
            lbl = QLabel(txt)
            lbl.setFixedWidth(w)
            lbl.setStyleSheet(
                "color:white; font-size:11px; font-weight:700;"
                " background:transparent;")
            hdr_layout.addWidget(lbl)

        hdr_layout.addStretch()
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
        self._list_layout.setContentsMargins(0, 0, 0, 0)
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
        # Clear existing rows
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        query     = self._search.text().strip().lower()
        all_tmpl  = load_all_templates()
        shown     = [
            t for t in all_tmpl
            if not query
            or query in t.get("name",   "").lower()
            or query in t.get("client", "").lower()
        ]

        if not shown:
            empty = QFrame()
            empty.setStyleSheet(
                "QFrame{background:white; border-radius:8px; border:none;}")
            el = QVBoxLayout(empty)
            el.setContentsMargins(12, 32, 12, 32)
            lbl = QLabel(
                "📋  No templates yet.\n\n"
                "Open the History tab, find an invoice and click "
                "☆ Template to save it here.")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#9ca3af; font-size:13px; background:transparent;")
            el.addWidget(lbl)
            self._list_layout.addWidget(empty)
            return

        for tmpl in shown:
            self._row(tmpl)

    # ── Row ───────────────────────────────────────────────────────────────────

    def _row(self, tmpl: dict):
        row = QFrame()
        row.setStyleSheet(
            "QFrame{background:white; border-radius:6px; border:none;}"
            "QFrame:hover{background:#f9fafb;}")
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.setFixedHeight(44)

        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 0, 8, 0)
        rl.setSpacing(4)

        def _cell(text: str, width: int, accent: bool = False,
                  muted: bool = False) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedWidth(width)
            style = "background:transparent; "
            if accent:
                style += f"color:{ACCENT}; font-weight:700; font-size:11px;"
            elif muted:
                style += "color:#9ca3af; font-size:11px;"
            else:
                style += "color:#374151; font-size:11px;"
            lbl.setStyleSheet(style)
            return lbl

        rl.addWidget(_cell(tmpl.get("name", "—"), 200, accent=True))
        rl.addWidget(_cell(tmpl.get("client", "—"), 180))

        n_items = len(tmpl.get("line_items", []))
        rl.addWidget(_cell(
            f"{n_items} item{'s' if n_items != 1 else ''}",
            80, muted=True))

        rate  = tmpl.get("tax_rate", 0)
        label = tmpl.get("tax_label", "Tax")
        rl.addWidget(_cell(
            f"{label} {rate}%" if rate else "No tax",
            80, muted=True))

        rl.addWidget(_cell(tmpl.get("currency", "USD"), 80, muted=True))
        rl.addStretch()

        # Action buttons
        use_btn = _action_btn("Use", w=80, h=28)
        use_btn.clicked.connect(lambda _, t=tmpl: self._use(t))
        rl.addWidget(use_btn)

        edit_btn = _action_btn("Edit", "edit", w=80, h=28)
        edit_btn.clicked.connect(lambda _, t=tmpl: self._open_edit_modal(t))
        rl.addWidget(edit_btn)

        del_btn = QPushButton()
        del_btn.setIcon(get_icon("delete"))
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(
            "QPushButton{background:#fee2e2; color:#fee2e2; border:none;"
            " font-size:13px; border-radius:4px;}"
            "QPushButton:hover{background:#f72d2d; color:#dc2626;}")
        del_btn.clicked.connect(lambda _, tid=tmpl["id"]: self._delete(tid))
        rl.addWidget(del_btn)

        self._list_layout.addWidget(row)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _use(self, tmpl: dict):
        it = self.app.invoice_tab

        # Helper: set QLineEdit text
        def st(widget, val):
            widget.setText(str(val) if val else "")

        st(it.v_client_name,  tmpl.get("client",         ""))
        st(it.v_client_email, tmpl.get("client_email",   ""))
        st(it.v_client_phone, tmpl.get("client_phone",   ""))
        st(it.v_client_addr,  tmpl.get("client_address", ""))
        st(it.v_client_city,  tmpl.get("client_city",    ""))
        st(it.v_client_state, tmpl.get("client_state",   ""))
        st(it.v_client_zip,   tmpl.get("client_zip",     ""))

        today = date.today()
        st(it.v_issue,   str(today))
        st(it.v_due,     str(today + timedelta(days=30)))
        st(it.v_inv_num, "")

        html_tmpl = tmpl.get("template", "")
        if html_tmpl and html_tmpl in TEMPLATE_LIST:
            it.v_template.setCurrentText(html_tmpl)

        currency = tmpl.get("currency", "USD")
        for key, (code, _) in CURRENCIES.items():
            if code == currency:
                it.v_currency.setCurrentText(key)
                break

        st(it.v_tax_label, tmpl.get("tax_label", "Tax"))
        st(it.v_tax,       str(tmpl.get("tax_rate", 0)))
        st(it.v_discount,  str(tmpl.get("discount", 0)))
        it.v_notes.setPlainText(tmpl.get("notes", ""))

        line_items = tmpl.get("line_items", [])
        if line_items:
            it.load_items_from(line_items)
        else:
            it.clear_items()
            it.add_item_row()

        it.refresh_totals()
        it.schedule_preview()
        self.app.tabs.set_tab("Invoice") if hasattr(self.app.tabs, "set_tab") \
            else None

    def _delete(self, template_id: str):
        reply = QMessageBox.question(
            self._scroll, "Delete Template",
            "Remove this template? \nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            delete_template(template_id)
            self.refresh()

    def _open_edit_modal(self, tmpl: dict):
        win = self._scroll.window()

        dlg = QDialog(win)
        dlg.setWindowTitle("Edit Template")
        dlg.setFixedWidth(420)
        dlg.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 12, 20, 12)
        hl_lbl = QLabel("Edit Template")
        hl_lbl.setStyleSheet(
            "color:white; font-size:14px; font-weight:700;"
            " background:transparent;")
        hl_lbl.setAlignment(Qt.AlignCenter)
        hl.addWidget(hl_lbl)
        layout.addWidget(hdr)

        # Form
        form = QWidget()
        form.setStyleSheet("background:white;")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(20, 12, 20, 8)
        fl.setSpacing(6)

        def _field(label: str, value: str = "") -> QLineEdit:
            lbl = QLabel(label)
            lbl.setStyleSheet(
                "font-size:12px; color:#374151; background:transparent;")
            fl.addWidget(lbl)
            entry = QLineEdit(value)
            fl.addWidget(entry)
            return entry

        f_name   = _field("Template Name *", tmpl.get("name",         ""))
        f_client = _field("Client",          tmpl.get("client",        ""))
        f_email  = _field("Client Email",    tmpl.get("client_email",  ""))

        layout.addWidget(form)

        # Footer
        foot = QFrame()
        foot.setStyleSheet("background:white; border-radius:0;")
        footl = QHBoxLayout(foot)
        footl.setContentsMargins(20, 4, 20, 16)
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

        save_btn = _action_btn("Save", "save", w=120, h=32)
        footl.addWidget(save_btn)

        layout.addWidget(foot)

        def on_save():
            name = f_name.text().strip()
            if not name:
                QMessageBox.warning(
                    dlg, "Missing Name",
                    "Template name is required.")
                return
            save_template({
                **tmpl,
                "name":         name,
                "client":       f_client.text().strip(),
                "client_email": f_email.text().strip(),
            })
            self.refresh()
            dlg.accept()

        save_btn.clicked.connect(on_save)

        # Centre over parent
        dlg.adjustSize()
        px = win.x() + (win.width()  - dlg.width())  // 2
        py = win.y() + (win.height() - dlg.height()) // 2
        dlg.move(px, py)
        dlg.exec()