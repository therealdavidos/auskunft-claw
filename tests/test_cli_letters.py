"""CLI integration: tick, remind/escalate/followup drafts, send-letter, notify."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest
from conftest import cli, cli_json

from auskunft.deadline import due_date


def sent_request(ledger, slug: str, name: str, sent: date, email: str | None = None, ref: str = ""):
    return ledger.create(slug, name, email or f"dpo@{slug}.example", ref or f"AK-{slug}", state="sent",
                         sent_at=sent, due_at=due_date(sent))


def draft_meta(slug: str) -> dict:
    return json.loads((Path("drafts") / f"{slug}.json").read_text(encoding="utf-8"))


def kinds(ledger, rid: int) -> list[str]:
    return [e["kind"] for e in ledger.events(rid)]


# ---- tick -----------------------------------------------------------------------------------
@pytest.fixture
def clocks(mini_env, ledger):
    """#1 overdue on 05.09., #2 due in 5 days, #3 reminded 16 days ago, #4 without a due date."""
    over = sent_request(ledger, "example-gmbh", "Example GmbH", date(2026, 8, 1))
    soon = sent_request(ledger, "english-ltd", "English Ltd", date(2026, 8, 10))
    rem = sent_request(ledger, "austria-gmbh", "Austria GmbH", date(2026, 7, 1))
    ledger.log(rem.id, "letter:reminder", {"subject": "Erinnerung"}, ts="2026-08-20T10:00:00")
    ledger.transition(rem.id, "reminded", ts="2026-08-20T10:00:01")
    ledger.create("german-en", "German But English", None, "AK-draft")
    return over, soon, rem


def test_tick_marks_overdue_and_lists_due_soon(clocks, ledger, runner):
    over, soon, rem = clocks
    out = cli(runner, "tick", "--today", "2026-09-05")
    assert "time travel: today = 05.09.2026" in out
    assert "overdue #1 Example GmbH (due 01.09.2026) → draft a reminder with `auskunft remind 1`" in out
    assert "5 days left #2 English Ltd (due 10.09.2026)" in out
    assert "reminded 16 days ago, still nothing #3 Austria GmbH → draft the complaint" in out
    assert ledger.get(over.id).state == "overdue"
    [ev] = [e for e in ledger.events(over.id) if e["kind"] == "state:overdue"]
    assert ev["ts"] == "2026-09-05T09:00:00"
    assert ev["payload"] == {"by": "tick", "days_over": 4}
    assert ledger.get(soon.id).state == "sent" and ledger.get(rem.id).state == "reminded"


def tick_json(runner, *args: str) -> dict:
    """`tick --today X --json` prints the time-travel banner before the JSON (see xfail below)."""
    out = cli(runner, "tick", *args, "--json")
    return json.loads(out[out.index("{"):])


@pytest.mark.xfail(strict=True, reason="BUG: tick --today --json prints the 'time travel' banner "
                   "before the JSON document, so the output is not valid JSON")
def test_tick_today_json_is_pure_json(clocks, runner):
    cli_json(runner, "tick", "--today", "2026-09-05", "--json")


def test_tick_json_and_idempotence(clocks, runner):
    rep = tick_json(runner, "--today", "2026-09-05")
    assert set(rep) == {"date", "overdue", "due_soon", "escalate", "requests"}
    assert (rep["date"], rep["overdue"], rep["due_soon"], rep["escalate"]) == ("2026-09-05", [1], [2], [3])
    assert {r["id"]: r["days_left"] for r in rep["requests"]} == {1: -4, 2: 5, 3: -33}
    again = tick_json(runner, "--today", "2026-09-05")
    assert again["overdue"] == [1]  # still reported, but not transitioned twice


def test_tick_quiet_day_and_warn_days(mini_env, ledger, runner):
    sent_request(ledger, "example-gmbh", "Example GmbH", date(2026, 9, 1))
    assert "no deadlines within 7 days, nothing overdue" in cli(runner, "tick", "--today", "2026-09-02")
    assert "29 days left" in cli(runner, "tick", "--today", "2026-09-02", "--warn-days", "30")


