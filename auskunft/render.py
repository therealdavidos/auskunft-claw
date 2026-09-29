"""Render datenanfragen.de letter templates into a complete request.

Template syntax (as used by datenanfragen.de):
  {var}                 variable substitution
  [flag>...]            conditional block, kept only if flag is truthy (may span lines)
  {free text prompt}    prose placeholder with spaces; filled from `prompts` or left for a human

We add a letter head (sender, recipient, date, subject) and a signature; the templates are body only.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import date

from auskunft.data import Company

_BLOCK = re.compile(r"\[([a-z_]+)>(.*?)\]", re.DOTALL)
_VAR = re.compile(r"\{([a-z_]+)\}")
_PROMPT = re.compile(r"\{([^{}]*\s[^{}]*)\}")  # curly with whitespace inside
_MARKUP = re.compile(r"</?(italic|bold|underline)>")  # datenanfragen.de inline markup
_THREAT = re.compile(
    r"(?:Sollten Sie meiner Anfrage nicht innerhalb der genannten Frist nachkommen.*?einzureichen\."
    r"|If you do not (?:comply|respond|answer).*?authority\.)\s*",
    re.DOTALL | re.IGNORECASE,
)
_L10N = {
    "de": {"subject": "Auskunftsersuchen nach Art. 15 DSGVO", "re": "Betreff", "name": "Name",
           "address": "Anschrift", "email": "E-Mail-Adresse", "dob": "Geburtsdatum",
           "ref": "Referenz", "ref_note": "bitte in Ihrer Antwort angeben"},
    "en": {"subject": "Data access request under Art. 15 GDPR", "re": "Subject", "name": "Name",
           "address": "Postal address", "email": "E-mail address", "dob": "Date of birth",
           "ref": "Reference", "ref_note": "please quote in your reply"},
}


@dataclass(frozen=True)
class Sender:
    name: str
    email: str
    postal_address: str
    birthdate: str = ""


@dataclass(frozen=True)
class Letter:
    tracking_id: str
    to_email: str
    to_name: str
    subject: str
    body: str
    sent_date: date
    company_slug: str
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.body


def new_tracking_id(slug: str, today: date | None = None) -> str:
    d = (today or date.today()).strftime("%Y%m%d")
    tag = re.sub(r"[^A-Z0-9]", "", slug.upper())[:4].ljust(4, "X")
    return f"AK-{d}-{tag}-{secrets.token_hex(2)}"


def fill_template(
    template: str,
    variables: dict[str, str],
    flags: dict[str, bool],
    prompts: dict[str, str] | None = None,
) -> str:
    """Apply flags, then variables, then prose prompts. Unknown prompts stay as `{...}`."""

    def _block(m: re.Match[str]) -> str:
        return m.group(2) if flags.get(m.group(1), False) else ""

    out = _MARKUP.sub("", template)
    out = _BLOCK.sub(_block, out)
    out = _VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), out)
    if prompts:
        out = _PROMPT.sub(lambda m: prompts.get(m.group(1).strip(), m.group(0)), out)
    # collapse 3+ blank lines left by removed blocks
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip() + "\n"


def id_data_lines(sender: Sender, company: Company, extra: dict[str, str], lang: str = "de") -> str:
    """Identification data: only what the company lists plus what the user chose to add."""
    t = _L10N[lang]
    lines: list[str] = [f"{t['name']}: {sender.name}", f"{t['address']}: {sender.postal_address}"]
    lines.append(f"{t['email']}: {sender.email}")
    wants_birthdate = any(e.type == "birthdate" for e in company.required_elements)
    if sender.birthdate and wants_birthdate:
        lines.append(f"{t['dob']}: {sender.birthdate}")
    for k, v in extra.items():
        if v:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def render_access_request(
    company: Company,
    sender: Sender,
    template: str,
    extra_id: dict[str, str] | None = None,
    today: date | None = None,
    tracking_id: str | None = None,
    data_portability: bool = True,
    polite: bool = False,
    lang: str = "de",
) -> Letter:
    today = today or date.today()
    tid = tracking_id or new_tracking_id(company.slug, today)
    extra_id = extra_id or {}
    if not company.email:
        raise ValueError(f"{company.slug} has no email contact; transport is {company.transport}")
    t = _L10N[lang]
    id_data = id_data_lines(sender, company, extra_id, lang)
    body = fill_template(
        template,
        variables={"id_data": id_data + "\n", "runs_list": ", ".join(company.runs)},
        flags={"data_portability": data_portability, "has_fields": True, "runs": bool(company.runs)},
    )
    if polite:
        # First contact: drop the "legal steps and complaint" sentence; it returns in the admonition.
        body = _THREAT.sub("", body)
    subject = f"{t['subject']} [Ref: {tid}]"
    datestr = today.strftime("%d.%m.%Y") if lang == "de" else today.strftime("%-d %B %Y")
    head = (
        f"{sender.name}\n{sender.postal_address}\n{sender.email}\n\n"
        f"{company.name}\n{company.address}\n\n"
        f"{datestr}\n\n"
        f"{t['re']}: {subject}\n\n"
    )
    signature = f"{sender.name}\n\n({t['ref']}: {tid} – {t['ref_note']})\n"
    full = head + body + signature
    return Letter(
        tracking_id=tid,
        to_email=company.email,
        to_name=company.name,
        subject=subject,
        body=full,
        sent_date=today,
        company_slug=company.slug,
        meta={"template": f"{lang}/access-default", "runs": ", ".join(company.runs),
              "polite": str(polite), "lang": lang},
    )


def render_admonition(template: str, request_date: date, problem: str, article: str = "15") -> str:
    return fill_template(
        template,
        variables={"request_date": request_date.strftime("%d.%m.%Y"), "request_article": article},
        flags={},
        prompts={
            "Beschreibung des Problems, z. B.: Leider erhielt ich bisher keine Antwort von Ihnen. "
            "Damit ist die Frist von einem Monat nach Art. 12 Abs. 3 S. 1 DSGVO überschritten.": problem
        },
    )
