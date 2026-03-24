"""Simple JSON persistence for profile and invoice history."""
import json, os, uuid, shutil
from datetime import datetime
from pathlib import Path

# ── Single data directory — AppData\Roaming\OfflineInvoice on Windows,
#    ~/.local/share/OfflineInvoice on Linux/Mac ─────────────────────────────
_APPDATA = os.environ.get("APPDATA")  # set on Windows, None elsewhere
if _APPDATA:
    DATA_DIR = Path(_APPDATA) / "OfflineInvoice"
else:
    DATA_DIR = Path.home() / ".local" / "share" / "OfflineInvoice"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Migrate old data from ~/.offlineinvoice if it exists ─────────────────────
_OLD_DIR = Path.home() / ".offlineinvoice"
if _OLD_DIR.exists() and not (DATA_DIR / ".migrated").exists():
    for _f in _OLD_DIR.iterdir():
        _dest = DATA_DIR / _f.name
        if not _dest.exists():
            shutil.copy2(str(_f), str(_dest))
    (DATA_DIR / ".migrated").touch()   # mark migration done

# ── File paths ────────────────────────────────────────────────────────────────
PROFILE_FILE  = DATA_DIR / "profile.json"
INVOICE_FILE  = DATA_DIR / "invoices.json"
CLIENT_FILE   = DATA_DIR / "clients.json"
CUSTOMER_FILE = DATA_DIR / "customers.json"
FIRSTRUN_FLAG = DATA_DIR / ".setup_done"   # exists = not first run
TEMPLATE_FILE = DATA_DIR / "invoice_templates.json"
BACKUP_DIR    = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _auto_backup():
    """
    Write a dated backup of all JSON data files to DATA_DIR/backups/.
    Keeps the 10 most recent backups and silently ignores errors.
    Called automatically on every save operation.
    """
    try:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bk    = BACKUP_DIR / stamp
        bk.mkdir(exist_ok=True)
        for src in [PROFILE_FILE, INVOICE_FILE, CLIENT_FILE,
                    CUSTOMER_FILE, TEMPLATE_FILE]:
            if src.exists():
                shutil.copy2(str(src), str(bk / src.name))
        # Keep only the 10 most recent backup folders
        backups = sorted(BACKUP_DIR.iterdir(), reverse=True)
        for old_bk in backups[10:]:
            shutil.rmtree(str(old_bk), ignore_errors=True)
    except Exception:
        pass  # never let a backup failure crash the app


def is_first_run() -> bool:
    return not FIRSTRUN_FLAG.exists()


def mark_setup_done():
    FIRSTRUN_FLAG.touch()


def get_output_dir() -> Path:
    p = load_profile() or {}
    out_str = p.get("output_dir", "").strip()
    path = Path(out_str) if out_str else Path.home() / "Documents" / "Invoices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_profile(data: dict):
    tmp = PROFILE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PROFILE_FILE)
    _auto_backup()


