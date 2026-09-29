"""Reply intake: read new mail through himalaya, match it to open requests, classify it into a
ledger state with deterministic rules, and record it. Inbound mail is untrusted input: we never
act on its instructions, we only classify it and let a human decide."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from auskunft.config import Settings
from auskunft.data import DataStore
from auskunft.discover import registrable, to_text
from auskunft.ledger import Ledger, Request
from auskunft.mail import himalaya_cmd

REF_RE = re.compile(r"AK-\d{8}-[A-Z0-9]{4}-[0-9a-f]{4}")

# (state, patterns). First hit in this order wins. Case-insensitive, German + English.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("id-requested", (r"ausweis", r"identit[äa]t", r"legitimation", r"identifi(?:kation|cation)",
                      r"proof of identity", r"verify (?:your )?identity", r"nachweis (?:ihrer|der) identit")),
    ("extended", (r"fristverl[äa]ngerung", r"zwei weitere monate", r"verl[äa]ngern wir", r"extend(?:ed|ing)? the (?:deadline|period)",
                  r"additional (?:two|2) months")),
    ("no-data", (r"keine (?:personenbezogenen )?daten", r"nicht gespeichert", r"liegen (?:uns )?keine",
                 r"no (?:personal )?data (?:about|on|regarding)", r"do not (?:hold|process) any")),
    ("refused", (r"ablehnen", r"nicht nachkommen", r"zur[üu]ckweisen", r"unable to (?:comply|fulfil)",
                 r"cannot (?:comply|fulfil)", r"offensichtlich unbegr[üu]ndet", r"exzessiv")),
    ("answered-partial", (r"anbei", r"im anhang", r"beigef[üu]gt", r"attached", r"kopie ihrer daten",
                          r"datenauskunft erteilen wir", r"please find (?:your|the) data")),
    ("portal-redirect", (r"portal", r"kundenkonto", r"self-?service", r"onetrust", r"privacy ?center",
                         r"[üu]ber (?:das|unser) formular", r"log ?in", r"einloggen", r"anmelden und")),
    ("clarification", (r"r[üu]ckfrage", r"ben[öo]tigen wir (?:noch|folgende)", r"bitte teilen sie uns",
                       r"please (?:provide|confirm|let us know)", r"could you (?:please )?(?:provide|confirm)")),
    ("acknowledged", (r"eingegangen", r"erhalten", r"received", r"ticket", r"vorgang", r"bearbeit",
                      r"we(?:'| a)re looking into", r"automatische antwort", r"auto-?reply", r"out of office",
                      r"abwesenheit", r"thank you for (?:contacting|your (?:e-?mail|request))")),
]
RANK = {s: i for i, s in enumerate(
    ["sent", "acknowledged", "clarification", "portal-redirect", "extended", "id-requested",
     "answered-partial", "no-data", "refused", "answered-full"])}
NEEDS_HUMAN = {"id-requested", "portal-redirect", "clarification", "refused", "answered-partial"}


# Where quoted material starts: our own letter's sentences, mail-client quote headers, ticket
# system separators. Everything from the earliest marker on is dropped before classifying.
_QUOTE_MARKERS = (
    r"ich bitte hiermit um auskunft gem[äa]ß art\. 15",
    r"betreff: auskunftsersuchen nach art\. 15",
    r"zur identifikation meiner person habe ich",
    r"^\s*>",                                   # classic quoting
    r"^on .{5,80} wrote:\s*$",                  # gmail/outlook english
    r"^am .{5,80} schrieb .*:\s*$",             # german
    r"^-{5,}\s*(original message|ursprüngliche nachricht)",
    r"^von: .*\n(gesendet|sent): ",
)
_QUOTE_RE = re.compile("|".join(f"(?:{m})" for m in _QUOTE_MARKERS), re.IGNORECASE | re.MULTILINE)


def strip_quoted(text: str, own_name: str = "") -> str:
    """Keep only the company's own words: cut at the first sign of quoted or ticket-echoed text."""
    cut = len(text)
    m = _QUOTE_RE.search(text)
    if m:
        cut = min(cut, m.start())
    if own_name:
        last = own_name.split()[-1]
        # ticket systems echo "<Name>, Sep 27, 2026, 15:28 UTC" before the quoted request
        m2 = re.search(rf"^.*{re.escape(last)}.*\d{{4}}, \d{{1,2}}:\d{{2}} UTC\s*$", text,
                       re.IGNORECASE | re.MULTILINE)
        if m2:
            cut = min(cut, m2.start())
    return text[:cut]


