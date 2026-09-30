"""CLI integration: lookup, draft, show, send, ls, add-synthetic (mini vendor data, fake himalaya)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from email import message_from_bytes, policy
from pathlib import Path

from conftest import cli, cli_json

from auskunft.deadline import due_date


def draft_meta(slug: str) -> dict:
    return json.loads((Path("drafts") / f"{slug}.json").read_text(encoding="utf-8"))


def draft_text(slug: str) -> str:
    return (Path("drafts") / f"{slug}.txt").read_text(encoding="utf-8")


# ---- lookup ---------------------------------------------------------------------------------
def test_lookup_hit_shows_contact_table(mini_env, runner):
    out = cli(runner, "lookup", "example-gmbh")
    for expected in ("Example GmbH", "datenschutz@example-gmbh.de", "verified", "yes",
                     "Geburtsdatum (optional)", "+49 30 1234567", "https://example-gmbh.de/dsr",
                     "AAAA BBBB CCCC DDDD", "Antwortet meist per Post.", "Musterweg 3, 10115 Berlin"):
        assert expected in out, expected


def test_lookup_by_runs_domain_and_company_without_email(mini_env, runner):
    assert "Example GmbH" in cli(runner, "lookup", "example.shop")
    out = cli(runner, "lookup", "letter-only")
    assert "Letter Only AG" in out and "none" in out and "letter" in out


def test_lookup_miss_exits_1(mini_env, runner):
    assert "No company found" in cli(runner, "lookup", "zzz-no-such-org", expect=1)


def test_lookup_json(mini_env, runner):
    hits = cli_json(runner, "lookup", "www.english.co.uk", "--json")
    assert [h["slug"] for h in hits] == ["english-ltd"]
    assert hits[0]["email"] == "privacy@english.co.uk"


# ---- draft ----------------------------------------------------------------------------------
def test_draft_german_company_writes_txt_and_meta(mini_env, runner):
    out = cli(runner, "draft", "example-gmbh", "--no-show")
    assert "language: de" in out
    assert "claims to need an ID document" in out and "note: Antwortet meist per Post." in out
    meta = draft_meta("example-gmbh")
    assert meta["to_email"] == "datenschutz@example-gmbh.de" and meta["meta"]["lang"] == "de"
    assert meta["tracking_id"].startswith("AK-") and meta["tracking_id"] in meta["subject"]
    body = draft_text("example-gmbh")
    assert body.startswith("Max Mustermann\nMusterstraße 1, 12345 Musterstadt\n")
    assert "Art. 20" in body and "rechtliche Schritte" in body
    assert "example.shop, Example Shop" in body


def test_draft_language_is_picked_from_record_or_seat(mini_env, runner):
    assert "language: en" in cli(runner, "draft", "english-ltd", "--no-show")
    assert "Data access request under Art. 15 GDPR" in draft_meta("english-ltd")["subject"]
    assert "language: en" in cli(runner, "draft", "german-en", "--no-show")
    assert "language: de" in cli(runner, "draft", "austria-gmbh", "--no-show")


def test_draft_lang_override_and_invalid_lang(mini_env, runner):
    cli(runner, "draft", "english-ltd", "--lang", "DE", "--no-show")
    assert draft_meta("english-ltd")["meta"]["lang"] == "de"
    assert "--lang must be de or en" in cli(runner, "draft", "english-ltd", "--lang", "fr", expect=1)


def test_draft_polite_extra_id_and_no_portability(mini_env, runner):
    out = cli(runner, "draft", "example-gmbh", "--polite", "--no-portability",
              "--id", "Kundennummer = 123", "--id", "leer=")
    body = draft_text("example-gmbh")
    assert "rechtliche Schritte" not in body and "Art. 20" not in body
    assert "Kundennummer: 123" in body and "leer:" not in body
    assert draft_meta("example-gmbh")["meta"]["polite"] == "True"
    assert "Kundennummer: 123" in out  # --show is the default


def test_draft_unknown_slug_and_missing_sender(mini_env, runner, monkeypatch):
    assert "Unknown slug" in cli(runner, "draft", "nope", expect=1)
    monkeypatch.setenv("AUSKUNFT_FROM_NAME", "")
    assert "AUSKUNFT_FROM_NAME" in cli(runner, "draft", "example-gmbh", expect=1)
    assert not Path("drafts").exists()


def test_draft_company_without_email_fails_without_writing(mini_env, runner):
    from auskunft.cli import app

    res = runner.invoke(app, ["draft", "letter-only"])
    assert res.exit_code != 0
    assert isinstance(res.exception, ValueError) and "no email contact" in str(res.exception)
    assert not (Path("drafts") / "letter-only.txt").exists()


# ---- show -----------------------------------------------------------------------------------
def test_show_lists_single_and_missing(mini_env, runner):
    assert "no drafts" in cli(runner, "show")
    cli(runner, "draft", "example-gmbh", "--no-show")
    cli(runner, "draft", "english-ltd", "--no-show")
    listing = cli(runner, "show")
    assert "example-gmbh" in listing and "english-ltd" in listing
    assert draft_meta("english-ltd")["tracking_id"] in listing
    single = cli(runner, "show", "english-ltd")
    assert "English Ltd <privacy@english.co.uk>" in single
    assert f"Subject: {draft_meta('english-ltd')['subject']}" in single
    assert "Max Mustermann" in single
    assert "no draft for ghost" in cli(runner, "show", "ghost", expect=1)


# ---- send -----------------------------------------------------------------------------------
def test_send_dry_run_sends_and_logs_nothing(mini_env, ledger, runner, fake_himalaya):
    fake = fake_himalaya()
    cli(runner, "draft", "example-gmbh", "--no-show")
    out = cli(runner, "send", "example-gmbh", "--dry-run")
    assert "dry run: nothing sent" in out and "To:      Example GmbH <datenschutz@example-gmbh.de>" in out
    assert f"{due_date(date.today()):%d.%m.%Y}" in out
    assert fake.sent == [] and ledger.all() == []


def test_send_approved_records_row_event_and_headers(mini_env, ledger, runner, fake_himalaya):
    fake = fake_himalaya()
    cli(runner, "draft", "example-gmbh", "--no-show")
    ref = draft_meta("example-gmbh")["tracking_id"]
    out = cli(runner, "send", "example-gmbh", input="send\n")
    assert "sent #1 Example GmbH" in out and ref in out

    led = ledger
    [r] = led.all()
    assert (r.slug, r.state, r.tracking_id, r.synthetic) == ("example-gmbh", "sent", ref, False)
    assert r.sent_at == date.today() and r.due_at == due_date(date.today())
    ev = [e for e in led.events(r.id) if e["kind"] == "smtp:sent"]
    assert ev and ev[0]["payload"]["to"] == "datenschutz@example-gmbh.de"

    [raw] = fake.sent
    msg = message_from_bytes(raw, policy=policy.default)
    assert msg["X-Auskunft-Ref"] == ref
    assert msg["Message-ID"] == ev[0]["payload"]["message_id"]
    assert "datenschutz@example-gmbh.de" in msg["To"] and "max.mustermann@example.org" in msg["From"]
    assert "Musterstraße 1" in msg.get_content()


def test_send_abort_and_duplicate_refusal(mini_env, ledger, runner, fake_himalaya):
    fake = fake_himalaya()
    cli(runner, "draft", "example-gmbh", "--no-show")
    assert "aborted, nothing sent" in cli(runner, "send", "example-gmbh", input="nope\n")
    assert fake.sent == [] and ledger.all() == []
    cli(runner, "send", "example-gmbh", input="send\n")
    out = cli(runner, "send", "example-gmbh", input="send\n", expect=1)
    assert "already in the ledger" in out
    assert len(fake.sent) == 1 and len(ledger.all()) == 1


def test_send_himalaya_failure_logs_nothing(mini_env, ledger, runner, fake_himalaya):
    fake_himalaya(fail_send=True)
    cli(runner, "draft", "example-gmbh", "--no-show")
    out = cli(runner, "send", "example-gmbh", input="send\n", expect=1)
    assert "send failed" in out and "550 relay denied" in out
    assert ledger.all() == []


def test_send_without_draft(mini_env, runner):
    assert "No draft for example-gmbh" in cli(runner, "send", "example-gmbh", expect=1)


# ---- ls / add-synthetic ---------------------------------------------------------------------
def test_add_synthetic_known_and_unknown(mini_env, ledger, runner):
    out = cli(runner, "add-synthetic", "example-gmbh", "nope", "--sent-on", "2026-09-01")
    assert "unknown slug nope, skipped" in out and "added #1 Example GmbH due 01.10.2026" in out
    [r] = ledger.all()
    assert r.synthetic and r.state == "sent" and r.notes == "synthetic: nothing was sent"
    assert r.sent_at == date(2026, 9, 1) and r.tracking_id.startswith("AK-20260901-EXAM-")


def test_ls_table_days_and_closed_filter(mini_env, ledger, runner):
    assert "0 requests" in cli(runner, "ls")
    cli(runner, "add-synthetic", "example-gmbh", "--sent-on", "2026-08-01")   # due 01.09 → overdue
    cli(runner, "add-synthetic", "english-ltd", "--sent-on", "2026-09-10")    # Sat 10.10 → Mon 12.10
    cli(runner, "add-synthetic", "austria-gmbh", "--sent-on", "2026-09-28")   # due 28.10 → 23 left
    led = ledger
    led.create("german-en", "German But English", None, "AK-X", state="drafted")
    closed = led.create("webform-only", "Webform Only BV", None, "AK-Y", state="sent",
                        sent_at=date(2026, 9, 1), due_at=date(2026, 10, 1))
    led.transition(closed.id, "closed")
    out = cli(runner, "ls", "--today", "2026-10-05")
    assert "05.10.2026" in out and "4 requests, 1 real, 3 synthetic" in out
    assert "│ -34 " in out and "12.10.2026 │ 7 " in out and "│ 23 " in out and "│ -    │ AK-X" in out
    assert "Webform Only BV" not in out
    assert "Webform Only BV" in cli(runner, "ls", "--all")


def test_ls_json_rows(mini_env, runner):
    cli(runner, "add-synthetic", "example-gmbh", "--sent-on", "2026-09-01")
    [row] = cli_json(runner, "ls", "--json")
    assert row["slug"] == "example-gmbh" and row["state"] == "sent" and row["synthetic"] is True
    assert row["due_at"] == "2026-10-01" and row["extended_until"] is None
    assert date.fromisoformat(row["sent_at"]) + timedelta(days=30) == date(2026, 10, 1)
