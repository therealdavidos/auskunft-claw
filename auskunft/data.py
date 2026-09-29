"""Loader for the datenanfragen.de open data (CC0): companies, supervisory authorities, templates.

The data is a `git clone` of https://github.com/datenanfragen/data under `vendor/datenanfragen`.
Records are one JSON file per company / authority. We keep them as plain dicts plus a thin
dataclass view for the fields the agent needs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RequiredElement:
    desc: str
    type: str
    optional: bool = False


@dataclass(frozen=True)
class Company:
    slug: str
    name: str
    address: str
    email: str | None
    fax: str | None
    web: str | None
    webform: str | None
    transport: str  # email | fax | letter | webform
    needs_id_document: bool
    required_elements: tuple[RequiredElement, ...]
    runs: tuple[str, ...]
    categories: tuple[str, ...]
    comments: tuple[str, ...]
    quality: str
    custom_access_template: str | None
    pgp_fingerprint: str | None
    request_language: str | None
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def letter_language(self) -> str:
        """de for controllers seated in DE/AT/CH or records that ask for German, else en."""
        if self.request_language in ("de", "en"):
            return self.request_language
        lines = [ln.strip().lower() for ln in self.address.splitlines() if ln.strip()]
        country = lines[-1] if lines else ""
        german = {"deutschland", "germany", "österreich", "austria", "schweiz", "switzerland",
                  "liechtenstein"}
        if country in german:
            return "de"
        if len(lines) >= 2 and __import__("re").match(r"^\d{5}\s+\S", country):
            return "de"  # no country line, German-style "PLZ Ort" last line
        return "en"

    @property
    def can_email(self) -> bool:
        return bool(self.email)

    @property
    def domains(self) -> tuple[str, ...]:
        """Domains this company is known by (for matching mailbox senders)."""
        out: list[str] = []
        if self.web:
            out.append(_domain_of(self.web))
        if self.email and "@" in self.email:
            out.append(self.email.split("@", 1)[1].lower())
        for r in self.runs:
            if "." in r and " " not in r:
                out.append(r.lower())
        return tuple(dict.fromkeys(d for d in out if d))


@dataclass(frozen=True)
class Authority:
    slug: str
    name: str
    address: str
    email: str | None
    webform: str | None
    web: str | None
    complaint_language: str | None
    transport: str | None
    pgp_fingerprint: str | None
    raw: dict[str, Any] = field(repr=False, compare=False)


def _domain_of(url: str) -> str:
    u = url.strip().lower()
    for prefix in ("https://", "http://"):
        u = u.removeprefix(prefix)
    u = u.split("/", 1)[0]
    return u.removeprefix("www.")


class DataStore:
    def __init__(self, vendor_dir: Path):
        self.root = Path(vendor_dir)
        self._domains: dict[str, list[str]] | None = None
        if not (self.root / "companies").is_dir():
            raise FileNotFoundError(
                f"datenanfragen data not found at {self.root}. Run: "
                "git clone --depth 1 https://github.com/datenanfragen/data vendor/datenanfragen"
            )

    # ---- companies -------------------------------------------------------------------------
    def company(self, slug: str) -> Company:
        path = self.root / "companies" / f"{slug}.json"
        if not path.is_file():
            raise KeyError(slug)
        return _company_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def iter_companies(self):
        for path in sorted((self.root / "companies").glob("*.json")):
            try:
                yield _company_from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError):
                continue

    def _domain_index(self) -> dict[str, list[str]]:
        if self._domains is None:
            idx: dict[str, list[str]] = {}
            for c in self.iter_companies():
                for d in c.domains:
                    idx.setdefault(d, []).append(c.slug)
            self._domains = idx
        return self._domains

    def find(self, query: str, limit: int = 10) -> list[Company]:
        """Find by slug, exact domain, or case-insensitive substring of name/slug/runs."""
        q = query.strip().lower()
        if not q:
            return []
        try:
            return [self.company(q)]
        except KeyError:
            pass
        dom = _domain_of(q) if "." in q else ""
        if dom:
            slugs = self._domain_index().get(dom, [])
            if slugs:
                return [self.company(s) for s in slugs[:limit]]
        hits: list[Company] = []
        for c in self.iter_companies():
            hay = " ".join([c.slug, c.name, *c.runs]).lower()
            if q in hay:
                hits.append(c)
                if len(hits) >= limit:
                    break
        return hits

    # ---- authorities -----------------------------------------------------------------------
    def authority(self, slug: str) -> Authority:
        path = self.root / "supervisory-authorities" / f"{slug}.json"
        if not path.is_file():
            raise KeyError(slug)
        return _authority_from_dict(json.loads(path.read_text(encoding="utf-8")))

    def iter_authorities(self):
        for path in sorted((self.root / "supervisory-authorities").glob("*.json")):
            yield _authority_from_dict(json.loads(path.read_text(encoding="utf-8")))

    # ---- templates -------------------------------------------------------------------------
    def template(self, name: str, lang: str = "de") -> str:
        path = self.root / "templates" / lang / f"{name}.txt"
        if not path.is_file():
            raise KeyError(f"{lang}/{name}")
        return path.read_text(encoding="utf-8")

    # ---- packs -----------------------------------------------------------------------------
    def pack(self, country: str = "de") -> list[dict[str, Any]]:
        path = self.root / "company-packs" / f"{country}.json"
        return json.loads(path.read_text(encoding="utf-8"))


def _company_from_dict(d: dict[str, Any]) -> Company:
    req = tuple(
        RequiredElement(
            desc=e.get("desc", ""), type=e.get("type", ""), optional=bool(e.get("optional", False))
        )
        for e in d.get("required-elements", []) or []
    )
    return Company(
        slug=d["slug"],
        name=d["name"],
        address=d.get("address", ""),
        email=d.get("email"),
        fax=d.get("fax"),
        web=d.get("web"),
        webform=d.get("webform"),
        transport=d.get("suggested-transport-medium", "email" if d.get("email") else "letter"),
        needs_id_document=bool(d.get("needs-id-document", False)),
        required_elements=req,
        runs=tuple(d.get("runs", []) or []),
        categories=tuple(d.get("categories", []) or []),
        comments=tuple(d.get("comments", []) or []),
        quality=d.get("quality", ""),
        custom_access_template=d.get("custom-access-template"),
        pgp_fingerprint=d.get("pgp-fingerprint"),
        request_language=d.get("request-language"),
        raw=d,
    )


def _authority_from_dict(d: dict[str, Any]) -> Authority:
    return Authority(
        slug=d["slug"],
        name=d["name"],
        address=d.get("address", ""),
        email=d.get("email"),
        webform=d.get("webform"),
        web=d.get("web"),
        complaint_language=d.get("complaint-language"),
        transport=d.get("suggested-transport-medium"),
        pgp_fingerprint=d.get("pgp-fingerprint"),
        raw=d,
    )