def classify(subject: str, text: str, own_name: str = "") -> tuple[str, str]:
    """Return (state, matched_pattern). Quoted text is removed first; subject is scanned too."""
    hay = f"{subject}\n{strip_quoted(text, own_name)}".lower()
    for state, pats in RULES:
        for p in pats:
            if re.search(p, hay):
                return state, p
    return "acknowledged", "(default: any reply)"


@dataclass
class Hit:
    request: Request
    envelope: dict
    state: str
    pattern: str
    text_path: Path


def _search(settings: Settings, mailbox: str, since: date, page_size: int = 200) -> list[dict]:
    res = subprocess.run(
        himalaya_cmd(settings, "envelope", "search", "--json", "--mailbox", mailbox,
                     "--page-size", str(page_size), "after", since.isoformat(),
                     "order", "by", "date", "desc"),
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "himalaya search failed")
    return json.loads(res.stdout or "{}").get("envelopes", [])


def _read(settings: Settings, mailbox: str, msg_id: str) -> str:
    res = subprocess.run(
        himalaya_cmd(settings, "message", "read", "--mailbox", mailbox, msg_id),
        capture_output=True, text=True, check=False,
    )
    return res.stdout if res.returncode == 0 else ""


def _match(env: dict, open_reqs: list[Request], store: DataStore) -> Request | None:
    subj = env.get("subject") or ""
    m = REF_RE.search(subj)
    if m:
        for r in open_reqs:
            if r.tracking_id == m.group(0):
                return r
    senders = {registrable((f.get("email") or "@").split("@", 1)[1]) for f in env.get("from") or []}
    for r in open_reqs:
        try:
            doms = {registrable(d) for d in store.company(r.slug).domains}
        except KeyError:
            doms = set()
        if r.to_email:
            doms.add(registrable(r.to_email.split("@", 1)[1]))
        if senders & doms:
            return r
    return None


def check(settings: Settings, store: DataStore, led: Ledger, mailbox: str = "INBOX",
          since: date | None = None, dry_run: bool = False) -> tuple[list[Hit], list[dict]]:
    open_reqs = [r for r in led.all(include_closed=False) if not r.synthetic and r.sent_at]
    if not open_reqs:
        return [], []
    # himalaya's `after` is exclusive, so start one day before the earliest send
    since = since or (min(r.sent_at for r in open_reqs if r.sent_at) - timedelta(days=1))
    seen_ids = {e["payload"].get("message_id") for r in open_reqs for e in led.events(r.id)
                if e["payload"] and e["kind"].startswith("reply")}
    hits: list[Hit] = []
    unmatched: list[dict] = []
    replies_dir = settings.data_dir / "replies"
    for env in _search(settings, mailbox, since):
        mid = env.get("message-id") or env.get("id")
        if mid in seen_ids:
            continue
        if any((f.get("email") or "").lower() == settings.from_email.lower() for f in env.get("from") or []):
            continue  # our own mail
        req = _match(env, open_reqs, store)
        if req is None:
            unmatched.append(env)
            continue
        text = to_text(_read(settings, mailbox, env["id"]))
        state, pat = classify(env.get("subject") or "", text, settings.from_name)
        out = replies_dir / req.tracking_id
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{env['id']}.txt"
        if not dry_run:
            path.write_text(f"Subject: {env.get('subject')}\nFrom: {env.get('from')}\nDate: {env.get('date')}\n\n{text}",
                            encoding="utf-8")
            payload = {"message_id": mid, "imap_id": env["id"], "subject": env.get("subject"),
                       "date": env.get("date"), "classified": state, "pattern": pat,
                       "has_attachment": env.get("has-attachment"), "saved": str(path)}
            led.log(req.id, "reply:received", payload)
            if RANK.get(state, 0) > RANK.get(req.state, 0):
                led.transition(req.id, state, {"by": "intake", "message_id": mid})
        hits.append(Hit(req, env, state, pat, path))
    return hits, unmatched
