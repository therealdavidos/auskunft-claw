"""CLI integration: `check` (fake IMAP, .eml files, demo fixtures) and `replies` (redaction)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import HAS_ZIP, cli, cli_json, envelope, make_eml, make_pdf

from auskunft.deadline import due_date

SENT = date(2026, 9, 28)

ANSWER = (
    "Sehr geehrter Herr Mustermann,\n\n"
    "anbei erhalten Sie die Kopie Ihrer Daten.\n"
    "Wir speichern zu Ihnen: Max Mustermann, Musterstraße 1, 12345 Musterstadt, "
    "max.mustermann@example.org.\n"
    "Kontakt: datenschutz@example-gmbh.de.\n\n"
    "Am 28.09.2026 schrieb Max Mustermann:\n"
    "> Ich bitte hiermit um Auskunft gemäß Art. 15 DSGVO\n"
    "> Bitte senden Sie mir eine Kopie Ihres Ausweises\n"
)


def open_request(ledger, slug: str, name: str, email: str, ref: str, synthetic: bool = False):
    return ledger.create(slug, name, email, ref, state="sent", sent_at=SENT, due_at=due_date(SENT),
                         synthetic=synthetic)


@pytest.fixture
def two_requests(mini_env, ledger):
    a = open_request(ledger, "example-gmbh", "Example GmbH", "datenschutz@example-gmbh.de",
                     "AK-20260928-EXAM-0a1b")
    b = open_request(ledger, "english-ltd", "English Ltd", "privacy@english.co.uk",
                     "AK-20260928-ENGL-0c2d")
    return a, b


@pytest.fixture
def mailbox(two_requests, fake_himalaya):
    a, _ = two_requests
    envs = [
        envelope("1", "datenschutz@example-gmbh.de", f"Re: Auskunftsersuchen [Ref: {a.tracking_id}]"),
        envelope("2", "support@mail.english.co.uk", "Your request"),         # domain-only match
        envelope("3", "max.mustermann@example.org", "Fwd: note to self"),     # own mail
        envelope("4", "news@unrelated.example", "Newsletter"),                # unmatched
    ]
    bodies = {"1": ANSWER,
              "2": "<p>Hello,</p><p>please upload a copy of your passport to verify.</p>"}
    atts = {"1": [("daten.csv", b"Feld;Wert\nName;Max\n"),
                  ("auskunft.pdf", make_pdf(["Verarbeitungszwecke: Vertragsabwicklung."]))]}
    return fake_himalaya(search=envs, bodies=bodies, attachments=atts)


def test_check_imap_matches_classifies_and_records(mailbox, two_requests, ledger, runner, env):
    a, b = two_requests
    hits = cli_json(runner, "check", "--json")
    by_org = {h["org"]: h for h in hits}
    assert set(by_org) == {"Example GmbH", "English Ltd"}
    assert by_org["Example GmbH"]["state"] == "answered-partial" and by_org["Example GmbH"]["needs_human"]
    # the quoted "Kopie Ihres Ausweises" from our own letter must not flip it to id-requested
    assert by_org["English Ltd"]["state"] == "id-requested" and by_org["English Ltd"]["ref"] == b.tracking_id

    assert ledger.get(a.id).state == "answered-partial"
    assert ledger.get(b.id).state == "id-requested"
    [reply] = [e for e in ledger.events(a.id) if e["kind"] == "reply:received"]
    p = reply["payload"]
    assert p["attachments"] == ["auskunft.pdf", "daten.csv"] and p["source"] == "imap"
    assert "copy" in p["analysis"]["found"] and "c_recipients" in p["analysis"]["missing"]
    saved = Path(p["saved"])
    assert saved == env / "data" / "replies" / a.tracking_id / "1.txt"
    text = saved.read_text(encoding="utf-8")
    assert "--- daten.csv ---\nFeld | Wert" in text and "Vertragsabwicklung" in text
    assert (saved.parent / "attachments" / "auskunft.pdf").is_file()
    assert not any((env / "data" / "tmp").iterdir())  # downloads are moved, not left behind


def test_check_skips_seen_messages_and_uses_since(mailbox, runner):
    cli(runner, "check", "--since", "2026-09-01")
    search = [c for c in mailbox.calls if "search" in c]
    assert "2026-09-01" in search[0] and "INBOX" in search[0]
    out = cli(runner, "check")
    assert "no new replies to open requests" in out
    assert "after" in search[0] and "2026-09-27" in [c for c in mailbox.calls if "search" in c][1]


def test_check_text_output_lists_hits_and_unmatched(mailbox, runner):
    out = cli(runner, "check")
    assert "#1 Example GmbH: answered-partial needs you" in out and "rule: anbei" in out
    assert "#2 English Ltd: id-requested needs you" in out
    assert "1 other new mails not related to open requests" in out


def test_check_text_output_shows_completeness_for_a_repeat_partial_answer(mailbox, two_requests,
                                                                          ledger, runner):
    ledger.transition(two_requests[0].id, "answered-partial")  # no state advance → reply is last event
    out = cli(runner, "check")
    assert "completeness 0.2 (heuristic): missing Datenkategorien, Empfänger" in out


@pytest.mark.xfail(strict=True, reason="BUG: check prints the analysis from led.events()[-1], which is "
                   "the state:* transition logged after reply:received, so it never shows")
def test_check_text_output_shows_completeness_for_a_first_partial_answer(mailbox, runner):
    assert "completeness" in cli(runner, "check")


def test_check_dry_run_records_nothing(mailbox, two_requests, ledger, runner, env):
    out = cli(runner, "check", "--dry-run")
    assert "dry run: nothing recorded" in out and "answered-partial" in out
    for r in two_requests:
        assert ledger.get(r.id).state == "sent"
        assert [e["kind"] for e in ledger.events(r.id)] == ["created"]
    assert not (env / "data" / "replies").exists()


def test_check_without_real_open_requests_does_not_touch_imap(mini_env, ledger, runner, fake_himalaya):
    fake = fake_himalaya()
    open_request(ledger, "example-gmbh", "Example GmbH", "datenschutz@example-gmbh.de", "AK-S", True)
    assert "no new replies" in cli(runner, "check")
    assert fake.calls == []


def test_check_imap_failure_is_not_swallowed(two_requests, runner, fake_himalaya):
    from auskunft.cli import app

    fake_himalaya(fail_search=True)
    res = runner.invoke(app, ["check"])
    assert res.exit_code != 0 and "cannot connect to imap" in str(res.exception)


def test_check_from_file_uses_mail_date_for_events(two_requests, ledger, runner, env):
    a, _ = two_requests
    eml = make_eml(env / "nodata.eml", frm=("Example GmbH", "datenschutz@example-gmbh.de"),
                   subject=f"Re: [Ref: {a.tracking_id}]",
                   body="Zu Ihrer Person liegen uns keine personenbezogenen Daten vor.")
    [hit] = cli_json(runner, "check", "--from-file", str(eml), "--json")
    assert hit["state"] == "no-data" and hit["needs_human"] is False
    ev = next(e for e in ledger.events(a.id) if e["kind"] == "state:no-data")
    assert ev["ts"].startswith("2026-10-02T10:00:00")


@pytest.mark.skipif(not HAS_ZIP, reason="zip CLI needed for the encrypted demo archive")
def test_check_from_dir_demo_fixtures(demo_env, runner, ledger):
    cli(runner, "demo", "seed", "--reveal")
    written = cli(runner, "demo", "fixtures", "--out", "fx")
    assert written.count("wrote fx/") == 9
    hits = cli_json(runner, "check", "--from-dir", "fx", "--zip-password", "DB-2026", "--json")
    states = {h["org"].split()[0].lower(): h["state"] for h in hits}
    assert states["schufa"] == "id-requested" and states["google"] == "portal-redirect"
    assert "answered-full" in states.values() and "answered-partial" in states.values()
    assert {"extended", "no-data", "refused", "acknowledged"} <= set(states.values())
    db = next(r for r in ledger.all() if r.slug == "deutsche-bahn")
    reply = next(e for e in ledger.events(db.id) if e["kind"] == "reply:received")["payload"]
    assert reply["attachments"] == ["export.zip/auskunft.txt", "export.zip/buchungen.csv"]
    assert "c_recipients" in reply["analysis"]["found"]


# ---- replies --------------------------------------------------------------------------------
def test_replies_redacted_by_default(mailbox, runner):
    cli(runner, "check")
    [first, second] = cli_json(runner, "replies", "--json")
    ex = first["excerpt"]
    assert first["org"] == "Example GmbH" and first["classified"] == "answered-partial"
    assert "Mustermann" not in ex and "Max" not in ex and "[NAME]" in ex
    assert "Musterstraße" not in ex and "max.mustermann@example.org" not in ex
    assert "datenschutz@example-gmbh.de" in ex          # the company's privacy address is kept
    assert "Ausweises" not in ex                        # quoted own letter is stripped
    assert second["org"] == "English Ltd" and "passport" in second["excerpt"]


def test_replies_raw_shows_personal_data(mailbox, runner):
    cli(runner, "check")
    out = cli(runner, "replies", "example-gmbh", "--raw", "--chars", "400")
    assert "Max Mustermann, Musterstraße 1, 12345 Musterstadt" in out
    assert "max.mustermann@example.org" in out
    assert "attachments: auskunft.pdf, daten.csv" in out and "answered-partial" in out


def test_replies_selection_by_id_slug_name(mailbox, runner):
    cli(runner, "check")
    assert [o["org"] for o in cli_json(runner, "replies", "2", "--json")] == ["English Ltd"]
    assert [o["slug"] for o in cli_json(runner, "replies", "english-ltd", "--json")] == ["english-ltd"]
    assert [o["request_id"] for o in cli_json(runner, "replies", "  EXAMPLE ", "--json")] == [1]
    assert "no request matches 'ghost'" in cli(runner, "replies", "ghost", expect=1)


def test_replies_none_yet(two_requests, runner):
    assert "no replies received" in cli(runner, "replies")
    assert "no replies received for 'english-ltd'" in cli(runner, "replies", "english-ltd")

