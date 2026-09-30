"""CLI integration: map, purge, report, and the demo commands."""

from __future__ import annotations

import os
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest
from conftest import HAS_UV, HAS_ZIP, cli, cli_json

from auskunft.deadline import due_date

ANALYSIS = {
    "score": 0.7, "judge": "heuristic", "missing": ["g_source", "c_recipients"],
    "categories": ["Stammdaten (Max Mustermann, max.mustermann@example.org)", "Buchungsdaten"],
    "recipients": ["Adyen N.V."],
    "found": {"a_purposes": "Verarbeitungszwecke: Vertragsabwicklung", "d_retention": "10 Jahre",
              "copy": "Anbei die Kopie"},
    "reasons": {"c_recipients": "nur Kategorien"},
}


@pytest.fixture
def answered(mini_env, ledger):
    """#1 answered with an analysis + reminder letter; #2 overdue; #3 drafted (no dates)."""
    sent = date(2026, 9, 1)
    a = ledger.create("example-gmbh", "Example GmbH", "datenschutz@example-gmbh.de", "AK-20260901-EXAM-0001",
                      state="sent", sent_at=sent, due_at=due_date(sent))
    ledger.log(a.id, "reply:received", {"classified": "answered-partial", "subject": "Ihre Auskunft",
                                        "attachments": ["daten.csv"], "analysis": ANALYSIS},
               ts="2026-09-20T12:00:00")
    ledger.transition(a.id, "answered-partial", ts="2026-09-20T12:00:01")
    ledger.log(a.id, "letter:followup", {"subject": "Nachfrage zur Auskunft"}, ts="2026-09-25T10:00:00")
    ledger.create("english-ltd", "English Ltd", "privacy@english.co.uk", "AK-20260801-ENGL-0002",
                  state="sent", sent_at=date(2026, 8, 1), due_at=due_date(date(2026, 8, 1)), synthetic=True)
    ledger.create("austria-gmbh", "Austria <GmbH>", None, "AK-draft")
    return a


# ---- map ------------------------------------------------------------------------------------
def test_map_empty(mini_env, runner):
    assert "no answers analysed yet" in cli(runner, "map")
    assert cli_json(runner, "map", "--json") == []


def test_map_json_is_redacted_unless_raw(answered, runner):
    [row] = cli_json(runner, "map", "--json")
    assert (row["org"], row["ref"], row["date"], row["score"]) == (
        "Example GmbH", "AK-20260901-EXAM-0001", "2026-09-20", 0.7)
    assert row["categories"][0] == "Stammdaten ([NAME] [NAME], [EMAIL])"
    assert row["missing"] == ["g_source", "c_recipients"]
    [raw] = cli_json(runner, "map", "--json", "--raw")
    assert raw["categories"][0] == ANALYSIS["categories"][0]


def test_map_text(answered, runner):
    out = cli(runner, "map")
    assert "Example GmbH" in out and "completeness 0.7" in out
    assert "categories: Stammdaten ([NAME] [NAME], [EMAIL]); Buchungsdaten" in out
    assert "recipients: Adyen N.V." in out
    assert "Verarbeitungszwecke: Verarbeitungszwecke: Vertragsabwicklung" in out
    assert "Speicherdauer: 10 Jahre" in out
    assert "missing: Herkunft, Empfänger" in out


# ---- purge ----------------------------------------------------------------------------------
@pytest.fixture
def stored(env) -> tuple[Path, Path]:
    root = env / "data" / "replies" / "AK-1"
    (root / "attachments").mkdir(parents=True)
    old, new = root / "1.txt", root / "attachments" / "daten.csv"
    old.write_bytes(b"x" * 3000)
    new.write_bytes(b"y" * 10)
    past = time.time() - 45 * 86400
    os.utime(old, (past, past))
    return old, new


def test_purge_nothing_stored(env, runner):
    assert "nothing stored" in cli(runner, "purge")


def test_purge_dry_run_keeps_files(stored, runner):
    out = cli(runner, "purge", "--dry-run")
    assert "would delete 1 files, 2 KiB (older than 30 days)" in out
    assert all(p.exists() for p in stored)


def test_purge_older_than_and_all(stored, runner, env):
    old, new = stored
    assert "deleted 0 files" in cli(runner, "purge", "--older-than", "60")
    assert "deleted 1 files" in cli(runner, "purge")
    assert not old.exists() and new.exists()
    assert "deleted 1 files, 0 KiB (all)" in cli(runner, "purge", "--all")
    assert list((env / "data" / "replies").iterdir()) == []  # empty dirs are removed too


