"""
Offline Invoice — Gumroad license validation.

Flow:
  1. On startup, load_license() reads the locally stored token.
  2. If no token → trial mode (5 invoice cap).
  3. If token present → validate signature locally (instant, no network).
  4. Every 30 days, re-verify against Gumroad API in a background thread.
  5. On activation, call activate(key) which hits the Gumroad API,
     stores a signed local token, and returns the result.

Machine fingerprint:
  A SHA-256 hash of the machine's UUID (Windows) or MAC address.
  Stored in the token so a key can't simply be copied to another machine
  without triggering a re-activation (Gumroad's uses count handles this).

Data stored in ~/.quickinvoice/license.json:
  {
    "key":         str,   # the raw Gumroad license key
    "email":       str,   # purchaser email from Gumroad
    "activated_at": str,  # ISO date of first activation
    "verified_at":  str,  # ISO date of last successful API check
    "machine_id":   str,  # fingerprint hash
    "signature":    str,  # HMAC so the file can't be trivially edited
  }
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import platform
import sys
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

GUMROAD_PRODUCT_ID  = "REPLACE_WITH_YOUR_GUMROAD_PRODUCT_ID"
GUMROAD_API_URL     = "https://api.gumroad.com/v2/licenses/verify"
TRIAL_INVOICE_LIMIT = 5
RECHECK_DAYS        = 30

DATA_DIR     = Path.home() / ".quickinvoice"
LICENSE_FILE = DATA_DIR / "license.json"

_SIGN_SECRET = "qi-local-sign-v1-CHANGE_BEFORE_SHIPPING"


# ── Machine fingerprint ───────────────────────────────────────────────────────

def _machine_id() -> str:
    """
    Return a stable per-machine identifier (SHA-256 hex).

    Windows: tries the registry first (works on Win10 and Win11,
             no subprocess/wmic needed), then falls back to MAC address.
    Other:   MAC address via uuid.getnode().
    Final fallback: hash of username + hostname.
    """
    raw = ""
    try:
        if platform.system() == "Windows":
            # Registry key — available on every Windows version including 11
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            raw, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
        else:
            import uuid as _uuid
            raw = str(_uuid.getnode())
    except Exception:
        pass

    if not raw:
        # Final fallback — less stable but never crashes
        try:
            import uuid as _uuid
            raw = str(_uuid.getnode())
        except Exception:
            pass

    if not raw:
        raw = f"{os.getlogin()}@{platform.node()}"

    return hashlib.sha256(raw.encode()).hexdigest()


# ── Local token signature ─────────────────────────────────────────────────────

def _sign(payload: dict) -> str:
    """HMAC-SHA256 signature of the JSON payload (keys sorted)."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(                          # fix: hmac.new is correct
        _SIGN_SECRET.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()


def _verify_signature(token: dict) -> bool:
    sig = token.pop("signature", None)
    expected = _sign(token)
    token["signature"] = sig   # restore
    return sig == expected


# ── Token I/O ─────────────────────────────────────────────────────────────────

def _save_token(key: str, email: str, activated_at: str,
                verified_at: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "key":          key,
        "email":        email,
        "activated_at": activated_at,
        "verified_at":  verified_at,
        "machine_id":   _machine_id(),
    }
    payload["signature"] = _sign(payload)
    tmp = LICENSE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, LICENSE_FILE)


def _load_token() -> dict | None:
    if not LICENSE_FILE.exists():
        return None
    try:
        token = json.loads(LICENSE_FILE.read_text(encoding="utf-8"))
        if not _verify_signature(token):
            return None
        if token.get("machine_id") != _machine_id():
            return None
        return token
    except Exception:
        return None


# ── Gumroad API call ──────────────────────────────────────────────────────────

def _gumroad_verify(key: str, increment: bool = False) -> dict:
    params = urllib.parse.urlencode({
        "product_id":           GUMROAD_PRODUCT_ID,
        "license_key":          key.strip().upper(),
        "increment_uses_count": "true" if increment else "false",
    }).encode()

    req = urllib.request.Request(
        GUMROAD_API_URL,
        data=params,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"Network error contacting Gumroad: {e}") from e


