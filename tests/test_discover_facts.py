"""Discovery (sender domains → datenanfragen.de) and fact extraction, against a fake mailbox."""

from __future__ import annotations

import pytest
from conftest import cli, cli_json, envelope

from auskunft.config import load_settings
from auskunft.data import DataStore
from auskunft.discover import discover, facts_for, registrable, to_text

OWN = "max.mustermann@example.org"

MAILBOX = [
    envelope("1", "news@mail.example-gmbh.de", "Newsletter", "2026-09-01", name="Example News"),
    envelope("2", "rechnung@example-gmbh.de", "Rechnung", "2026-09-20", name="Example Billing"),
    envelope("3", "orders@example.shop", "Bestellung", "2026-08-01"),
    envelope("4", "friend@gmail.com", "Hi", "2026-09-25", name="Erika"),
    envelope("5", OWN, "note to self", "2026-09-26"),
    envelope("6", "info@news.english.co.uk", "Hello", "2026-07-01", name="English"),
    envelope("7", "undisclosed-recipients", "broken sender", "2026-07-02"),
    envelope("8", "hello@unknown-startup.io", "Welcome", "2026-06-01", name="Startup"),
]


@pytest.mark.parametrize(("domain", "expected"), [
    ("example.com", "example.com"), ("Mail.Example.COM.", "example.com"),
    ("a.b.english.co.uk", "english.co.uk"), ("shop.com.au", "shop.com.au"),
    ("x.shop.com.au", "shop.com.au"), ("localhost", "localhost"),
])
def test_registrable(domain, expected):
    assert registrable(domain) == expected


def test_to_text_strips_markup_scripts_and_entities():
    raw = "<style>p{}</style><script>x()</script><p>Kunden&shy;nummer:&nbsp;1</p>\n\n\n<b>Ende</b>"
    assert to_text(raw).split() == ["Kunden\xadnummer:", "1", "Ende"]


# ---- discover -------------------------------------------------------------------------------
def test_discover_pages_aggregates_and_maps(mini_env, fake_himalaya):
    fake = fake_himalaya(envelopes=MAILBOX)
    settings = load_settings()
    senders = discover(settings, DataStore(settings.vendor_dir), mailbox="INBOX", pages=5,
                       page_size=3, own_email=OWN.upper())
    pages = [c[c.index("--page") + 1] for c in fake.calls]
    assert pages == ["1", "2", "3"]  # stops after the short third page
    by_dom = {s.domain: s for s in senders}
    assert OWN.split("@")[1] not in by_dom and "undisclosed-recipients" not in by_dom
    ex = by_dom["example-gmbh.de"]
    assert (ex.count, ex.last, ex.company.slug) == (2, "2026-09-20", "example-gmbh")
    assert ex.names == {"Example News", "Example Billing"}
    assert ex.addresses == {"news@mail.example-gmbh.de", "rechnung@example-gmbh.de"}
    assert by_dom["example.shop"].company.slug == "example-gmbh"  # matched via `runs`
    assert by_dom["english.co.uk"].company.slug == "english-ltd"
    assert by_dom["gmail.com"].company is None and by_dom["unknown-startup.io"].company is None
    assert senders[0].domain == "example-gmbh.de"  # most mails first


def test_discover_matches_company_known_only_by_a_subdomain(mini_env, fake_himalaya):
    fake_himalaya(envelopes=[envelope("1", "a@shop.example", "x")])
    settings = load_settings()
    store = DataStore(settings.vendor_dir)
    store._domains = {"datenschutz.shop.example": ["letter-only"], "gmail.com": ["example-gmbh"]}
    [s] = discover(settings, store)
    assert s.company.slug == "letter-only"
    fake_himalaya(envelopes=[envelope("1", "a@gmail.com", "x")])
    assert discover(settings, store)[0].company is None  # webmail is never a company


def test_discover_stops_on_himalaya_error(mini_env, monkeypatch):
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "err"))
    settings = load_settings()
    assert discover(settings, DataStore(settings.vendor_dir)) == []


def test_cli_discover_json_known_only_and_limit(mini_env, runner, fake_himalaya):
    fake_himalaya(envelopes=MAILBOX)
    rows = cli_json(runner, "discover", "--json")
    by_dom = {r["domain"]: r for r in rows}
    assert by_dom["example-gmbh.de"] == {"domain": "example-gmbh.de", "count": 2, "last": "2026-09-20",
                                         "slug": "example-gmbh", "name": "Example GmbH"}
    assert by_dom["gmail.com"]["slug"] is None and by_dom["gmail.com"]["name"] == ["Erika"]
    known = cli_json(runner, "discover", "--json", "--known-only")
    assert {r["slug"] for r in known} == {"example-gmbh", "english-ltd"} and len(known) == 3
    assert len(cli_json(runner, "discover", "--json", "--limit", "2")) == 2


