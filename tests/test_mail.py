from datetime import date
from pathlib import Path

import pytest

from auskunft import mail
from auskunft.config import Settings
from auskunft.render import Letter

LETTER = Letter(tracking_id="AK-1", to_email="dpo@example.org", to_name="Example GmbH",
                subject="Auskunft [Ref: AK-1]", body="Hallo\n", sent_date=date(2026, 9, 25),
                company_slug="example")
SETTINGS = Settings(from_name="Max", from_email="max@example.org", postal_address="A",
                    birthdate="", himalaya_account="", data_dir=Path("data"),
                    vendor_dir=Path("vendor/datenanfragen"))


def test_refuses_without_approval():
    with pytest.raises(PermissionError):
        mail.send(LETTER, SETTINGS, approved=False)


def test_message_headers():
    msg = mail.build_message(LETTER, SETTINGS)
    assert msg["To"] == "Example GmbH <dpo@example.org>"
    assert msg["X-Auskunft-Ref"] == "AK-1"
    assert msg.get_content().startswith("Hallo")


def test_send_pipes_raw_message_to_himalaya(monkeypatch):
    seen = {}

    def fake_run(cmd, input, capture_output, check):
        seen["cmd"], seen["input"] = cmd, input

        class R:
            returncode, stderr, stdout = 0, b"", b""

        return R()

    monkeypatch.setattr(mail.subprocess, "run", fake_run)
    mid = mail.send(LETTER, SETTINGS, approved=True)
    assert seen["cmd"] == ["himalaya", "message", "send", "--save", "Sent"]
    assert b"Subject: Auskunft [Ref: AK-1]" in seen["input"]
    assert mid.startswith("<")


def test_send_surfaces_himalaya_error(monkeypatch):
    def fake_run(*a, **k):
        class R:
            returncode, stderr, stdout = 1, b"cannot connect", b""

        return R()

    monkeypatch.setattr(mail.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="cannot connect"):
        mail.send(LETTER, SETTINGS, approved=True)
