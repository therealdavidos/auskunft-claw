"""Thin bridge to the `himalaya` CLI (OpenClaw bundled skill). We build the RFC 5322 message,
himalaya does the transport. Nothing is sent unless `approved=True`."""

from __future__ import annotations

import subprocess
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


def himalaya_cmd(settings: Settings, *args: str) -> list[str]:
    cmd = ["himalaya"]
    if settings.himalaya_account:
        cmd += ["--account", settings.himalaya_account]
    return cmd + list(args)


def send(letter: Letter, settings: Settings, approved: bool) -> str:
    """Send via `himalaya message send` (stdin = raw message). Returns the Message-ID."""
    if not approved:
        raise PermissionError("refusing to send: not approved by a human")
    msg = build_message(letter, settings)
    res = subprocess.run(
        himalaya_cmd(settings, "message", "send", "--save", "Sent"),
        input=msg.as_bytes(), capture_output=True, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode(errors="replace").strip() or "himalaya failed")
    return str(msg["Message-ID"])
