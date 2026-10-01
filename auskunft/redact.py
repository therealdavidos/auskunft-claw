"""Redaction of personal data before any text reaches the model or the chat. Regex-based, biased
towards over-masking. The user can always see the unredacted file locally."""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE", re.compile(r"(?<![\w/])(?:\+\d{1,3}[ \-]?\(?\d{2,5}\)?|\(?0\d{2,5}\)?)[ \-/]?\d{3,}(?:[ \-]?\d{2,})*\b")),
    ("ADDRESS", re.compile(r"\b[A-ZÄÖÜ][\wäöüß.\-]+(?:[ \-][A-ZÄÖÜ]?[\wäöüß.\-]+){0,3}(?:str(?:aße|\.)|weg|platz|allee|gasse|ring|damm|ufer)\s\d{1,4}[a-z]?\b(?:,?\s*\d{5}\s+[A-ZÄÖÜ][\wäöüß\- ]+)?", re.IGNORECASE)),
    ("PLZ", re.compile(r"\b\d{5}\s+[A-ZÄÖÜ][a-zäöüß]+(?:[ \-][A-ZÄÖÜ][a-zäöüß]+)?\b")),
    ("ID", re.compile(r"\b(?:Kunden|Vertrags|Konto|Mitglieds|Versicherten|Steuer|Personalausweis|Ausweis)(?:-?nummer|-?nr\.?|-?ID)\s*:?\s*[A-Z0-9][A-Z0-9\-/ ]{3,25}\b", re.IGNORECASE)),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
]


# Dates are only masked when labelled as a birth date; other dates (received on, valid until) stay.
_DOB = re.compile(r"\b(geb(?:oren)?\.?(?:\s+am)?|Geburtsdatum|date of birth|DOB)(\s*:?\s*)"
                  r"(?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|1[0-2])\.(?:19|20)\d{2}\b", re.IGNORECASE)


def redact(text: str, keep_emails_at: tuple[str, ...] = (), own_name: str = "") -> str:
    """Mask PII. Company privacy addresses can be kept via `keep_emails_at` (domains)."""
    out = _DOB.sub(r"\1\2[DOB]", text)
    for label, pat in _PATTERNS:
        if label == "EMAIL":
            def _mask(m: re.Match[str]) -> str:
                dom = m.group(0).split("@", 1)[1].lower()
                return m.group(0) if any(dom.endswith(k) for k in keep_emails_at) else "[EMAIL]"
            out = pat.sub(_mask, out)
        else:
            out = pat.sub(f"[{label}]", out)
    if own_name:
        parts = [p for p in own_name.split() if len(p) > 2]
        for p in parts:
            out = re.sub(rf"\b{re.escape(p)}\b", "[NAME]", out)
    return out