def load_profile() -> dict | None:
    if not PROFILE_FILE.exists():
        return None
    try:
        with open(PROFILE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_client(name: str, email: str, address: str) -> None:
    clients = load_clients()
    clients[name.strip().lower()] = {
        "name":    name.strip(),
        "email":   email.strip(),
        "address": address.strip(),
    }
    tmp = CLIENT_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(clients, f, indent=2)
    os.replace(tmp, CLIENT_FILE)


def load_clients() -> dict:
    if not CLIENT_FILE.exists():
        return {}
    try:
        with open(CLIENT_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def find_client(name: str) -> dict | None:
    return load_clients().get(name.strip().lower())


def save_invoice(inv, pdf_path: str, template: str = "") -> None:
    invoices = load_invoices()
    invoices.append({
        # ── Display fields ──
        "number":     inv.invoice_number,
        "client":     inv.client_name,
        "total":      inv.grand_total,
        "currency":   inv.currency,
        "issue_date": inv.issue_date,
        "due_date":   inv.due_date,
        "pdf_path":   str(pdf_path),
        "status":     "Sent",
        # ── Full client snapshot ──
        "client_email":   inv.client_email,
        "client_phone":   getattr(inv, "client_phone",  ""),
        "client_address": getattr(inv, "client_address",""),
        "client_city":    getattr(inv, "client_city",   ""),
        "client_state":   getattr(inv, "client_state",  ""),
        "client_zip":     getattr(inv, "client_zip",    ""),
        # ── Invoice snapshot ──
        "template":      template,
        "tax_rate":      inv.tax_rate,
        "tax_label":     getattr(inv, "tax_label",     "Tax"),
        "payment_link":  getattr(inv, "payment_link",  ""),
        "payment_terms": getattr(inv, "payment_terms", ""),
        "discount":      inv.discount,
        "notes":        inv.notes,
        "currency_key": inv.currency,   # e.g. "USD", "EUR"
        "line_items": [
            {"description": item.description,
             "qty":         item.qty,
             "unit_price":  item.unit_price}
            for item in inv.items
        ],
    })
    tmp = INVOICE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(invoices, f, indent=2)
    os.replace(tmp, INVOICE_FILE)
    _auto_backup()


def load_invoices() -> list:
    if not INVOICE_FILE.exists():
        return []
    try:
        with open(INVOICE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def invoice_number_exists(number: str) -> bool:
    """Return True if any saved invoice already uses this number."""
    number = number.strip()
    return any(
        i.get("number", "").strip() == number
        for i in load_invoices()
    )


# ── Customers ─────────────────────────────────────────────────────────────────
# Stored in customers.json as a list of dicts:
# {
#   "id":      str  (uuid4 hex, assigned on first save),
#   "name":    str,
#   "email":   str,
#   "phone":   str,
#   "address": str,
#   "city":    str,
#   "state":   str,
#   "zip":     str,
#   "notes":   str,
# }

def _load_customers_raw() -> list[dict]:
    if not CUSTOMER_FILE.exists():
        return []
    try:
        with open(CUSTOMER_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_customers_raw(customers: list[dict]) -> None:
    tmp = CUSTOMER_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(customers, f, indent=2)
    os.replace(tmp, CUSTOMER_FILE)
    _auto_backup()


def load_all_customers() -> list[dict]:
    """Return all saved customers sorted A-Z by name."""
    return sorted(_load_customers_raw(), key=lambda c: c.get("name", "").lower())


def save_customer(customer: dict) -> dict:
    """
    Insert or update a customer.

    Resolution order:
    - Has 'id'            → update that exact record in-place.
    - No 'id', name match → merge into the existing record (no duplicates).
    - No 'id', no match   → insert as new record with a generated id.

    Returns the saved customer dict with id populated.
    """
    customers = _load_customers_raw()

    if customer.get("id"):
        # Explicit edit by id — replace in-place
        customers = [
            customer if c["id"] == customer["id"] else c
            for c in customers
        ]
        _save_customers_raw(customers)
        return customer

    # Check for an existing customer with the same name (case-insensitive)
    name_lower = customer.get("name", "").strip().lower()
    existing   = next(
        (c for c in customers
         if c.get("name", "").strip().lower() == name_lower),
        None,
    )
    if existing:
        # Merge: keep existing id, overwrite other fields with new values
        # but only replace a field if the new value is non-empty
        merged = dict(existing)
        for k, v in customer.items():
            if k != "id" and str(v).strip():
                merged[k] = v
        customers = [merged if c["id"] == existing["id"] else c
                     for c in customers]
        _save_customers_raw(customers)
        return merged

    # Truly new customer
    customer = {**customer, "id": uuid.uuid4().hex}
    customers.append(customer)
    _save_customers_raw(customers)
    return customer


def delete_customer(customer_id: str) -> None:
    """Remove the customer with the given id. Silent no-op if not found."""
    _save_customers_raw(
        [c for c in _load_customers_raw() if c.get("id") != customer_id]
    )


def find_customer_by_name(name: str) -> dict | None:
    """
    Case-insensitive prefix match on name — used for Bill To autofill.
    Returns the first match or None.
    """
    name = name.strip().lower()
    if not name:
        return None
    for c in _load_customers_raw():
        if c.get("name", "").lower().startswith(name):
            return c
    return None

def next_invoice_number() -> str:
    """
    Return the next auto-incremented invoice number.

    Scans all existing invoice numbers, strips the configured prefix,
    finds the highest numeric suffix, and returns prefix + (max+1)
    zero-padded to 4 digits.

    Examples:
        prefix="INV-", existing=["INV-0001","INV-0003"] → "INV-0004"
        prefix="",      existing=["0005"]               → "0006"
        prefix="INV-",  no history                      → "INV-0001"
    """
    profile = load_profile() or {}
    prefix  = profile.get("prefix", "").strip()

    max_num = 0
    for inv in load_invoices():
        raw = inv.get("number", "")
        # Strip prefix if present
        candidate = raw[len(prefix):] if prefix and raw.startswith(prefix) else raw
        # Extract all digit characters from the remainder
        digits = "".join(c for c in candidate if c.isdigit())
        if digits:
            try:
                max_num = max(max_num, int(digits))
            except ValueError:
                pass

    return f"{prefix}{max_num + 1:04d}"


# ── Invoice Templates (recurring) ─────────────────────────────────────────────
# Stored in invoice_templates.json as a list of dicts:
# {
#   "id":          str  (uuid4 hex),
#   "name":        str  (display name, e.g. "Monthly Retainer - Acme"),
#   "client":      str,
#   "client_email":str,
#   "client_phone":str,
#   "client_address":str,
#   "client_city": str,
#   "client_state":str,
#   "client_zip":  str,
#   "template":    str  (HTML template name),
#   "currency":    str,
#   "tax_rate":    float,
#   "tax_label":   str,
#   "discount":    float,
#   "notes":       str,
#   "line_items":  list[{description, qty, unit_price}],
# }

def _load_templates_raw() -> list[dict]:
    if not TEMPLATE_FILE.exists():
        return []
    try:
        with open(TEMPLATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_templates_raw(templates: list[dict]) -> None:
    tmp = TEMPLATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(templates, f, indent=2)
    os.replace(tmp, TEMPLATE_FILE)
    _auto_backup()


def load_all_templates() -> list[dict]:
    """Return all saved invoice templates sorted A-Z by name."""
    return sorted(_load_templates_raw(),
                  key=lambda t: t.get("name", "").lower())


def save_template(tmpl: dict) -> dict:
    """
    Insert or update a template.
    No 'id'  → generates one and inserts a new record.
    Has 'id' → replaces the matching record in-place (edit).
    Returns the saved template dict with id populated.
    """
    templates = _load_templates_raw()
    if not tmpl.get("id"):
        tmpl = {**tmpl, "id": uuid.uuid4().hex}
        templates.append(tmpl)
    else:
        templates = [
            tmpl if t["id"] == tmpl["id"] else t
            for t in templates
        ]
    _save_templates_raw(templates)
    return tmpl


def delete_template(template_id: str) -> None:
    """Remove the template with the given id. Silent no-op if not found."""
    _save_templates_raw(
        [t for t in _load_templates_raw() if t.get("id") != template_id]
    )


def find_template(template_id: str) -> dict | None:
    """Return the template with the given id, or None."""
    for t in _load_templates_raw():
        if t.get("id") == template_id:
            return t
    return None