# ---- report ---------------------------------------------------------------------------------
def test_report_writes_html_with_clocks_timeline_and_map(answered, runner, env):
    out = cli(runner, "report", "--out", "out/r.html", "--today", "2026-10-05", "--title", "Test <Bericht>")
    assert "report written: out/r.html" in out
    page = (env / "out" / "r.html").read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "<title>Test &lt;Bericht&gt;</title>" in page
    assert "Stand 05.10.2026 · 3 Anfragen (2 echt, 1 synthetisch)" in page
    for org in ("Example GmbH", "English Ltd", "Austria &lt;GmbH&gt;"):
        assert org in page
    assert "<span class='st answered-partial'>answered-partial</span>" in page
    assert "class='days neg'>-34<" in page and "synthetisch</span>" in page
    assert "reply:received → <b>answered-partial</b>" in page and "📎 daten.csv" in page
    assert "letter:followup → Nachfrage zur Auskunft" in page
    assert "Wer weiß was über mich" in page and "width:70%" in page and "70%" in page
    assert "✓ Verarbeitungszwecke" in page and "✗ Herkunft" in page and "Adyen N.V." in page


def test_report_default_path_empty_map_and_open(mini_env, ledger, runner, monkeypatch):
    opened = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: opened.append(cmd))
    ledger.create("example-gmbh", "Example GmbH", None, "AK-1", state="sent",
                  sent_at=date.today(), due_at=due_date(date.today()))
    cli(runner, "report", "--open")
    page = Path("data/report.html").read_text(encoding="utf-8")
    assert f"Stand {date.today():%d.%m.%Y}" in page and "Noch keine Antworten ausgewertet." in page
    assert opened == [["open", "data/report.html"]]


# ---- demo -----------------------------------------------------------------------------------
def test_seed_refused_on_real_data_dir(env, runner, ledger):
    # NB: the test name must not contain "demo": the guard checks the whole data-dir path.
    assert "refusing: AUSKUNFT_DATA_DIR must contain 'demo'" in cli(runner, "demo", "seed", expect=1)
    assert ledger.all() == []


@pytest.mark.xfail(strict=True, reason="BUG: the demo guard tests `'demo' in str(data_dir)`, so a real "
                   "data dir under any path containing 'demo' (e.g. ~/demos/x/data) is accepted")
def test_seed_refused_when_only_a_parent_dir_mentions_demo(env, runner, monkeypatch):
    monkeypatch.setenv("AUSKUNFT_DATA_DIR", str(env / "demos" / "real" / "data"))
    cli(runner, "demo", "seed", expect=1)


def test_demo_seed_creates_scenario(demo_env, runner, ledger):
    out = cli(runner, "demo", "seed", "--sent-on", "2026-09-27", "--reveal")
    assert "plays id-requested" in out and "plays silent" in out
    rows = ledger.all()
    assert len(rows) == 9 and all(r.synthetic and r.state == "sent" for r in rows)
    assert {r.due_at for r in rows} == {date(2026, 10, 27)}


def test_demo_step_out_of_range(env, runner):
    assert "step must be 0..5" in cli(runner, "demo", "step", "6", expect=1)


@pytest.mark.skipif(not (HAS_UV and HAS_ZIP), reason="demo step shells out to `uv run` and `zip`")
def test_demo_steps_0_and_1_shell_out(env, runner, monkeypatch, repo_root):
    # cwd stays tmp_path (step 0 resets ./data-demo); UV_PROJECT lets `uv run auskunft` find the project
    monkeypatch.setenv("UV_PROJECT", str(repo_root))
    (env / "drafts").mkdir()
    (env / "drafts" / "x-reminder.txt").write_text("stale")
    (env / "drafts" / "keep-me.txt").write_text("user draft")
    s0 = cli_json(runner, "demo", "step", "0", "--json")
    assert s0["step"] == 0 and s0["next"] == 1 and s0["title"].startswith("Tag 0")
    assert [o["cmd"] for o in s0["outputs"]] == ["demo seed", "demo fixtures", "ls --today 2026-09-27"]
    assert "9 requests, 0 real, 9 synthetic" in s0["outputs"][-1]["out"]
    assert (env / "data-demo" / "ledger.db").is_file() and len(list((env / "fixtures" / "replies").glob("*.eml"))) == 9
    assert not (env / "drafts" / "x-reminder.txt").exists() and (env / "drafts" / "keep-me.txt").exists()
    out = cli(runner, "demo", "step", "1")
    assert "Demo step 1" in out and "$ auskunft check --from-dir fixtures/replies" in out
    assert "answered-full" in out and "next: auskunft demo step 2" in out
