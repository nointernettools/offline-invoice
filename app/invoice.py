"""
Invoice data model. Pure Python — no framework dependency.
Validates fields and computes totals before PDF generation.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
import re

@dataclass
class LineItem:
    description: str
    qty:         float
    unit_price:  float

    @property
    def total(self) -> float:
        return round(self.qty * self.unit_price, 2)


@dataclass
class Invoice:
    # Your business
    business_name:    str
    business_email:   str
    business_address: str
    business_phone:   str = ""
    business_city:    str = ""
    business_state:   str = ""
    business_zip:     str = ""
    logo_path:        Optional[str] = None

    # Client
    client_name:    str = ""
    client_email:   str = ""
    client_phone:   str = ""
    client_address: str = ""
    client_city:    str = ""
    client_state:   str = ""
    client_zip:     str = ""

    # Currency
    currency:        str = "USD"
    currency_symbol: str = "$"

    # Invoice meta
    invoice_number:  str = ""
    issue_date:      str = ""
    due_date:        str = ""

    # Line items
    items: list[LineItem] = field(default_factory=list)

    # Extras
    tax_rate:     float = 0.0
    discount:     float = 0.0
    notes:        str   = ""
    tax_label:     str   = "Tax"   # e.g. "GST/HST", "Sales Tax", "VAT"
    payment_link:  str   = ""      # URL encoded as QR code in PDF (optional)
    payment_terms: str   = ""      # shown in footer e.g. "Net 30 · Late fee 1.5%/month"

    def __post_init__(self):
        if not self.invoice_number:
            self.invoice_number = self._next_number()
        if not self.issue_date:
            self.issue_date = str(date.today())
        if not self.due_date:
            self.due_date = str(date.today() + timedelta(days=30))

    @staticmethod
    def _next_number() -> str:
        """
        Generate the next invoice number using the saved prefix.

        Uses max(existing numbers) + 1 rather than len() so that deleting
        invoices never causes a number to be reused.
        """
        from app.storage import load_invoices, load_profile
        prefix = (load_profile() or {}).get("prefix", "").strip() or "INV-"

        # Extract the numeric suffix from every existing invoice that uses
        # this prefix, then increment the highest one found.
        max_n = 0
        for inv in load_invoices():
            num = str(inv.get("number", "")).strip()
            if num.startswith(prefix):
                suffix = num[len(prefix):]
                if suffix.isdigit():
                    max_n = max(max_n, int(suffix))

        return f"{prefix}{max_n + 1:04d}"

    # ── Computed totals ───────────────────────────────────────────────────────

    @property
    def subtotal(self) -> float:
        return round(sum(i.total for i in self.items), 2)

    @property
    def tax_amount(self) -> float:
        return round(self.subtotal * (self.tax_rate / 100), 2)

    @property
    def grand_total(self) -> float:
        return round(self.subtotal + self.tax_amount - self.discount, 2)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """Returns a list of error strings. Empty = valid."""
        errors = []
        if not self.business_name.strip():
            errors.append("Business name is required.")
        if not self.client_name.strip():
            errors.append("Client name is required.")
        if not self.items:
            errors.append("Add at least one line item.")
        for i, item in enumerate(self.items, 1):
            if not item.description.strip():
                errors.append(f"Item {i}: description is empty.")
            if item.qty <= 0:
                errors.append(f"Item {i}: quantity must be > 0.")
            if item.unit_price < 0:
                errors.append(f"Item {i}: price cannot be negative.")
        if self.client_email and not re.match(r"[^@]+@[^@]+\.[^@]+", self.client_email):
            errors.append("Client email format is invalid.")
        return errors