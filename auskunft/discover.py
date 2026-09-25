"""Discovery: which organisations does the user deal with? Read the mailbox through himalaya,
aggregate sender domains, map them to datenanfragen.de records. Then pull identification facts
(customer numbers, postal address) out of the mails from a chosen organisation."""

from __future__ import annotations

import html
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from auskunft.config import Settings
from auskunft.data import Company, DataStore
from auskunft.mail import himalaya_cmd

WEBMAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
           "gmx.de", "gmx.net", "web.de", "t-online.de", "icloud.com", "me.com", "posteo.de",
           "mailbox.org", "protonmail.com", "proton.me"}
# second-level public suffixes where the registrable domain has three labels
_SLD = {"co.uk", "com.au", "co.jp", "com.br"}


def registrable(domain: str) -> str:
    parts = domain.lower().strip(".").split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SLD:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


@dataclass
class Sender:
    domain: str
    count: int = 0
    last: str = ""
    names: set[str] = field(default_factory=set)
    addresses: set[str] = field(default_factory=set)
    company: Company | None = None


def _envelopes(settings: Settings, mailbox: str, pages: int, page_size: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        res = subprocess.run(
            himalaya_cmd(settings, "envelope", "list", "--json", "--mailbox", mailbox,
                         "--page", str(page), "--page-size", str(page_size)),
            capture_output=True, text=True, check=False,
        )
        if res.returncode != 0:
            break
        batch = json.loads(res.stdout or "{}").get("envelopes", [])
        out.extend(batch)
        if len(batch) < page_size:
            break
    return out


def discover(settings: Settings, store: DataStore, mailbox: str = "[Gmail]/All Mail",
             pages: int = 8, page_size: int = 500, own_email: str = "") -> list[Sender]:
    senders: dict[str, Sender] = defaultdict(lambda: Sender(domain=""))
    for env in _envelopes(settings, mailbox, pages, page_size):
        for frm in env.get("from") or []:
            email = (frm.get("email") or "").lower()
            if "@" not in email or email == own_email.lower():
                continue
            dom = registrable(email.split("@", 1)[1])
            s = senders[dom]
            s.domain = dom
            s.count += 1
            s.last = max(s.last, env.get("date") or "")
            if frm.get("name"):
                s.names.add(frm["name"])
            s.addresses.add(email)
    idx = store._domain_index()
    by_reg: dict[str, list[str]] = defaultdict(list)
    for d, slugs in idx.items():
        by_reg[registrable(d)].extend(slugs)
    for s in senders.values():
        if s.domain in WEBMAIL:
            continue
        slugs = idx.get(s.domain) or by_reg.get(s.domain) or []
        if slugs:
            s.company = store.company(slugs[0])
    return sorted(senders.values(), key=lambda s: (-s.count, s.domain))


# ---- facts ----------------------------------------------------------------------------------
_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)


def to_text(raw: str) -> str:
    """Strip HTML tags/entities so regexes see prose. Good enough for transactional mail."""
    txt = _TAG_RE.sub(" ", raw)
    txt = html.unescape(txt)
    txt = re.sub(r"[ \t\xa0]+", " ", txt)
    return re.sub(r"\n\s*\n+", "\n", txt)


_NUMBER_LABELS = (
    r"Buchungsnummer", r"Booking (?:Number|Reference)", r"Auftragsnummer", r"Bestellnummer",
    r"Rechnungsnummer", r"Order (?:Number|ID)",
    r"Kundennummer", r"Kunden-?Nr\.?", r"Kundenkonto", r"BahnCard-?(?:Nummer|Nr\.?)",
    r"Vertragsnummer", r"Vertrags-?Nr\.?", r"Mitgliedsnummer", r"Kartennummer",
    r"Account(?:-| )?(?:ID|Nummer)", r"Customer (?:ID|number)", r"Konto-?Nr\.?",
)
_NUMBER_RE = re.compile(
    r"(?P<label>" + "|".join(_NUMBER_LABELS) + r")\s*[:#]?\s*(?P<val>[A-Z0-9][A-Z0-9\-/]{3,25}(?: \d{3,4}){0,3})",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"(?P<street>[A-ZÄÖÜ][\w\.\-ÄÖÜäöüß ]{2,40}?\s\d{1,4}[a-zA-Z]?)\s*[\n,]\s*(?P<plz>\d{5})\s+(?P<city>[A-ZÄÖÜ][\wÄÖÜäöüß\- ]{2,40})"
)


@dataclass
class Facts:
    slug: str
    numbers: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    addresses: set[str] = field(default_factory=set)
    account_emails: set[str] = field(default_factory=set)
    messages_read: int = 0


def _read(settings: Settings, msg_id: str, mailbox: str) -> str:
    res = subprocess.run(
        himalaya_cmd(settings, "message", "read", "--mailbox", mailbox, msg_id),
        capture_output=True, text=True, check=False,
    )
    return res.stdout if res.returncode == 0 else ""


def facts_for(settings: Settings, company: Company | None, own_name: str,
              mailbox: str = "[Gmail]/All Mail", max_messages: int = 6,
              domains: tuple[str, ...] = ()) -> Facts:
    f = Facts(slug=company.slug if company else (domains[0] if domains else "?"))
    doms = {registrable(d) for d in (company.domains if company else domains)}
    envs: list[dict] = []
    for d in doms:
        res = subprocess.run(
            himalaya_cmd(settings, "envelope", "search", "--json", "--mailbox", mailbox,
                         "--page-size", str(max_messages), "from", d, "order", "by", "date", "desc"),
            capture_output=True, text=True, check=False,
        )
        if res.returncode == 0:
            envs.extend(json.loads(res.stdout or "{}").get("envelopes", []))
    envs = sorted(envs, key=lambda e: e.get("date", ""), reverse=True)[:max_messages]
    for env in envs:
        for to in env.get("to") or []:
            if to.get("email"):
                f.account_emails.add(to["email"].lower())
        text = to_text(_read(settings, env["id"], mailbox))
        if not text:
            continue
        f.messages_read += 1
        for m in _NUMBER_RE.finditer(text):
            f.numbers[m.group("label").strip()].add(m.group("val").strip())
        for m in _ADDRESS_RE.finditer(text):
            addr = f"{m.group('street').strip()}, {m.group('plz')} {m.group('city').strip()}"
            # keep only addresses that appear near the user's own name (within 200 chars)
            window = text[max(0, m.start() - 200): m.end() + 50]
            if own_name.split()[-1].lower() in window.lower():
                f.addresses.add(addr)
    return f