def test_tick_retention_hint_for_old_reply_files(mini_env, runner):
    root = Path("data") / "replies" / "AK-1"
    root.mkdir(parents=True)
    old, new = root / "old.txt", root / "new.txt"
    old.write_text("x"), new.write_text("y")
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    assert "retention: 1 stored reply files older than 30 days → `auskunft purge`" in cli(runner, "tick")


# ---- remind / escalate / followup + send-letter ---------------------------------------------
def test_remind_show_and_simulated_send(demo_env, mini_env, ledger, runner):
    r = sent_request(ledger, "letter-only", "Letter Only AG", date(2026, 9, 1), ref="AK-20260901-LETT-aaaa")
    out = cli(runner, "remind", str(r.id), "--today", "2026-10-05")
    assert "reminder drafted: drafts/letter-only-reminder.txt" in out
    meta = draft_meta("letter-only-reminder")
    assert (meta["kind"], meta["request_id"], meta["to_email"]) == ("reminder", r.id, r.to_email)
    text = Path("drafts/letter-only-reminder.txt").read_text(encoding="utf-8")
    assert "seit 4 Tagen überschritten" in text and "Postweg 1\n80331 München" in text
    assert "Erinnerung" in cli(runner, "show", "letter-only-reminder")

    out = cli(runner, "send-letter", "letter-only-reminder", "--simulate", "--today", "2026-10-05")
    assert "simulated: nothing was mailed" in out and "state → reminded" in out
    assert ledger.get(r.id).state == "reminded"
    ev = next(e for e in ledger.events(r.id) if e["kind"] == "letter:reminder")
    assert ev["ts"] == "2026-10-05T10:00:00" and ev["payload"]["simulated"] is True
    assert ev["payload"]["message_id"] == "<simulated>"
    assert not Path("drafts/letter-only-reminder.txt").exists()


def test_remind_not_yet_overdue_and_unknown_company(mini_env, ledger, runner):
    r = sent_request(ledger, "example-gmbh", "Example GmbH", date(2026, 9, 1))
    assert "is not overdue" in cli(runner, "remind", str(r.id), "--today", "2026-09-10")
    assert "seit 1 Tag überschritten" in Path("drafts/example-gmbh-reminder.txt").read_text("utf-8")
    ghost = sent_request(ledger, "ghost", "Ghost Corp", date(2026, 8, 1))
    assert "→ Ghost Corp <dpo@ghost.example>" in cli(runner, "remind", str(ghost.id), "--today", "2026-09-10")


def test_escalate_picks_authority_by_seat_and_cites_reminder(demo_env, mini_env, ledger, runner):
    r = sent_request(ledger, "letter-only", "Letter Only AG", date(2026, 9, 1))
    ledger.log(r.id, "letter:reminder", {}, ts="2026-10-05T10:00:00")
    out = cli(runner, "escalate", str(r.id), "--today", "2026-10-20")
    assert "competent authority: Bayerisches Landesamt für Datenschutzaufsicht" in out
    meta = draft_meta("letter-only-complaint")
    assert meta["to_email"] == "poststelle@lda.bayern.de"
    assert meta["subject"] == f"Beschwerde nach Art. 77 DSGVO gegen Letter Only AG [Ref: {r.tracking_id}]"
    text = Path("drafts/letter-only-complaint.txt").read_text(encoding="utf-8")
    assert "Erinnerung vom 05.10.2026" in text and "per E-Mail unter max.mustermann@example.org" in text
    cli(runner, "send-letter", "letter-only-complaint", "--simulate")
    assert ledger.get(r.id).state == "complaint-filed"


def test_escalate_foreign_seat_uses_own_land(mini_env, ledger, runner):
    r = sent_request(ledger, "english-ltd", "English Ltd", date(2026, 9, 1))
    assert "Niedersachsen" in cli(runner, "escalate", str(r.id))
    assert "Berliner Beauftragte" in cli(runner, "escalate", str(r.id), "--my-authority", "deberlbdi")


