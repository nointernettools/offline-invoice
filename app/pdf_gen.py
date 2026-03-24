"""
PDF generation entry point.
All templates use WeasyPrint HTML rendering.
"""
from pathlib import Path
from app.invoice import Invoice
from app.storage import load_profile

WEASY_TEMPLATES = {
    "Classic":      "classic",
    "Modern":       "modern",
    "Consultant":   "consultant",
    "Minimalist":   "minimalist",
    "Professional": "professional",
}


def generate(inv: Invoice, template: str, output_dir: Path,
             filename: str | None = None) -> str:
    from app.weasy_gen import generate_weasy
    profile = load_profile() or {}
    accent  = profile.get("accent_color", None)
    return generate_weasy(inv, WEASY_TEMPLATES.get(template, "classic"),
                          output_dir, accent=accent, filename=filename)