"""Outgoing mail. Nothing leaves this function without `approved=True`, which the CLI only sets
after a human typed `send`. Plain SMTP with an app password; no OAuth by design (see docs/03c)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from auskunft.config import Settings
from auskunft.render import Letter


def build_message(letter: Letter, settings: Settings) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.from_name, settings.from_email))
    msg["To"] = formataddr((letter.to_name, letter.to_email))
    msg["Subject"] = letter.subject
    msg["Message-ID"] = make_msgid(domain=settings.from_email.split("@", 1)[-1] or None)
    msg["X-Auskunft-Ref"] = letter.tracking_id
    msg.set_content(letter.body, charset="utf-8")
    return msg


def send(letter: Letter, settings: Settings, approved: bool) -> str:
    """Send the letter. Returns the Message-ID. Raises if not approved or SMTP is not configured."""
    if not approved:
        raise PermissionError("refusing to send: not approved by a human")
    for k in ("smtp_host", "smtp_user", "smtp_password", "from_email"):
        if not getattr(settings, k):
            raise RuntimeError(f"SMTP not configured: {k} missing in .env")
    msg = build_message(letter, settings)
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            s.starttls()
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    return str(msg["Message-ID"])