def test_followup_lists_gaps_then_simulated_send(demo_env, mini_env, ledger, runner):
    r = sent_request(ledger, "example-gmbh", "Example GmbH", date(2026, 9, 1))
    assert "no recorded gaps" in cli(runner, "followup", str(r.id), expect=1)
    ledger.log(r.id, "reply:received", {"analysis": {"missing": ["c_recipients", "copy"],
                                                      "reasons": {"c_recipients": "nur Kategorien"}}},
               ts="2026-09-20T12:00:00")
    cli(runner, "followup", str(r.id), "--today", "2026-09-25")
    text = Path("drafts/example-gmbh-followup.txt").read_text(encoding="utf-8")
    assert "Antwort vom 20.09.2026" in text
    assert "- Empfänger (Art. 15 Abs. 1 lit. c DSGVO): nur Kategorien" in text
    assert "- Kopie der Daten (Art. 15 Abs. 3 DSGVO)" in text
    cli(runner, "send-letter", "example-gmbh-followup", "--simulate", "--today", "2026-09-25")
    assert ledger.get(r.id).state == "answered-partial"


def test_send_letter_dry_run_abort_and_real_send(mini_env, ledger, runner, fake_himalaya):
    fake = fake_himalaya()
    r = sent_request(ledger, "example-gmbh", "Example GmbH", date(2026, 8, 1))
    cli(runner, "remind", str(r.id))
    assert "dry run" in cli(runner, "send-letter", "example-gmbh-reminder", "--dry-run")
    assert "aborted" in cli(runner, "send-letter", "example-gmbh-reminder", input="no\n")
    assert fake.sent == [] and "letter:reminder" not in kinds(ledger, r.id)
    assert Path("drafts/example-gmbh-reminder.txt").exists()

    out = cli(runner, "send-letter", "example-gmbh-reminder", input="send\n")
    assert "sent reminder for #1, state → reminded" in out
    [raw] = fake.sent
    assert f"X-Auskunft-Ref: {r.tracking_id}".encode() in raw
    ev = next(e for e in ledger.events(r.id) if e["kind"] == "letter:reminder")
    assert ev["payload"]["simulated"] is False and ev["payload"]["message_id"].startswith("<")


def test_send_letter_refusals(mini_env, ledger, runner):
    assert "no draft nope" in cli(runner, "send-letter", "nope", expect=1)
    r = sent_request(ledger, "example-gmbh", "Example GmbH", date(2026, 8, 1))
    cli(runner, "remind", str(r.id))
    out = cli(runner, "send-letter", "example-gmbh-reminder", "--simulate", expect=1)
    assert "--simulate only works on a demo data dir" in out
    assert ledger.get(r.id).state == "sent"


# ---- notify ---------------------------------------------------------------------------------
class FakeOpenClaw:
    def __init__(self, self_json: str = '{"id":"+4915112345678"}', send_rc: int = 0):
        self.self_json, self.send_rc, self.calls = self_json, send_rc, []

    def __call__(self, cmd, *args, **kwargs):
        assert cmd[0] == "openclaw", cmd
        self.calls.append(cmd)
        if cmd[1:3] == ["directory", "self"]:
            return subprocess.CompletedProcess(cmd, 0, self.self_json, "")
        if cmd[1:3] == ["message", "send"]:
            return subprocess.CompletedProcess(cmd, self.send_rc, "", "gateway down" if self.send_rc else "")
        raise AssertionError(cmd)


def test_notify_delivers_to_own_chat(env, runner, monkeypatch):
    fake = FakeOpenClaw()
    monkeypatch.setattr(subprocess, "run", fake)
    assert "delivered via signal" in cli(runner, "notify", "3 Anfragen überfällig", "--channel", "signal")
    send = fake.calls[-1]
    assert send[send.index("--target") + 1] == "+4915112345678"
    assert send[send.index("--channel") + 1] == "signal"
    assert send[send.index("--message") + 1] == "3 Anfragen überfällig"


def test_notify_failures(env, runner, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeOpenClaw(send_rc=1))
    assert "delivery failed: gateway down" in cli(runner, "notify", "hi", expect=1)
    monkeypatch.setattr(subprocess, "run", FakeOpenClaw(self_json="{}"))
    assert "could not determine own chat id" in cli(runner, "notify", "hi", expect=1)
