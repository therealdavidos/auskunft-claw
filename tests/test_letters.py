from datetime import date
from pathlib import Path

from auskunft.data import DataStore
from auskunft.letters import (
    authority_for,
    authority_slug_for,
    is_german,
    render_admonition,
    render_complaint,
    render_followup,
)

STORE = DataStore(Path("vendor/datenanfragen"))
SENDER = ("Max Mustermann", "Musterstraße 1, 12345 Musterstadt", "max@example.org")


def test_authority_by_seat():
    assert authority_slug_for("Theresienhöhe 12\n80339 München\nDeutschland") == "debaylda"
    assert authority_slug_for("Kormoranweg 5\n65201 Wiesbaden\nDeutschland") == "dehessbdi"
    assert authority_slug_for("Alt-Moabit 1\n10555 Berlin") == "deberlbdi"
    assert authority_slug_for("Carl-Bertelsmann-Straße 161S\n33311 Gütersloh") == "denrwldi"
    assert authority_slug_for("Vana-Lõuna 15\n10134 Tallinn\nEstonia", fallback="dendslfd") == "dendslfd"


def test_authority_for_foreign_company_falls_back_to_user_land():
    assert not is_german("Vana-Lõuna 15\n10134 Tallinn\nEstonia")
    a = authority_for(STORE, "Vana-Lõuna 15\n10134 Tallinn\nEstonia", "dendslfd")
    assert "Niedersachsen" in a.name


def test_admonition_letter():
    subject, text = render_admonition(STORE, sender=SENDER, company_name="PAYBACK GmbH",
                                      company_address="Theresienhöhe 12\n80339 München",
                                      request_date=date(2026, 9, 27), tracking_id="AK-1",
                                      today=date(2026, 10, 28), days_over=1)
    assert "Erinnerung" in subject and "[Ref: AK-1]" in subject
    assert "seit 1 Tag überschritten" in text and "zwei Wochen" in text
    assert text.startswith("Max Mustermann\n")


def test_complaint_letter_addresses_authority():
    auth = STORE.authority("debaylda")
    subject, text = render_complaint(STORE, sender=SENDER, company_name="PAYBACK GmbH",
                                     company_address="Theresienhöhe 12\n80339 München",
                                     request_date=date(2026, 9, 27), reminder_date=date(2026, 10, 28),
                                     tracking_id="AK-1", today=date(2026, 11, 11), authority=auth)
    assert "Art. 77" in subject and auth.name in text
    assert "Erinnerung vom 28.10.2026" in text and "PAYBACK GmbH" in text
    assert "[optional" not in text and "{" not in text


def test_followup_names_missing_items():
    subject, text = render_followup(sender=SENDER, company_name="Flix S.E.", company_address="X",
                                    request_date=date(2026, 9, 27), answer_date=date(2026, 9, 29),
                                    tracking_id="AK-2", today=date(2026, 10, 1),
                                    missing=["c_recipients", "d_retention", "copy"])
    assert "Empfänger (Art. 15 Abs. 1 lit. c" in text and "Kopie der Daten (Art. 15 Abs. 3" in text
    assert "C-154/21" in text and "Nachfrage" in subject