def test_cli_discover_table(mini_env, runner, fake_himalaya):
    fake_himalaya(envelopes=MAILBOX)
    out = cli(runner, "discover", "--mailbox", "Archive")
    assert "Senders in Archive" in out and "Example GmbH (example-gmbh)" in out
    assert "privacy@english.co.uk" in out
    assert "5 senders shown, 3 matched to datenanfragen.de" in out


# ---- facts ----------------------------------------------------------------------------------
FACT_MAILS = [
    envelope("10", "shop@example-gmbh.de", "Ihre Bestellung", "2026-09-10", to="Max+Shop@Example.org"),
    envelope("11", "booking@example.shop", "Buchung", "2026-09-12"),
    envelope("12", "empty@example-gmbh.de", "leer", "2026-09-01"),
    envelope("13", "other@unrelated.example", "nope", "2026-09-13"),
]
FACT_BODIES = {
    "10": "<html><body><p>Rechnung an Hauptstraße 5, 10115 Berlin</p>" + "<p>lorem ipsum</p>" * 30
          + "<p>Ihre Kundennummer: 12345678</p><p>Lieferung an Max Mustermann, "
          "Musterstraße 1, 12345 Musterstadt</p></body></html>",
    "11": "<p>Booking Number: 3094839218</p><p>Bestellnummer #A-77/2026</p>",
    "12": "",
}


@pytest.fixture
def fact_mailbox(mini_env, fake_himalaya):
    return fake_himalaya(search=FACT_MAILS, bodies=FACT_BODIES)


def test_facts_for_company_reads_its_domains(fact_mailbox):
    settings = load_settings()
    company = DataStore(settings.vendor_dir).company("example-gmbh")
    f = facts_for(settings, company, "Max Mustermann", mailbox="INBOX", max_messages=5)
    froms = sorted(c[c.index("from") + 1] for c in fact_mailbox.calls if "search" in c)
    assert froms == ["example-gmbh.de", "example.shop"]
    assert f.messages_read == 2 and f.slug == "example-gmbh"
    assert dict(f.numbers) == {"Kundennummer": {"12345678"}, "Booking Number": {"3094839218"},
                               "Bestellnummer": {"A-77/2026"}}
    assert f.account_emails == {"max+shop@example.org", OWN}
    assert any("Musterstraße 1, 12345 Musterstadt" in a for a in f.addresses)
    assert not any("Hauptstraße" in a for a in f.addresses)  # not near the user's name


def test_facts_max_messages_keeps_newest(fact_mailbox):
    settings = load_settings()
    company = DataStore(settings.vendor_dir).company("example-gmbh")
    f = facts_for(settings, company, "Max Mustermann", max_messages=1)
    assert f.messages_read == 1 and "Booking Number" in f.numbers and "Kundennummer" not in f.numbers


@pytest.mark.xfail(strict=True, reason="BUG: _NUMBER_RE needs >=4 chars before the first space, so a "
                   "grouped booking number like '309 483 9218' is not extracted")
def test_facts_grouped_booking_number(mini_env, fake_himalaya):
    fake_himalaya(search=[FACT_MAILS[1]], bodies={"11": "<p>Booking Number 309 483 9218</p>"})
    f = facts_for(load_settings(), None, "Max Mustermann", domains=("example.shop",))
    assert f.numbers.get("Booking Number") == {"309 483 9218"}


def test_cli_facts_company_and_addresses_opt_in(fact_mailbox, runner):
    out = cli(runner, "facts", "example-gmbh")
    assert "Example GmbH  read 2 mails" in out
    assert "account e-mail(s): max+shop@example.org, max.mustermann@example.org" in out
    assert "Kundennummer: 12345678" in out and "Booking Number: 3094839218" in out
    assert "address (guess)" not in out
    assert "address (guess):" in cli(runner, "facts", "example-gmbh", "--addresses")


def test_cli_facts_domain_mode_and_nothing_found(fact_mailbox, runner):
    out = cli(runner, "facts", "example.shop", "--domain", "--max", "3")
    assert out.startswith("example.shop  read 1 mails") and "Bestellnummer: A-77/2026" in out
    searches = [c for c in fact_mailbox.calls if "search" in c]
    assert searches[-1][searches[-1].index("--page-size") + 1] == "3"
    out = cli(runner, "facts", "nobody.example", "--domain")
    assert "read 0 mails" in out and "no customer numbers or addresses found" in out
