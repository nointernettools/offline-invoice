"""
WeasyPrint PDF generator.
Renders Jinja2 HTML templates → PDF.
All templates live in app/templates/
"""
import base64, os, sys
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def _get_template_dir() -> Path:
    """
    Resolve the templates folder whether running from source or a
    PyInstaller-frozen exe.

    PyInstaller unpacks data files into sys._MEIPASS at runtime.
    In development, templates sit next to this file in app/templates/.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "templates"
    return Path(__file__).parent / "templates"


def _get_font_dir() -> Path:
    """
    Resolve the fonts folder whether running from source or a
    PyInstaller-frozen exe.
    Fonts live in app/fonts/ next to app/templates/.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "fonts"
    return Path(__file__).parent / "fonts"


_TMPL_DIR = _get_template_dir()
_FONT_DIR = _get_font_dir()
_env = Environment(loader=FileSystemLoader(str(_TMPL_DIR)), autoescape=True)


def _logo_b64(logo_path: str) -> str | None:
    if not logo_path or not os.path.exists(logo_path):
        return None
    ext  = Path(logo_path).suffix.lower().lstrip(".")
    mime = {"jpg":"jpeg","jpeg":"jpeg","png":"png","gif":"gif","svg":"svg+xml"}.get(ext,"png")
    with open(logo_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/{mime};base64,{data}"


def _qr_b64(url: str) -> str | None:
    """
    Generate a QR code PNG from url and return it as a base64 data URI,
    ready to embed directly in HTML as <img src="...">.
    Returns None if the url is blank or qrcode is not installed.
    """
    if not url or not url.strip():
        return None
    try:
        import qrcode
        import io as _io
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(url.strip())
        qr.make(fit=True)
        img  = qr.make_image(fill_color="black", back_color="white")
        buf  = _io.BytesIO()
        img.save(buf, format="PNG")
        data = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/png;base64,{data}"
    except ImportError:
        return None


def generate_weasy(inv, template_name: str, output_dir: Path,
                   accent: str | None = None,
                   filename: str | None = None) -> str:
    from weasyprint import HTML
    from app.color_utils import normalise, text_on_accent, accent_light, accent_dark, DEFAULT_ACCENT

    ac       = normalise(accent) if accent else DEFAULT_ACCENT
    text_ac  = text_on_accent(ac)
    ac_light = accent_light(ac)
    ac_dark  = accent_dark(ac)

    # Convert the fonts path to a file:/// URI so WeasyPrint can resolve
    # @font-face url() references regardless of OS or frozen/source mode.
    font_dir_uri = _FONT_DIR.as_uri()  # e.g. file:///E:/…/app/fonts

    tmpl = _env.get_template(f"{template_name}.html")
    ctx  = {
        # ── Font path (used in @font-face url() inside templates) ──
        "font_dir": font_dir_uri,
        # ── Colors ──
        "accent":       ac,
        "accent_text":  text_ac,
        "accent_light": ac_light,
        "accent_dark":  ac_dark,
        # ── Business ──
        "logo_src":           _logo_b64(inv.logo_path or ""),
        "business_name":      inv.business_name,
        "business_email":     inv.business_email,
        "business_phone":     inv.business_phone,
        "business_address":   inv.business_address.replace("\n", "<br>"),
        "business_city":      getattr(inv, "business_city",  ""),
        "business_state":     getattr(inv, "business_state", ""),
        "business_zip":       getattr(inv, "business_zip",   ""),
        # ── Client ──
        "client_name":    inv.client_name,
        "client_email":   inv.client_email,
        "client_phone":   getattr(inv, "client_phone", ""),
        "client_address": inv.client_address.replace("\n", "<br>"),
        "client_city":    getattr(inv, "client_city",  ""),
        "client_state":   getattr(inv, "client_state", ""),
        "client_zip":     getattr(inv, "client_zip",   ""),
        # ── Meta ──
        "invoice_number": inv.invoice_number,
        "issue_date":     inv.issue_date,
        "due_date":       inv.due_date,
        "currency":       inv.currency,
        "currency_symbol":inv.currency_symbol,
        # ── Items / totals ──
        "items":          inv.items,
        "subtotal":       inv.subtotal,
        "tax_rate":       inv.tax_rate,
        "tax_label":      getattr(inv, "tax_label", "Tax"),
        "tax_amount":     inv.tax_amount,
        "discount":       inv.discount,
        "grand_total":    inv.grand_total,
        # ── Notes ──
        "notes": inv.notes.replace("\n", "<br>") if inv.notes else "",
        # ── Footer ──
        "payment_terms": getattr(inv, "payment_terms", ""),
        # ── Payment QR ──
        "payment_link": getattr(inv, "payment_link", ""),
        "qr_src":       _qr_b64(getattr(inv, "payment_link", "")),
    }

    html_str = tmpl.render(**ctx)

    if filename and filename.strip():
        safe = filename.strip()
        safe = safe.replace("/", "-").replace("\\", "-").replace(":", "-")
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
        out_path = output_dir / safe
    else:
        safe_num = inv.invoice_number.replace("/", "-").replace("\\", "-")
        out_path = output_dir / f"{safe_num}_{template_name}.pdf"

    HTML(string=html_str, base_url=str(_TMPL_DIR)).write_pdf(str(out_path))
    return str(out_path)