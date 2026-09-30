"""Shared fixtures: isolated env + data dir per test, CLI runner, fake himalaya, mini vendor data."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "datenanfragen"
HAS_ZIP = shutil.which("zip") is not None
HAS_UV = shutil.which("uv") is not None
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def plain(s: str) -> str:
    return _ANSI.sub("", s)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    """Never talk to a model by accident: the .env may hold a key."""
    monkeypatch.setenv("AUSKUNFT_LLM_KEY", "")


@pytest.fixture
def env(tmp_path, monkeypatch) -> Path:
    """Persona + isolated data dir; cwd is tmp_path so drafts/ lands there too."""
    monkeypatch.setenv("AUSKUNFT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUSKUNFT_FROM_NAME", "Max Mustermann")
    monkeypatch.setenv("AUSKUNFT_FROM_EMAIL", "max.mustermann@example.org")
    monkeypatch.setenv("AUSKUNFT_POSTAL_ADDRESS", "Musterstraße 1, 12345 Musterstadt")
    monkeypatch.setenv("AUSKUNFT_BIRTHDATE", "")
    monkeypatch.setenv("AUSKUNFT_HIMALAYA_ACCOUNT", "")
    monkeypatch.setenv("AUSKUNFT_VENDOR_DIR", str(VENDOR))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def demo_env(env, monkeypatch) -> Path:
    """Same as env, but the data dir name contains 'demo' (required by demo seed / --simulate)."""
    monkeypatch.setenv("AUSKUNFT_DATA_DIR", str(env / "data-demo"))
    return env


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def open_ledger():
    from auskunft.config import load_settings
    from auskunft.ledger import Ledger

    return Ledger(load_settings().ledger_path)


@pytest.fixture
def ledger(env):
    """Ledger at the configured data dir. List `demo_env` before `ledger` in a test signature so
    the demo dir is configured first."""
    led = open_ledger()
    yield led
    led.close()


def cli(runner: CliRunner, *args: str, input: str | None = None, expect: int = 0) -> str:
    """Invoke the CLI; assert the exit code; return colour-free output."""
    from auskunft.cli import app

    res = runner.invoke(app, list(args), input=input)
    assert res.exit_code == expect, f"exit {res.exit_code}\n{res.output}\n{res.exception!r}"
    return plain(res.output)


def cli_json(runner: CliRunner, *args: str, expect: int = 0):
    return json.loads(cli(runner, *args, expect=expect))


# ---- mail fixtures --------------------------------------------------------------------------
def make_eml(path: Path, *, frm: tuple[str, str], subject: str, body: str,
             when: datetime | None = None, to: tuple[str, str] = ("Max Mustermann", "max.mustermann@example.org"),
             attachments: list[tuple[str, bytes, str]] | None = None, html: bool = False) -> Path:
    m = EmailMessage()
    m["From"] = f"{frm[0]} <{frm[1]}>"
    m["To"] = f"{to[0]} <{to[1]}>"
    m["Subject"] = subject
    m["Date"] = format_datetime(when or datetime(2026, 10, 2, 10, 0, tzinfo=UTC))
    m["Message-ID"] = f"<{path.stem}@{frm[1].split('@')[1]}>"
    m.set_content(body, subtype="html" if html else "plain")
    for name, data, mime in attachments or []:
        maintype, subtype = mime.split("/", 1)
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    path.write_bytes(m.as_bytes())
    return path


class _Result:
    def __init__(self, rc: int, out: str = "", err: str = "", text: bool = True):
        self.returncode = rc
        self.stdout = out if text else out.encode()
        self.stderr = err if text else err.encode()


class FakeHimalaya:
    """Stand-in for subprocess.run that answers himalaya (and openclaw) the way the real CLIs do.

    envelopes: for `envelope list` (paged); search: for `envelope search` (filtered by `from <dom>`
    when present); bodies: message id → raw body for `message read`; attachments: message id →
    [(name, bytes)] materialised by `attachment download`.
    """

    def __init__(self, envelopes=None, search=None, bodies=None, attachments=None,
                 fail_send: bool = False, fail_search: bool = False):
        self.envelopes = envelopes or []
        self.search = search or []
        self.bodies = bodies or {}
        self.attachments = attachments or {}
        self.fail_send = fail_send
        self.fail_search = fail_search
        self.calls: list[list[str]] = []
        self.sent: list[bytes] = []

    def __call__(self, cmd, *args, **kwargs):
        if not cmd or cmd[0] != "himalaya":
            return _REAL_RUN(cmd, *args, **kwargs)
        self.calls.append(list(cmd))
        text = bool(kwargs.get("text"))
        sub = cmd[3:] if cmd[1] == "--account" else cmd[1:]
        if sub[:2] == ["message", "send"]:
            self.sent.append(kwargs.get("input") or b"")
            return _Result(1 if self.fail_send else 0, "", "smtp: 550 relay denied", text=text)
        if sub[:2] == ["envelope", "list"]:
            page, size = int(sub[sub.index("--page") + 1]), int(sub[sub.index("--page-size") + 1])
            batch = self.envelopes[(page - 1) * size: page * size]
            return _Result(0, json.dumps({"envelopes": batch}), text=text)
        if sub[:2] == ["envelope", "search"]:
            if self.fail_search:
                return _Result(1, "", "cannot connect to imap", text=text)
            envs = self.search
            if "from" in sub:
                dom = sub[sub.index("from") + 1]
                envs = [e for e in envs if any(dom in (f.get("email") or "") for f in e.get("from", []))]
            return _Result(0, json.dumps({"envelopes": envs}), text=text)
        if sub[:2] == ["message", "read"]:
            return _Result(0, self.bodies.get(sub[-1], ""), text=text)
        if sub[:2] == ["attachment", "download"]:
            out = Path(sub[sub.index("--dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            for name, data in self.attachments.get(sub[sub.index("--dir") - 1], []):
                (out / name).write_bytes(data)
            return _Result(0, "", text=text)
        raise AssertionError(f"unexpected himalaya call: {cmd}")


_REAL_RUN = subprocess.run


@pytest.fixture
def fake_himalaya(monkeypatch):
    """Install a FakeHimalaya as subprocess.run (all modules share the subprocess module)."""
    def _install(**kw) -> FakeHimalaya:
        fake = FakeHimalaya(**kw)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake
    return _install


# ---- mini vendor data: deterministic records covering the fields the real data may lack ------
MINI_COMPANIES = {
    "example-gmbh": {
        "slug": "example-gmbh", "name": "Example GmbH", "email": "datenschutz@example-gmbh.de",
        "web": "https://www.example-gmbh.de", "fax": "+49 30 1234567", "webform": "https://example-gmbh.de/dsr",
        "pgp-fingerprint": "AAAA BBBB CCCC DDDD", "needs-id-document": True, "quality": "verified",
        "address": "Musterweg 3\n10115 Berlin\nDeutschland", "runs": ["example.shop", "Example Shop"],
        "comments": ["Antwortet meist per Post."], "suggested-transport-medium": "email",
        "required-elements": [{"desc": "Name", "type": "name"}, {"desc": "Anschrift", "type": "address"},
                              {"desc": "Geburtsdatum", "type": "birthdate", "optional": True}],
    },
    "letter-only": {"slug": "letter-only", "name": "Letter Only AG", "address": "Postweg 1\n80331 München",
                    "fax": "+49 89 111111"},
    "english-ltd": {"slug": "english-ltd", "name": "English Ltd", "email": "privacy@english.co.uk",
                    "web": "https://www.english.co.uk/", "address": "1 High Street\nLondon\nUnited Kingdom"},
    "austria-gmbh": {"slug": "austria-gmbh", "name": "Austria GmbH", "email": "dsb@austria.example",
                     "address": "Ring 1\n1010 Wien\nÖsterreich"},
    "german-en": {"slug": "german-en", "name": "German But English", "email": "dpo@german-en.example",
                  "address": "Weg 1\n20095 Hamburg\nDeutschland", "request-language": "en"},
    "webform-only": {"slug": "webform-only", "name": "Webform Only BV", "address": "Gracht 1\n1011 Amsterdam\nNetherlands",
                     "webform": "https://webform.example/form", "suggested-transport-medium": "webform"},
}


@pytest.fixture(scope="session")
def mini_vendor(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("vendor")
    (root / "companies").mkdir()
    for slug, rec in MINI_COMPANIES.items():
        (root / "companies" / f"{slug}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (root / "companies" / "broken.json").write_text("{not json", encoding="utf-8")
    (root / "companies" / "nokey.json").write_text('{"slug": "nokey"}', encoding="utf-8")
    shutil.copytree(VENDOR / "templates", root / "templates")
    shutil.copytree(VENDOR / "supervisory-authorities", root / "supervisory-authorities")
    (root / "company-packs").mkdir()
    (root / "company-packs" / "de.json").write_text(json.dumps(
        [{"slug": "basics", "type": "add-all", "companies": ["example-gmbh", "english-ltd"]}]), encoding="utf-8")
    return root


@pytest.fixture
def mini_env(env, mini_vendor, monkeypatch) -> Path:
    monkeypatch.setenv("AUSKUNFT_VENDOR_DIR", str(mini_vendor))
    return env


def make_pdf(lines: list[str]) -> bytes:
    """A one-page text PDF (reportlab is a dev dependency)."""
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i, line in enumerate(lines):
        c.drawString(50, 800 - 16 * i, line)
    c.save()
    return buf.getvalue()


def envelope(mid: str, frm: str, subject: str, date: str = "2026-10-02 10:00+00:00",
             name: str = "", to: str = "max.mustermann@example.org") -> dict:
    """An envelope shaped like `himalaya envelope list/search --json` output."""
    return {"id": mid, "subject": subject, "date": date, "from": [{"name": name, "email": frm}],
            "to": [{"name": "", "email": to}], "has-attachment": False}
