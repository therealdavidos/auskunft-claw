from datetime import date
from pathlib import Path

from auskunft.data import DataStore
from auskunft.intake import _match, parse_eml
from auskunft.ledger import Ledger

STORE = DataStore(Path("vendor/datenanfragen"))


def _led(tmp_path):
    led = Ledger(tmp_path / "l.db")
    led.create("flixbus", "Flix S.E.", "data.protection@flixbus.com", "AK-20260926-FLIX-ab3a", state="sent",
               sent_at=date(2026, 9, 27), due_at=date(2026, 10, 27))
    led.create("schufa", "SCHUFA Holding AG", "datenschutz@schufa.de", "AK-20260926-SCHU-18e8", state="sent",
               sent_at=date(2026, 9, 27), due_at=date(2026, 10, 27))
    return led


def test_match_by_reference_in_subject(tmp_path):
    led = _led(tmp_path)
    env = {"subject": "AW: Auskunftsersuchen [Ref: AK-20260926-SCHU-18e8]", "from": [{"email": "noreply@ticket.example"}]}
    assert _match(env, led.all(), STORE).slug == "schufa"


def test_match_by_sender_domain_without_reference(tmp_path):
    led = _led(tmp_path)
    env = {"subject": "Your case 53352469", "from": [{"email": "data.protection@flixbus.com"}]}
    assert _match(env, led.all(), STORE).slug == "flixbus"
    env = {"subject": "Newsletter", "from": [{"email": "news@unrelated.example"}]}
    assert _match(env, led.all(), STORE) is None


def test_parse_eml_with_attachment():
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"] = "DPO <dpo@example.org>"
    m["To"] = "max@example.org"
    m["Subject"] = "Re: [Ref: AK-1]"
    m["Message-ID"] = "<x@example.org>"
    m.set_content("Anbei Ihre Daten.")
    m.add_attachment(b"a;b\n1;2\n", maintype="text", subtype="csv", filename="export.csv")
    env, text, atts = parse_eml(m.as_bytes())
    assert env["subject"] == "Re: [Ref: AK-1]" and env["has-attachment"] is True
    assert "Anbei" in text and atts[0][0] == "export.csv"
