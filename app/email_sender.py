"""
app/email_sender.py

Two strategies for sending an invoice PDF by email:

1. mailto:  — opens the user's default email client with To, Subject and
               Body pre-filled. The PDF must be attached manually by the user
               (browser/OS security prevents auto-attaching files via mailto).
               Works with zero configuration.

2. SMTP     — sends the email directly from the app with the PDF attached.
               Requires the user to configure SMTP settings in their profile.
               Supports TLS (port 587) and SSL (port 465).
"""
import logging
import os
import smtplib
import sys
import urllib.parse
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

log = logging.getLogger(__name__)


# ── mailto: strategy ──────────────────────────────────────────────────────────

def open_mailto(
    to: str,
    subject: str,
    body: str,
) -> bool:
    """
    Open the user's default email client with To/Subject/Body pre-filled.
    Returns True if the system call succeeded.

    Note: mailto: cannot attach files — the user must attach the PDF manually.
    The dialog shown before calling this function should tell them where it is.
    """
    params = urllib.parse.urlencode(
        {"subject": subject, "body": body},
        quote_via=urllib.parse.quote,
    )
    url = f"mailto:{urllib.parse.quote(to)}?{params}"

    try:
        if sys.platform == "win32":
            os.startfile(url)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", url], check=True)
        else:
            import subprocess
            subprocess.run(["xdg-open", url], check=True)
        log.info("mailto: opened for %s", to)
        return True
    except Exception as exc:
        log.error("mailto: failed: %s", exc)
        return False


# ── SMTP strategy ─────────────────────────────────────────────────────────────

def send_smtp(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    pdf_path: str | None = None,
    use_ssl: bool = False,
) -> tuple[bool, str]:
    """
    Send an email directly via SMTP with optional PDF attachment.

    Returns (success: bool, message: str).
    """
    msg = MIMEMultipart()
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        filename = Path(pdf_path).name
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
        log.info("SMTP: attaching %s", filename)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, [to_addr], msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, [to_addr], msg.as_string())

        log.info("SMTP: sent to %s via %s:%d", to_addr, smtp_host, smtp_port)
        return True, "Email sent successfully."

    except smtplib.SMTPAuthenticationError:
        msg = "Authentication failed — check your SMTP username and password."
        log.error("SMTP auth error for %s", smtp_user)
        return False, msg
    except smtplib.SMTPConnectError as exc:
        msg = f"Could not connect to {smtp_host}:{smtp_port}.\n{exc}"
        log.error("SMTP connect error: %s", exc)
        return False, msg
    except smtplib.SMTPRecipientsRefused:
        msg = f"Recipient refused: {to_addr}"
        log.error("SMTP recipient refused: %s", to_addr)
        return False, msg
    except smtplib.SMTPException as exc:
        log.error("SMTP error: %s", exc)
        return False, str(exc)
    except OSError as exc:
        log.error("SMTP OS error: %s", exc)
        return False, str(exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def build_subject(inv: dict) -> str:
    """Build a sensible default email subject from an invoice record."""
    num    = inv.get("number",     "")
    client = inv.get("client",     "")
    sym    = {"USD": "$", "EUR": "€", "GBP": "£",
              "CAD": "$", "AUD": "$"}.get(inv.get("currency", "USD"), "$")
    total  = inv.get("total", "")
    try:
        total_fmt = f"{sym}{float(total):,.2f}"
    except (ValueError, TypeError):
        total_fmt = str(total)

    parts = [p for p in [f"Invoice {num}" if num else "Invoice",
                          client, total_fmt] if p]
    return " — ".join(parts)


def build_body(inv: dict, business_name: str = "") -> str:
    """Build a polite default email body from an invoice record."""
    client  = inv.get("client",     "there")
    num     = inv.get("number",     "")
    due     = inv.get("due_date",   "")
    sym     = {"USD": "$", "EUR": "€", "GBP": "£",
               "CAD": "$", "AUD": "$"}.get(inv.get("currency", "USD"), "$")
    total   = inv.get("total", "")
    try:
        total_fmt = f"{sym}{float(total):,.2f}"
    except (ValueError, TypeError):
        total_fmt = str(total)

    terms = inv.get("payment_terms", "")
    notes = inv.get("notes", "")

    lines = [
        f"Hi {client},",
        "",
        f"Please find attached invoice {num} for {total_fmt}.",
    ]
    if due:
        lines.append(f"Payment is due by {due}.")
    if terms:
        lines.append(f"Payment terms: {terms}")
    if notes:
        lines += ["", notes]
    lines += [
        "",
        "Please don't hesitate to reach out if you have any questions.",
        "",
        f"Best regards,",
        business_name or "Your Business",
    ]
    return "\n".join(lines)