# ── Public API ────────────────────────────────────────────────────────────────

class LicenseStatus:
    def __init__(self, *, licensed: bool, trial: bool, email: str = "",
                 message: str = "", key: str = ""):
        self.licensed = licensed
        self.trial    = trial
        self.email    = email
        self.message  = message
        self.key      = key

    @property
    def can_generate(self) -> bool:
        return self.licensed or self.trial


def load_license() -> LicenseStatus:
    """
    Check the locally stored token. No network call — instant.
    """
    token = _load_token()
    if not token:
        return LicenseStatus(licensed=False, trial=True,
                             message="Trial mode")

    try:
        last = datetime.fromisoformat(token["verified_at"]).date()
        due  = last + timedelta(days=RECHECK_DAYS)
        if date.today() > due:
            return LicenseStatus(
                licensed=True, trial=False,
                email=token.get("email", ""),
                key=token.get("key", ""),
                message="License requires re-verification (no internet?)")
    except Exception:
        pass

    return LicenseStatus(
        licensed=True, trial=False,
        email=token.get("email", ""),
        key=token.get("key", ""),
        message=f"Licensed to {token.get('email', '')}")


def activate(key: str) -> LicenseStatus:
    """Validate a key against Gumroad and store the local token."""
    key = key.strip().upper()
    if not key:
        return LicenseStatus(licensed=False, trial=True,
                             message="Please enter a license key.")

    try:
        data = _gumroad_verify(key, increment=True)
    except RuntimeError as e:
        return LicenseStatus(licensed=False, trial=True, message=str(e))

    if not data.get("success"):
        msg = data.get("message", "Invalid license key.")
        return LicenseStatus(licensed=False, trial=True, message=msg)

    purchase = data.get("purchase", {})

    if purchase.get("refunded"):
        return LicenseStatus(licensed=False, trial=True,
                             message="This license has been refunded.")
    if purchase.get("chargebacked"):
        return LicenseStatus(licensed=False, trial=True,
                             message="This license is no longer valid.")

    email = purchase.get("email", "")
    today = date.today().isoformat()
    _save_token(key=key, email=email, activated_at=today, verified_at=today)

    return LicenseStatus(
        licensed=True, trial=False,
        email=email, key=key,
        message=f"Activated! Licensed to {email}")


def deactivate() -> None:
    """Remove the local license token."""
    try:
        LICENSE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def recheck_in_background(on_result=None) -> None:
    """
    Re-verify the stored key against Gumroad in a daemon thread.
    Calls on_result(LicenseStatus) on the main thread when done.
    """
    import threading

    token = _load_token()
    if not token:
        return

    try:
        last = datetime.fromisoformat(token["verified_at"]).date()
        if date.today() <= last + timedelta(days=RECHECK_DAYS):
            return   # not due yet
    except Exception:
        return

    def _worker():
        try:
            data = _gumroad_verify(token["key"], increment=False)
            if data.get("success"):
                purchase = data.get("purchase", {})
                if not purchase.get("refunded") and not purchase.get("chargebacked"):
                    _save_token(
                        key=token["key"],
                        email=token.get("email", ""),
                        activated_at=token.get("activated_at",
                                               date.today().isoformat()),
                        verified_at=date.today().isoformat(),
                    )
                    result = LicenseStatus(
                        licensed=True, trial=False,
                        email=token.get("email", ""),
                        key=token["key"],
                        message="License verified.")
                else:
                    deactivate()
                    result = LicenseStatus(
                        licensed=False, trial=True,
                        message="License revoked (refunded or chargebacked).")
            else:
                result = LicenseStatus(
                    licensed=True, trial=False,
                    email=token.get("email", ""),
                    key=token["key"],
                    message="Could not verify license — will retry later.")
        except RuntimeError:
            result = None

        if on_result and result:
            try:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: on_result(result))
            except Exception:
                pass

    threading.Thread(target=_worker, daemon=True).start()


def trial_invoices_remaining() -> int:
    """Return how many trial invoices the user has left (0 = cap reached)."""
    from app.storage import load_invoices
    used = len(load_invoices())
    return max(0, TRIAL_INVOICE_LIMIT - used)