from datetime import date
from pathlib import Path

import pytest

from auskunft import mailer
from auskunft.config import Settings
from auskunft.render import Letter

LETTER = Letter(tracking_id="AK-1", to_email="dpo@example.org", to_name="Example GmbH",
                subject="Auskunft [Ref: AK-1]", body="Hallo\n", sent_date=date(2026, 9, 25),
                company_slug="example")
SETTINGS = Settings(from_name="Max", from_email="max@example.org", smtp_host="smtp.example.org",
                    smtp_port=465, smtp_user="max@example.org", smtp_password="x",
                    imap_host="", imap_port=993, postal_address="A", birthdate="",
                    data_dir=Path("data"), vendor_dir=Path("vendor/datenanfragen"))


def test_refuses_without_approval():
    with pytest.raises(PermissionError):
        mailer.send(LETTER, SETTINGS, approved=False)


def test_message_headers():
    msg = mailer.build_message(LETTER, SETTINGS)
    assert msg["To"] == "Example GmbH <dpo@example.org>"
    assert msg["X-Auskunft-Ref"] == "AK-1"
    assert "AK-1" in msg["Subject"]
    assert msg.get_content().startswith("Hallo")


def test_send_uses_smtp_ssl(monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, u, p):
            calls["login"] = u

        def send_message(self, msg):
            calls["sent"] = msg["Subject"]

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    mid = mailer.send(LETTER, SETTINGS, approved=True)
    assert calls == {"host": ("smtp.example.org", 465), "login": "max@example.org",
                     "sent": "Auskunft [Ref: AK-1]"}
    assert mid.startswith("<")
