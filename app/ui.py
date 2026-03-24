"""
Offline Invoice - App coordinator (PySide6).
QMainWindow with QTabWidget shell.
All business logic lives in app/tabs/*.py - untouched.
"""
from __future__ import annotations

import logging
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

from app.color_utils import DEFAULT_ACCENT
from app.eula import show_eula_if_needed
from app.updater import check_for_update
from app.industry_packs import IndustryPack
from app.license import LicenseStatus, load_license, recheck_in_background
from app.pdf_gen import WEASY_TEMPLATES
from app.storage import (
    is_first_run, load_invoices, load_profile,
    mark_setup_done,
)

log = logging.getLogger(__name__)

APP_VERSION = "1.0.0"
APP_NAME    = "Offline Invoice"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _icon_path() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "app" / "assets" / "icon.ico"  # type: ignore
    else:
        p = Path(__file__).parent / "assets" / "icon.ico"
    return p if p.is_file() else None


def _asset(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "app" / "assets" / name  # type: ignore
    return Path(__file__).parent / "assets" / name


# ── Application stylesheet ────────────────────────────────────────────────────

def _build_qss(accent: str = DEFAULT_ACCENT) -> str:
    return f"""
QWidget {{
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: #1f2937;
    background-color: #f3f4f6;
}}

/* Tab bar */
QTabWidget::pane {{
    border: none;
    background: #f3f4f6;
}}
QTabBar::tab {{
    background: #e5e7eb;
    color: #6b7280;
    padding: 8px 20px;
    border: none;
    border-bottom: 3px solid transparent;
    font-weight: 500;
    min-width: 90px;
}}
QTabBar::tab:selected {{
    background: #f3f4f6;
    color: {accent};
    border-bottom: 3px solid {accent};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: #dbeafe;
    color: {accent};
}}

/* Scroll bars */
QScrollBar:vertical {{
    background: #f3f4f6;
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #d1d5db;
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #9ca3af; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{
    background: #d1d5db;
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: #9ca3af; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Primary buttons */
QPushButton {{
    background: {accent};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: 600;
}}
QPushButton:hover   {{ background: {accent}cc; }}
QPushButton:pressed {{ background: {accent}99; }}
QPushButton:disabled {{ background: #9ca3af; color: #e5e7eb; }}

/* Flat / outline buttons — use setObjectName("flat") */
QPushButton#flat,
QPushButton[flat="true"] {{
    background: transparent;
    color: #374151;
    border: 1px solid #d1d5db;
    font-weight: 400;
}}
QPushButton#flat:hover,
QPushButton[flat="true"]:hover {{ background: #f9fafb; border-color: #9ca3af; }}
QPushButton#flat:pressed,
QPushButton[flat="true"]:pressed {{ background: #f3f4f6; }}

/* Danger buttons — use setObjectName("danger") */
QPushButton#danger,
QPushButton[danger="true"] {{
    background: transparent;
    color: #dc2626;
    border: 1px solid #dc2626;
    font-weight: 400;
}}
QPushButton#danger:hover,
QPushButton[danger="true"]:hover {{ background: #fee2e2; }}

/* Inputs */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 6px 10px;
    color: #1f2937;
    selection-background-color: #bfdbfe;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {accent};
}}
QLineEdit:disabled {{ background: #f9fafb; color: #9ca3af; }}

/* Combo boxes */
QComboBox {{
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 5px 10px;
    color: #1f2937;
    min-height: 28px;
}}
QComboBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    selection-background-color: #dbeafe;
    selection-color: #1e40af;
    outline: none;
    padding: 2px;
}}

/* Check boxes */
QCheckBox {{
    spacing: 6px;
    color: #374151;
}}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: white;
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}

/* Progress bar */
QProgressBar {{
    background: #e5e7eb;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 5px;
}}

/* Message boxes — clean, no grey icon background */
QMessageBox {{
    background: white;
    border-radius: 8px;
}}
QMessageBox QLabel {{
    color: #1f2937;
    font-size: 13px;
    background: white;
    padding: 4px 0;
}}
QMessageBox QLabel#qt_msgbox_label {{
    color: #1f2937;
    font-size: 13px;
    min-width: 260px;
}}
QMessageBox QLabel#qt_msgboxex_icon_label {{
    padding: 0;
    background: white;
}}
QMessageBox QPushButton {{
    background: {accent};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 20px;
    font-weight: 600;
    min-width: 80px;
}}
QMessageBox QPushButton:hover {{ background: #1d4ed8; }}
QMessageBox QPushButton[text="Cancel"],
QMessageBox QPushButton[text="No"] {{
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
}}
QMessageBox QPushButton[text="Cancel"]:hover,
QMessageBox QPushButton[text="No"]:hover {{
    background: #f9fafb;
}}
"""


# ── App (QApplication subclass) ───────────────────────────────────────────────

class App(QApplication):
    """
    PySide6 QApplication. Owns the main window and shared state.
    Tabs access shared state via self.app (the App instance).
    """

    def __init__(self, argv: list[str]):
        super().__init__(argv)

        self.setAttribute(Qt.AA_UseHighDpiPixmaps)
        self.setApplicationName(APP_NAME)
        self.setApplicationVersion(APP_VERSION)
        self.setOrganizationName("OfflineTools")

        self.setStyleSheet(_build_qss())

        ico = _icon_path()
        if ico:
            self.setWindowIcon(QIcon(str(ico)))

        # Shared state — same attributes tabs expect
        self.accent_color:   str           = DEFAULT_ACCENT
        self.logo_path:      str | None    = None
        self.license_status: LicenseStatus = load_license()

        # Build and show main window
        self._win = MainWindow(self)
        self._win.show()
        # EULA — shown once on first launch; exit if declined
        if not show_eula_if_needed(self._win):
            import sys as _sys; _sys.exit(0)
        # Check for updates in background — non-blocking
        check_for_update(APP_VERSION, self._win)

    # ── QTimer helpers — same API as CTk after() / after_cancel() ─────────────

    def after(self, ms: int, fn) -> QTimer:
        """Run fn() once after ms milliseconds. Returns QTimer for cancellation."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(fn)
        timer.start(ms)
        return timer

    def after_cancel(self, timer: QTimer | None):
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    # ── Accent color update ───────────────────────────────────────────────────

    def update_accent(self, new_accent: str):
        """Re-apply the full stylesheet with a new accent colour."""
        self.accent_color = new_accent
        self.setStyleSheet(_build_qss(new_accent))

    # ── Tab proxy properties — tabs call self.app.history_tab etc. ─────────────

    @property
    def tabs(self):           return self._win.tabs

    @property
    def invoice_tab(self):    return self._win.invoice_tab

    @property
    def customers_tab(self):  return self._win._tab("customers_tab")

    @property
    def history_tab(self):    return self._win._tab("history_tab")

    @property
    def templates_tab(self):  return self._win._tab("templates_tab")

    @property
    def profile_tab(self):    return self._win.profile_tab

    @property
    def license_tab(self):    return self._win._tab("license_tab")

    # ── Window geometry helpers ───────────────────────────────────────────────

    def winfo_x(self) -> int:      return self._win.x()
    def winfo_y(self) -> int:      return self._win.y()
    def winfo_width(self) -> int:  return self._win.width()
    def winfo_height(self) -> int: return self._win.height()

    # ── License ───────────────────────────────────────────────────────────────

    def _on_license_recheck(self, status: LicenseStatus):
        self.license_status = status
        lt = self._win._tab("license_tab")
        if lt:
            lt.refresh()
        if not status.licensed:
            QMessageBox.warning(
                self._win, "License Issue",
                f"{status.message}\n\nPlease check the License tab.")

    @property
    def is_licensed(self) -> bool:
        return self.license_status.licensed

    # ── Delegates to window ───────────────────────────────────────────────────

    def launch_wizard(self): self._win.launch_wizard()
    def show_about(self):    self._win.show_about()


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self, app: App):
        super().__init__()
        self.app = app

        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 700)

        ico = _icon_path()
        if ico:
            self.setWindowIcon(QIcon(str(ico)))

        # Tab instances
        self.invoice_tab:   object | None = None
        self.profile_tab:   object | None = None
        self.customers_tab: object | None = None
        self.history_tab:   object | None = None
        self.templates_tab: object | None = None
        self.license_tab:   object | None = None

        self._build_tabs()

        # Defer profile load until after exec() starts so self._win is fully
        # assigned and invoice_tab is guaranteed to exist.
        def _safe_profile_load():
            log.info("DEBUG: profile_tab.load() starting")
            try:
                self.profile_tab.load()
                log.info("DEBUG: profile_tab.load() completed OK")
            except Exception:
                log.critical("DEBUG: profile_tab.load() crashed:\n%s",
                             traceback.format_exc())

        QTimer.singleShot(0, _safe_profile_load)

        # Ctrl+G → generate
        sc = QShortcut(QKeySequence("Ctrl+G"), self)
        sc.activated.connect(lambda: self.invoice_tab.generate())

        recheck_in_background(on_result=self.app._on_license_recheck)
        log.info("DEBUG: recheck_in_background registered")

        if is_first_run():
            log.info("DEBUG: first run — scheduling wizard at 300ms")
            QTimer.singleShot(300, self.launch_wizard)
        else:
            log.info("DEBUG: not first run — scheduling overdue check at 600ms")
            QTimer.singleShot(600, self._check_overdue)

    def _check_overdue(self):
        log.info("DEBUG: _check_overdue fired")

    # ── Tab shell ─────────────────────────────────────────────────────────────

    def _build_tabs(self):
        from app.tabs.invoice_tab import InvoiceTab
        from app.tabs.profile_tab import ProfileTab

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.setCentralWidget(self.tabs)

        tab_names = [
            "Invoice", "Customers", "History",
            "Templates", "Business Profile", "License",
        ]
        self._tab_widgets: dict[str, QWidget] = {}
        for name in tab_names:
            w = QWidget()
            self.tabs.addTab(w, name)
            self._tab_widgets[name] = w

        log.info("DEBUG: building InvoiceTab")
        self.invoice_tab = InvoiceTab(self._tab_widgets["Invoice"], self.app)
        log.info("DEBUG: InvoiceTab built OK")

        log.info("DEBUG: building ProfileTab")
        self.profile_tab = ProfileTab(self._tab_widgets["Business Profile"], self.app)
        log.info("DEBUG: ProfileTab built OK")

        QTimer.singleShot(200, self._preload_tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _preload_tabs(self):
        from app.tabs.history_tab   import HistoryTab
        from app.tabs.customers_tab import CustomersTab
        from app.tabs.templates_tab import TemplatesTab
        from app.tabs.license_tab   import LicenseTab

        build_order = [
            ("history_tab",   lambda: HistoryTab(   self._tab_widgets["History"],   self.app)),
            ("customers_tab", lambda: CustomersTab( self._tab_widgets["Customers"], self.app)),
            ("templates_tab", lambda: TemplatesTab( self._tab_widgets["Templates"], self.app)),
            ("license_tab",   lambda: LicenseTab(   self._tab_widgets["License"],   self.app)),
        ]

        def _build_next(items):
            if not items:
                log.info("DEBUG: all secondary tabs preloaded OK")
                return
            attr, factory = items[0]
            log.info("DEBUG: building %s", attr)
            try:
                setattr(self, attr, factory())
                log.info("DEBUG: %s built OK", attr)
            except Exception:
                log.error("Tab build failed: %s\n%s", attr, traceback.format_exc())
            QTimer.singleShot(50, lambda: _build_next(items[1:]))

        _build_next(build_order)

    def _on_tab_changed(self, index: int):
        name = self.tabs.tabText(index)
        attr_map = {
            "Customers": "customers_tab",
            "History":   "history_tab",
            "Templates": "templates_tab",
            "License":   "license_tab",
        }
        attr = attr_map.get(name)
        if attr and getattr(self, attr) is None:
            self._tab(attr)

    def _tab(self, attr: str):
        obj = getattr(self, attr, None)
        if obj is not None:
            return obj

        from app.tabs.history_tab   import HistoryTab
        from app.tabs.customers_tab import CustomersTab
        from app.tabs.templates_tab import TemplatesTab
        from app.tabs.license_tab   import LicenseTab

        tab_map = {
            "customers_tab": lambda: CustomersTab(self._tab_widgets["Customers"], self.app),
            "history_tab":   lambda: HistoryTab(  self._tab_widgets["History"],   self.app),
            "templates_tab": lambda: TemplatesTab(self._tab_widgets["Templates"], self.app),
            "license_tab":   lambda: LicenseTab(  self._tab_widgets["License"],   self.app),
        }
        if attr in tab_map:
            try:
                obj = tab_map[attr]()
                setattr(self, attr, obj)
            except Exception:
                log.error("On-demand tab build failed: %s\n%s",
                          attr, traceback.format_exc())
        return getattr(self, attr, None)

    def set_tab(self, name: str):
        """Switch to a tab by name — replaces self.tabs.set('History')."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                self.tabs.setCurrentIndex(i)
                return

    # ── Overdue check ─────────────────────────────────────────────────────────

    def _check_overdue(self):
        today   = date.today()
        overdue = [
            i for i in load_invoices()
            if i.get("status", "") == "Sent"
            and self._is_past_due(i.get("due_date", ""), today)
        ]
        if not overdue:
            return
        n = len(overdue)
        QMessageBox.warning(
            self, "Overdue Invoices",
            f"You have {n} overdue invoice{'s' if n > 1 else ''}.\n\n"
            "The History tab will open\nwith the Overdue filter active.",
        )
        self.set_tab("History")
        ht = self._tab("history_tab")
        if ht:
            ht._set_filter("Overdue")

    @staticmethod
    def _is_past_due(due_str: str, today: date) -> bool:
        try:
            return datetime.strptime(due_str, "%Y-%m-%d").date() < today
        except Exception:
            return False

    # ── About dialog ──────────────────────────────────────────────────────────

    def show_about(self):
        from app.storage import load_all_customers
        from PySide6.QtGui import QFont

        dlg = QDialog(self)
        dlg.setWindowTitle(f"About {APP_NAME}")
        dlg.setFixedWidth(380)
        dlg.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Accent header
        hdr = QFrame()
        hdr.setStyleSheet(
            f"background:{self.app.accent_color}; border-radius:0;")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(20, 18, 20, 16)

        t = QLabel(APP_NAME)
        t.setAlignment(Qt.AlignCenter)
        f = QFont(); f.setPointSize(16); f.setBold(True)
        t.setFont(f)
        t.setStyleSheet("color:white; background:transparent;")

        v = QLabel(f"Version {APP_VERSION}")
        v.setAlignment(Qt.AlignCenter)
        v.setStyleSheet(
            "color:#bfdbfe; background:transparent; font-size:12px;")

        hl.addWidget(t)
        hl.addWidget(v)
        layout.addWidget(hdr)

        # Body
        body = QFrame()
        body.setStyleSheet("background:white;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 16, 24, 8)
        bl.setSpacing(6)

        n_inv  = len(load_invoices())
        n_cust = len(load_all_customers())

        for text in [
            f"  {n_inv} invoice{'s' if n_inv != 1 else ''} on record",
            f"  {n_cust} customer{'s' if n_cust != 1 else ''} saved",
            "",
            "Built with Python  \u00b7  PySide6  \u00b7  WeasyPrint",
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                "color:#374151; background:transparent; font-size:12px;")
            bl.addWidget(lbl)

        layout.addWidget(body)

        # Close button
        bf = QFrame()
        bf.setStyleSheet("background:white;")
        bfl = QHBoxLayout(bf)
        bfl.setContentsMargins(20, 4, 20, 16)
        btn = QPushButton("Close")
        btn.setFixedWidth(120)
        btn.clicked.connect(dlg.accept)
        bfl.addStretch()
        bfl.addWidget(btn)
        bfl.addStretch()
        layout.addWidget(bf)

        dlg.exec()

    # ── Wizard ────────────────────────────────────────────────────────────────

    def launch_wizard(self):
        from app.wizard import run_wizard

        it = self.invoice_tab
        if hasattr(it, "_preview_timer") and it._preview_timer:
            it._preview_timer.stop()

        pack = run_wizard(self)
        if pack:
            self._apply_pack(pack)
            mark_setup_done()

    def _apply_pack(self, pack: IndustryPack):
        it = self.invoice_tab
        pt = self.profile_tab

        if pack.template in WEASY_TEMPLATES:
            it.v_template.setCurrentText(pack.template)

        pt.apply_accent(pack.accent_color)
        pt.apply_tax_label(pack.tax_label)

        it.load_items_from(pack.line_items)
        it.v_notes.setPlainText(pack.notes)

        profile = load_profile() or {}
        profile.update({
            "accent_color":       pack.accent_color,
            "industry":           pack.id,
            "template":           pack.template,
            "tax_label":          pack.tax_label,
            "default_terms":      pack.default_terms,
            "default_notes":      pack.notes,
            "default_line_items": [],
        })
        from app.storage import save_profile
        save_profile(profile)

        it.refresh_totals()
        it.schedule_preview()
        self.set_tab("Invoice")