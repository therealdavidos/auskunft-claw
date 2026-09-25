from datetime import date

from auskunft.data import Company, RequiredElement
from auskunft.render import Sender, fill_template, new_tracking_id, render_access_request

TEMPLATE = (
    "Hallo,\n[runs>Auch für: {runs_list}.\n]"
    "[data_portability>Bitte Art. 20.\n][has_fields>ID:\n{id_data}\n]Gruß\n"
)


def _company(runs=(), email="datenschutz@example.org"):
    return Company(
        slug="example",
        name="Example GmbH",
        address="Straße 1\n12345 Ort",
        email=email,
        fax=None,
        web="https://www.example.org",
        webform=None,
        transport="email",
        needs_id_document=False,
        required_elements=(RequiredElement("Name", "name"), RequiredElement("Adresse", "address")),
        runs=tuple(runs),
        categories=(),
        comments=(),
        quality="verified",
        custom_access_template=None,
        pgp_fingerprint=None,
        raw={},
    )


SENDER = Sender(name="Max Mustermann", email="max@example.org", postal_address="Weg 2, 10115 Berlin")


def test_fill_template_flags_and_vars():
    out = fill_template(TEMPLATE, {"runs_list": "a, b", "id_data": "Name: X"},
                        {"runs": True, "data_portability": False, "has_fields": True})
    assert "Auch für: a, b." in out
    assert "Art. 20" not in out
    assert "Name: X" in out


def test_tracking_id_format():
    tid = new_tracking_id("deutsche-bahn", date(2026, 9, 25))
    assert tid.startswith("AK-20260925-DEUT-")
    assert len(tid.split("-")[-1]) == 4


def test_render_access_request_has_head_subject_ref():
    letter = render_access_request(_company(runs=("bahn.de",)), SENDER, TEMPLATE, today=date(2026, 9, 25),
                                   tracking_id="AK-20260925-EXAM-abcd")
    assert letter.to_email == "datenschutz@example.org"
    assert "[Ref: AK-20260925-EXAM-abcd]" in letter.subject
    assert "Example GmbH" in letter.body and "25.09.2026" in letter.body
    assert "Auch für: bahn.de." in letter.body
    assert "E-Mail-Adresse: max@example.org" in letter.body
    assert letter.body.rstrip().endswith("bitte in Ihrer Antwort angeben)")


def test_render_refuses_company_without_email():
    import pytest

    with pytest.raises(ValueError):
        render_access_request(_company(email=None), SENDER, TEMPLATE)


def test_birthdate_only_when_required():
    s = Sender(name="M", email="m@x.org", postal_address="A", birthdate="01.01.1990")
    letter = render_access_request(_company(), s, TEMPLATE, today=date(2026, 9, 25))
    assert "Geburtsdatum" not in letter.body


def test_markup_stripped():
    out = fill_template("Kopie <italic>sämtlicher</italic> Daten", {}, {})
    assert out == "Kopie sämtlicher Daten\n"
