"""
First-run / re-run industry wizard.
Card selection uses QFrame + Signal pattern for reliable border updates:
  - Each card emits a `clicked` signal
  - WizardModal tracks `_selected_card` and calls set_selected() on all cards
  - No QAbstractButton, no QButtonGroup repaint timing issues
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from app.industry_packs import PACKS, IndustryPack

ACCENT = "#2563eb"

_STYLE_DEFAULT = """
    _PackCard {
        background-color: white;
        border: 1.5px solid #e5e7eb;
        border-radius: 10px;
    }
    _PackCard:hover {
        background-color: #f9fafb;
        border-color: #d1d5db;
    }
"""
_STYLE_SELECTED = """
    _PackCard {
        background-color: white;
        border: 2.5px solid #2563eb;
        border-radius: 10px;
    }
    _PackCard:hover {
        background-color: #f0f5ff;
    }
"""


def _pack_pixmap(pack: IndustryPack, size: int = 24) -> QPixmap | None:
    path = Path(pack.icon) if pack.icon else None
    if path and path.exists():
        px = QPixmap(str(path))
        if not px.isNull():
            return px.scaled(size, size, Qt.KeepAspectRatio,
                             Qt.SmoothTransformation)
    return None


class _PackCard(QFrame):
    """
    Clickable industry card. Emits clicked(self) on left press.
    WizardModal calls set_selected(True/False) to toggle the border instantly.
    """
    clicked = Signal(object)   # passes self

    def __init__(self, pack: IndustryPack, parent=None):
        super().__init__(parent)
        self._pack = pack
        self.setFrameShape(QFrame.NoFrame)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(120)
        self.setStyleSheet(_STYLE_DEFAULT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header: icon + name
        hdr = QWidget()
        hdr.setAttribute(Qt.WA_TransparentForMouseEvents)
        hdr.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(24, 24)
        icon_lbl.setStyleSheet("background:transparent;")
        px = _pack_pixmap(pack, 24)
        if px:
            icon_lbl.setPixmap(px)
        else:
            icon_lbl.setText("📋")
            icon_lbl.setStyleSheet("font-size:16px; background:transparent;")
        hl.addWidget(icon_lbl)

        name_lbl = QLabel(pack.label)
        name_lbl.setWordWrap(True)
        name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        name_lbl.setStyleSheet(
            "font-size:12px; font-weight:700; color:#111827;"
            " background:transparent;")
        hl.addWidget(name_lbl, stretch=1)
        layout.addWidget(hdr)

        # Description
        desc = QLabel(pack.description)
        desc.setWordWrap(True)
        desc.setAttribute(Qt.WA_TransparentForMouseEvents)
        desc.setStyleSheet(
            "font-size:10px; color:#6b7280; background:transparent;")
        layout.addWidget(desc)

        # Line item preview
        preview = QFrame()
        preview.setAttribute(Qt.WA_TransparentForMouseEvents)
        preview.setStyleSheet(
            "background:#f9fafb; border-radius:5px; border:none;")
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(8, 4, 8, 4); pl.setSpacing(1)
        for item in pack.line_items[:2]:
            lbl = QLabel(f"· {item['description']}")
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            lbl.setStyleSheet(
                "font-size:9px; color:#9ca3af; background:transparent;")
            pl.addWidget(lbl)
        if len(pack.line_items) > 2:
            more = QLabel(f"+ {len(pack.line_items) - 2} more…")
            more.setAttribute(Qt.WA_TransparentForMouseEvents)
            more.setStyleSheet(
                "font-size:9px; color:#d1d5db; background:transparent;")
            pl.addWidget(more)
        layout.addWidget(preview)

    @property
    def pack(self):
        return self._pack

    def set_selected(self, selected: bool):
        """Instantly switch border. Called by WizardModal — no repaint delay."""
        self.setStyleSheet(_STYLE_SELECTED if selected else _STYLE_DEFAULT)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)


class WizardModal(QDialog):

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Industry Setup Wizard")
        self.setFixedWidth(660)
        self.setMinimumHeight(500)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.result_pack: IndustryPack | None = None
        self._selected_card: _PackCard | None = None
        self._cards: list[_PackCard] = []

        self._build()
        self.adjustSize()

        px = parent.x() + (parent.width()  - self.width())  // 2
        py = parent.y() + (parent.height() - self.height()) // 2
        self.move(px, py)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(f"background:{ACCENT}; border-radius:0;")
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(24, 20, 24, 18); hl.setSpacing(4)

        title = QLabel("Welcome to Offline Invoice")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color:white; font-size:18px; font-weight:700;"
            " background:transparent;")
        hl.addWidget(title)

        sub = QLabel(
            "Pick your industry — we'll pre-fill templates, line items "
            "and settings for you.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            "color:#bfdbfe; font-size:11px; background:transparent;")
        hl.addWidget(sub)
        root.addWidget(hdr)

        # Card grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:#f3f4f6; border:none;}")
        root.addWidget(scroll, stretch=1)

        grid_w = QWidget()
        grid_w.setStyleSheet("background:#f3f4f6;")
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(20, 16, 20, 16)
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for i, pack in enumerate(PACKS):
            card = _PackCard(pack)
            card.clicked.connect(self._on_card_clicked)
            grid.addWidget(card, i // 2, i % 2)
            self._cards.append(card)

        scroll.setWidget(grid_w)

        # Footer
        foot = QFrame()
        foot.setStyleSheet("background:white; border-top:1px solid #e5e7eb;")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 12, 20, 16); fl.setSpacing(8)

        skip_btn = QPushButton("Skip for now")
        skip_btn.setFixedSize(120, 34)
        skip_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#6b7280;"
            " border:1px solid #d1d5db; border-radius:6px; font-weight:400;}"
            "QPushButton:hover{background:#f9fafb; border-color:#9ca3af;}")
        skip_btn.clicked.connect(self.reject)
        fl.addWidget(skip_btn)
        fl.addStretch()

        self._sel_lbl = QLabel("No industry selected")
        self._sel_lbl.setStyleSheet(
            "color:#9ca3af; font-size:11px; background:transparent;")
        fl.addWidget(self._sel_lbl)

        self._apply_btn = QPushButton("Apply & Continue →")
        self._apply_btn.setFixedSize(180, 34)
        self._apply_btn.setEnabled(False)
        self._apply_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT}; color:white; border:none;"
            f" border-radius:6px; font-weight:600;}}"
            f"QPushButton:hover{{background:#1d4ed8;}}"
            f"QPushButton:disabled{{background:#9ca3af; color:#e5e7eb;}}")
        self._apply_btn.clicked.connect(self._apply)
        fl.addWidget(self._apply_btn)

        root.addWidget(foot)

    def _on_card_clicked(self, card):
        """Deselect previous, select clicked — border updates immediately."""
        if self._selected_card and self._selected_card is not card:
            self._selected_card.set_selected(False)

        self._selected_card = card
        card.set_selected(True)

        self._sel_lbl.setText(f"Selected: {card.pack.label}")
        self._sel_lbl.setStyleSheet(
            f"color:{ACCENT}; font-size:11px;"
            " font-weight:600; background:transparent;")
        self._apply_btn.setEnabled(True)
        short = (card.pack.label if len(card.pack.label) <= 14
                 else card.pack.label[:12] + "…")
        self._apply_btn.setText(f"Apply {short} →")

    def _apply(self):
        if self._selected_card:
            self.result_pack = self._selected_card.pack
        self.accept()


def run_wizard(parent: QWidget) -> IndustryPack | None:
    modal = WizardModal(parent)
    modal.exec()
    return modal.result_pack