from datetime import date
from email.message import EmailMessage
from pathlib import Path

from auskunft.config import Settings
from auskunft.data import DataStore
from auskunft.intake import check_files
from auskunft.ledger import Ledger


def _eml(path: Path, ref: str, body: str, when: str) -> Path:
    m = EmailMessage()
    m["From"] = "Datenschutz <datenschutz@telekom.de>"
    m["To"] = "Max <max@example.org>"
    m["Subject"] = f"Re: Auskunft [Ref: {ref}]"
    m["Date"] = when
    m["Message-ID"] = f"<{ref}@telekom.de>"
    m.set_content(body)
    path.write_bytes(m.as_bytes())
    return path


def _setup(tmp_path):
    settings = Settings(from_name="Max Mustermann", from_email="max@example.org", postal_address="A",
                        birthdate="", himalaya_account="", data_dir=tmp_path / "data",
                        vendor_dir=Path("vendor/datenanfragen"))
    store = DataStore(settings.vendor_dir)
    led = Ledger(settings.data_dir / "ledger.db")
    r = led.create("telekom-de", "Telekom", "datenschutz@telekom.de", "AK-20260901-TELE-0001", state="sent",
                   sent_at=date(2026, 9, 1), due_at=date(2026, 10, 1))
    return settings, store, led, r


def test_timely_reasoned_extension_moves_deadline(tmp_path):
    settings, store, led, r = _setup(tmp_path)
    p = _eml(tmp_path / "a.eml", r.tracking_id,
             "Aufgrund der Komplexität nehmen wir eine Fristverlängerung um zwei Monate in Anspruch.",
             "Mon, 20 Sep 2026 10:00:00 +0000")
    check_files(settings, store, led, [p])
    r = led.get(r.id)
    assert r.state == "extended" and r.extended_until == date(2026, 12, 1)


def test_late_extension_is_rejected(tmp_path):
    settings, store, led, r = _setup(tmp_path)
    p = _eml(tmp_path / "b.eml", r.tracking_id,
             "Aufgrund der Komplexität nehmen wir eine Fristverlängerung in Anspruch.",
             "Mon, 05 Oct 2026 10:00:00 +0000")
    check_files(settings, store, led, [p])
    r = led.get(r.id)
    assert r.state == "acknowledged" and r.extended_until is None
    assert "late notice" in led.events(r.id)[-1]["payload"]["extension"]


def test_unreasoned_extension_is_rejected(tmp_path):
    settings, store, led, r = _setup(tmp_path)
    p = _eml(tmp_path / "c.eml", r.tracking_id, "Wir nehmen eine Fristverlängerung in Anspruch.",
             "Mon, 20 Sep 2026 10:00:00 +0000")
    check_files(settings, store, led, [p])
    r = led.get(r.id)
    assert r.state == "acknowledged" and r.extended_until is None
