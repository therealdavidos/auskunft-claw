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


def id_data_lines(sender: Sender, company: Company, extra: dict[str, str]) -> str:
    """Identification data: only what the company lists plus what the user chose to add."""
    lines: list[str] = [f"Name: {sender.name}", f"Anschrift: {sender.postal_address}"]
    lines.append(f"E-Mail-Adresse: {sender.email}")
    wants_birthdate = any(e.type == "birthdate" for e in company.required_elements)
    if sender.birthdate and wants_birthdate:
        lines.append(f"Geburtsdatum: {sender.birthdate}")
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
) -> Letter:
    today = today or date.today()
    tid = tracking_id or new_tracking_id(company.slug, today)
    extra_id = extra_id or {}
    if not company.email:
        raise ValueError(f"{company.slug} has no email contact; transport is {company.transport}")

    id_data = id_data_lines(sender, company, extra_id)
    body = fill_template(
        template,
        variables={"id_data": id_data, "runs_list": ", ".join(company.runs)},
        flags={"data_portability": data_portability, "has_fields": True, "runs": bool(company.runs)},
    )
    subject = f"Auskunftsersuchen nach Art. 15 DSGVO [Ref: {tid}]"
    head = (
        f"{sender.name}\n{sender.postal_address}\n{sender.email}\n\n"
        f"{company.name}\n{company.address}\n\n"
        f"{today.strftime('%d.%m.%Y')}\n\n"
        f"Betreff: {subject}\n\n"
    )
    signature = f"{sender.name}\n\n(Referenz: {tid} – bitte in Ihrer Antwort angeben)\n"
    full = head + body + signature
    return Letter(
        tracking_id=tid,
        to_email=company.email,
        to_name=company.name,
        subject=subject,
        body=full,
        sent_date=today,
        company_slug=company.slug,
        meta={"template": "access-default", "runs": ", ".join(company.runs)},
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
