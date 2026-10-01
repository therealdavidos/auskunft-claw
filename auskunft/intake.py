"""Reply intake: read new mail through himalaya, match it to open requests, classify it into a
ledger state with deterministic rules, and record it. Inbound mail is untrusted input: we never
act on its instructions, we only classify it and let a human decide."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from pathlib import Path

from auskunft.analysis import analyse
from auskunft.attachments import unpack
from auskunft.config import Settings
from auskunft.data import DataStore
from auskunft.deadline import extended_due_date
from auskunft.discover import registrable, to_text
from auskunft.judge import judge
from auskunft.ledger import Ledger, Request
from auskunft.mail import himalaya_cmd

REF_RE = re.compile(r"AK-\d{8}-[A-Z0-9]{4}-[0-9a-f]{4}")

# (state, patterns). First hit in this order wins. Case-insensitive, German + English.
# A legal identity check (Art. 12(6)) means a document is demanded. Questions for a customer number,
# account e-mail or date of birth are ordinary clarifications and get different advice.
_ID_DOCUMENT = re.compile(
    r"ausweis|reisepass|personalausweis|passport|id card|identity (?:document|card)|photo ?id|"
    r"government[- ]issued|lichtbild|kopie ihres|copy of your (?:id|passport)|selfie|video[- ]ident",
    re.IGNORECASE)

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("id-requested", (r"ausweis", r"reisepass", r"passport", r"\bid card", r"identity (?:document|card)",
                      r"photo ?id", r"government[- ]issued", r"lichtbild", r"video[- ]ident", r"selfie",
                      r"kopie ihres", r"copy of your (?:id|passport)")),
    ("clarification", (r"identit[äa]t", r"legitimation", r"identifi(?:kation|cation)", r"verify",
                       r"best[äa]tigen sie", r"kundennummer", r"customer (?:number|id)", r"geburtsdatum",
                       r"date of birth", r"r[üu]ckfrage", r"ben[öo]tigen wir (?:noch|folgende|weitere)",
                       r"bitte teilen sie uns", r"please (?:provide|confirm|let us know)",
                       r"could you (?:please )?(?:provide|confirm)", r"weitere (?:angaben|informationen)")),
    ("extended", (r"fristverl[äa]ngerung", r"zwei weitere monate", r"verl[äa]ngern wir", r"extend(?:ed|ing)? the (?:deadline|period)",
                  r"additional (?:two|2) months")),
    ("no-data", (r"keine (?:personenbezogenen )?daten", r"nicht gespeichert", r"liegen (?:uns )?keine",
                 r"no (?:personal )?data (?:about|on|regarding)", r"do not (?:hold|process) any")),
    ("refused", (r"ablehnen", r"nicht nachkommen", r"zur[üu]ckweisen", r"unable to (?:comply|fulfil)",
                 r"cannot (?:comply|fulfil)", r"offensichtlich unbegr[üu]ndet", r"exzessiv")),
    ("download-ready", (r"(?:daten|data)[^.\n]{0,40}(?:sind|is|are)[^.\n]{0,20}(?:verf[üu]gbar|available)",
                        r"link ist[^.\n]{0,60}zug[äa]nglich bis", r"herunterladen", r"download (?:your|the) (?:data|file|copy)",
                        r"available (?:for download|until)", r"download-?link", r"link (?:expires|is valid) ")),
    ("answered-partial", (r"anbei", r"im anhang", r"beigef[üu]gt", r"attached", r"kopie ihrer daten",
                          r"datenauskunft erteilen wir", r"please find (?:your|the) data")),
    ("portal-redirect", (r"portal", r"kundenkonto", r"self-?service", r"onetrust", r"privacy ?center",
                         r"[üu]ber (?:das|unser) formular", r"log ?in", r"einloggen", r"anmelden und")),
    ("acknowledged", (r"eingegangen", r"erhalten", r"received", r"ticket", r"vorgang", r"bearbeit",
                      r"we(?:'| a)re looking into", r"automatische antwort", r"auto-?reply", r"out of office",
                      r"abwesenheit", r"thank you for (?:contacting|your (?:e-?mail|request))")),
]
RANK = {s: i for i, s in enumerate(
    ["sent", "acknowledged", "clarification", "portal-redirect", "extended", "id-requested",
     "download-ready", "answered-partial", "no-data", "refused", "answered-full"])}
NEEDS_HUMAN = {"id-requested", "portal-redirect", "clarification", "refused", "answered-partial", "download-ready"}

_EXPIRY_RE = re.compile(
    r"(?:zug[äa]nglich|verf[üu]gbar|g[üu]ltig|available|valid|accessible|expires?)[^.\n]{0,30}?(?:bis|until|on|:)\s*:?\s*"
    r"(\d{1,2}\.?\s?(?:[A-Za-zäÄ]{3,9}\.?|\d{1,2}\.)\s?\d{4}(?:,?\s*\d{1,2}:\d{2}(?::\d{2})?)?(?:\s*\(UTC[+-]\d{2}:\d{2}\))?)",
    re.IGNORECASE)


def download_expiry(text: str) -> str | None:
    """'3 Oct 2026, 11:47:47 (UTC+02:00)' or '03.10.2026' from a download-link mail, if stated."""
    m = _EXPIRY_RE.search(text)
    return m.group(1).strip() if m else None


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


def process_reply(settings: Settings, led: Ledger, req: Request, env: dict, text: str,
                  attachments: list[tuple[str, bytes]], *, source: str, dry_run: bool = False,
                  zip_password: str | None = None) -> tuple[str, str, dict]:
    """Classify one reply (+ attachments), record it, advance the state. Returns (state, rule, payload)."""
    mid = env.get("message-id") or env.get("id")
    out = settings.data_dir / "replies" / req.tracking_id
    att_texts: list[tuple[str, str]] = []
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        for name, data in attachments:
            att_texts.extend(unpack(name, data, out / "attachments", zip_password))
    else:
        att_texts = [(n, "") for n, _ in attachments]
    state, pat = classify(env.get("subject") or "", text, settings.from_name)
    payload: dict = {"message_id": mid, "imap_id": env.get("id"), "subject": env.get("subject"),
                     "date": env.get("date"), "classified": state, "pattern": pat, "source": source,
                     "attachments": [n for n, _ in att_texts]}
    full_text = text + "\n\n" + "\n\n".join(f"--- {n} ---\n{t}" for n, t in att_texts if t)
    if state == "download-ready":
        payload["download_until"] = download_expiry(text)
    if att_texts and state in ("acknowledged", "answered-partial", "clarification", "download-ready"):
        state = "answered-partial"
    if state == "answered-partial":
        a = analyse(full_text)
        from auskunft.redact import redact
        v = judge(redact(strip_quoted(full_text, settings.from_name), own_name=settings.from_name), a)
        payload["analysis"] = {**v.as_analysis(), "recipients": a.recipients, "categories": a.categories,
                               "heuristic_missing": a.missing, "heuristic_score": a.score}
        if not v.missing:
            state = "answered-full"
    if not dry_run:
        path = out / f"{env.get('id') or 'reply'}.txt"
        path.write_text(f"Subject: {env.get('subject')}\nFrom: {env.get('from')}\nDate: {env.get('date')}\n\n{full_text}",
                        encoding="utf-8")
        payload["saved"] = str(path)
        ts = _event_ts(env.get("date")) if source.startswith("file:") else None
        led.log(req.id, "reply:received", payload, ts=ts)
        if RANK.get(state, 0) > RANK.get(req.state, 0):
            fields = {}
            note = {"by": "intake", "message_id": mid}
            if state == "extended" and req.sent_at:
                # Art. 12(3) s. 2: two further months, but only if the notice arrives within the first
                # month and gives reasons. A late or unreasoned notice does not move the deadline.
                notice = _notice_date(env.get("date")) or date.today()
                reasons = bool(re.search(r"grund|komplex|umfang|anzahl|vielzahl|because|due to|complex|"
                                         r"volume|number of requests", text, re.IGNORECASE))
                if notice <= (req.due_at or notice) and reasons:
                    fields["extended_until"] = extended_due_date(req.sent_at, 2)
                    note["extension"] = "accepted"
                else:
                    state = "acknowledged"  # keep the original clock running
                    note["extension"] = "rejected: " + ("late notice" if notice > (req.due_at or notice) else "no reasons given")
                    payload["extension_rejected"] = note["extension"]
            led.transition(req.id, state, note, ts=ts, **fields)
    return state, pat, payload


def _notice_date(date_header: str | None) -> date | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(date_header).date() if date_header else None
    except (TypeError, ValueError):
        return None


def _event_ts(date_header: str | None) -> str | None:
    """RFC 2822 date → ISO timestamp, so simulated replies carry their own date in the ledger."""
    if not date_header:
        return None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(date_header).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def parse_eml(raw: bytes) -> tuple[dict, str, list[tuple[str, bytes]]]:
    """An .eml file → (envelope dict like himalaya's, body text, attachments)."""
    msg: EmailMessage = message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    froms = [{"name": n, "email": a} for n, a in [_addr(msg.get("From", ""))]]
    env = {"id": (msg.get("Message-ID") or "").strip("<>") or "eml", "message-id": msg.get("Message-ID"),
           "subject": msg.get("Subject", ""), "from": froms, "date": msg.get("Date", ""),
           "has-attachment": False}
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        text = body.get_content()
        if body.get_content_type() == "text/html":
            text = to_text(text)
    atts: list[tuple[str, bytes]] = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment.bin"
        atts.append((name, part.get_payload(decode=True) or b""))
    env["has-attachment"] = bool(atts)
    return env, text, atts


def _addr(s: str) -> tuple[str, str]:
    from email.utils import parseaddr

    return parseaddr(s)


def check_files(settings: Settings, store: DataStore, led: Ledger, paths: list[Path],
                dry_run: bool = False, zip_password: str | None = None) -> tuple[list[Hit], list[dict]]:
    open_reqs = [r for r in led.all(include_closed=False) if r.sent_at]
    hits, unmatched = [], []
    for path in paths:
        env, text, atts = parse_eml(Path(path).read_bytes())
        req = _match(env, open_reqs, store)
        if req is None:
            unmatched.append(env)
            continue
        state, pat, payload = process_reply(settings, led, req, env, text, atts,
                                            source=f"file:{path}", dry_run=dry_run,
                                            zip_password=zip_password)
        hits.append(Hit(req, env, state, pat, Path(payload.get("saved", ""))))
    return hits, unmatched


def _download_attachments(settings: Settings, mailbox: str, msg_id: str, tmp: Path) -> list[tuple[str, bytes]]:
    tmp.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        himalaya_cmd(settings, "attachment", "download", "--mailbox", mailbox, msg_id, "--dir", str(tmp)),
        capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        return []
    out = []
    for f in sorted(tmp.iterdir()):
        if f.is_file():
            out.append((f.name, f.read_bytes()))
            f.unlink()
    return out


def check(settings: Settings, store: DataStore, led: Ledger, mailbox: str = "INBOX",
          since: date | None = None, dry_run: bool = False) -> tuple[list[Hit], list[dict]]:
    open_reqs = [r for r in led.all(include_closed=False) if not r.synthetic and r.sent_at]
    if not open_reqs:
        return [], []
    Path(settings.data_dir / "tmp").mkdir(parents=True, exist_ok=True)
    # himalaya's `after` is exclusive, so start one day before the earliest send
    since = since or (min(r.sent_at for r in open_reqs if r.sent_at) - timedelta(days=1))
    seen_ids = {e["payload"].get("message_id") for r in open_reqs for e in led.events(r.id)
                if e["payload"] and e["kind"].startswith("reply")}
    hits: list[Hit] = []
    unmatched: list[dict] = []
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
        atts = _download_attachments(settings, mailbox, env["id"], settings.data_dir / "tmp")
        state, pat, payload = process_reply(settings, led, req, env, text, atts,
                                            source="imap", dry_run=dry_run)
        path = Path(payload.get("saved", ""))
        hits.append(Hit(req, env, state, pat, path))
    return hits, unmatched
