"""
Shared FPDF base class and color constants used by all templates.
"""
import os
from fpdf import FPDF
from PIL import Image as PilImage
from app.invoice import Invoice
# <-- Removed OUTPUT_DIR import here

# ── Shared colors (R, G, B) ───────────────────────────────────────────────────
WHITE        = (255, 255, 255)
DARK         = (30,  30,  30)
MUTED        = (110, 110, 110)
ACCENT       = (37,  99,  235)
ACCENT_LIGHT = (219, 234, 254)
LIGHT_GRAY   = (245, 245, 245)
MID_GRAY     = (200, 200, 200)

class _Base(FPDF):
    """Shared helpers inherited by all three templates."""

    def _money(self, inv: Invoice, amount: float) -> str:
        return f"{inv.currency_symbol}{amount:,.2f}"

    def _set_font_regular(self, size=10):
        self.set_font("Helvetica", size=size)

    def _set_font_bold(self, size=10):
        self.set_font("Helvetica", style="B", size=size)

    def _divider(self, color=MID_GRAY):
        self.set_draw_color(*color)
        self.line(self.l_margin, self.get_y(), 210 - self.r_margin, self.get_y())

    def _place_logo(self, inv: Invoice, x: float, y: float, max_w: float, max_h: float):
        """Place logo at (x, y) constrained to max_w × max_h, preserving aspect ratio."""
        if not (inv.logo_path and os.path.exists(inv.logo_path)):
            return 0  
        try:
            with PilImage.open(inv.logo_path) as img:
                iw, ih = img.size
            ratio  = min(max_w / iw, max_h / ih)
            w, h   = iw * ratio, ih * ratio
            self.image(inv.logo_path, x=x, y=y, w=w, h=h)
            return h
        except Exception:
            return 0  

    def _client_block(self, inv: Invoice, x: float, y: float, w: float):
        """
        Render full client address block at (x, y) within column width w.
        Handles missing fields gracefully — no orphan commas or blank lines.
        """
        self.set_xy(x, y)
        self._set_font_bold(9)
        self.set_text_color(*DARK)
        self.cell(w, 5, inv.client_name, ln=True)

        self._set_font_regular(9)
        self.set_text_color(*MUTED)

        for line in filter(None, [
            inv.client_email,
            inv.client_phone,
            inv.client_address,
        ]):
            self.set_x(x)
            self.cell(w, 5, line, ln=True)

        # City, State ZIP — only show parts that exist
        csz_parts = [p for p in [inv.client_city, inv.client_state, inv.client_zip] if p.strip()]
        if csz_parts:
            self.set_x(x)
            self.cell(w, 5, ", ".join(csz_parts), ln=True)

        self.set_text_color(*DARK)
        # Default widths for Classic/Modern. 
        # For Consultant, we will pass smaller widths from that file.
        if col_w is None:
            col_w = [90, 25, 35, 35]
            
        headers = ["Description", "Qty", "Unit Price", "Total"]
        aligns  = ["L", "C", "R", "R"]

        self.set_fill_color(*ACCENT)
        self.set_text_color(*WHITE)
        self._set_font_bold(9)
        for w, h, a in zip(col_w, headers, aligns):
            self.cell(w, 8, h, fill=True, align=a)
        self.ln()

        self.set_text_color(*DARK)
        self._set_font_regular(9)
        fill = False
        for item in inv.items:
            self.set_fill_color(*LIGHT_GRAY)
            # Clip description so it doesn't overflow the cell
            desc = item.description[:40] if col_w[0] < 60 else item.description[:55]
            self.cell(col_w[0], 7, desc, fill=fill, align="L")
            self.cell(col_w[1], 7, str(item.qty),                    fill=fill, align="C")
            self.cell(col_w[2], 7, self._money(inv, item.unit_price), fill=fill, align="R")
            self.cell(col_w[3], 7, self._money(inv, item.total),      fill=fill, align="R")
            self.ln()
            fill = not fill
        self.ln(2)

    def _totals_block(self, inv: Invoice, x_label=120):
        rows = [("Subtotal", self._money(inv, inv.subtotal))]
        if inv.tax_rate:
            rows.append((f"Tax ({inv.tax_rate}%)", self._money(inv, inv.tax_amount)))
        if inv.discount:
            rows.append(("Discount", f"- {self._money(inv, inv.discount)}"))

        self._set_font_regular(9)
        self.set_text_color(*MUTED)
        for label, value in rows:
            self.set_x(x_label)
            self.cell(45, 7, label, align="L")
            self.cell(30, 7, value, align="R")
            self.ln()

        self.set_fill_color(*ACCENT_LIGHT)
        self.set_text_color(*ACCENT)
        self._set_font_bold(11)
        self.set_x(x_label)
        self.cell(75, 9, f"Total Due   {self._money(inv, inv.grand_total)}",
                  fill=True, align="R")
        self.ln(14)

    def _notes_block(self, inv: Invoice):
        if inv.notes:
            self._set_font_bold(9)
            self.set_text_color(*MUTED)
            self.cell(0, 6, "Notes", ln=True)
            self._set_font_regular(9)
            self.set_text_color(*DARK)
            self.multi_cell(0, 5, inv.notes)