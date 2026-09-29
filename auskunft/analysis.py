"""What did they actually tell us? Deterministic extraction of the Art. 15(1) items from an
answer's text, and a completeness check. Heuristic by design: it finds the sections and quotes
them; it does not invent. An LLM can refine the summary later, the gaps list is what drives
the follow-up letter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Art. 15(1) items → (label, patterns that introduce the section)
ITEMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "a_purposes": ("Verarbeitungszwecke", (r"verarbeitungszweck", r"zweck(?:e)? der verarbeitung",
                                           r"purpose(?:s)? of (?:the )?processing")),
    "b_categories": ("Datenkategorien", (r"kategorien? (?:der |von )?(?:personenbezogenen )?daten",
                                         r"categor(?:y|ies) of (?:personal )?data", r"folgende daten")),
    "c_recipients": ("Empfänger", (r"empf[äa]nger", r"weitergabe", r"offengelegt", r"recipient",
                                   r"shared with", r"disclosed to")),
    "d_retention": ("Speicherdauer", (r"speicherdauer", r"aufbewahrung", r"l[öo]schfrist", r"gespeichert (?:bis|für)",
                                      r"retention", r"stored for", r"deleted after")),
    "e_rights": ("Betroffenenrechte", (r"berichtigung", r"l[öo]schung", r"einschr[äa]nkung", r"widerspruch",
                                       r"rectification", r"erasure", r"right to")),
    "f_complaint": ("Beschwerderecht", (r"beschwerde", r"aufsichtsbeh[öo]rde", r"supervisory authority",
                                        r"lodge a complaint")),
    "g_source": ("Herkunft", (r"herkunft", r"quelle", r"erhoben (?:bei|von)", r"source of (?:the )?data",
                              r"obtained from")),
    "h_automated": ("Automatisierte Entscheidungen", (r"automatisierte entscheidung", r"profiling",
                                                      r"automated decision", r"scoring")),
    "copy": ("Kopie der Daten", (r"kopie", r"anbei", r"im anhang", r"beigef[üu]gt", r"attached", r"copy of")),
    "third_country": ("Drittland", (r"drittland", r"third countr", r"standardvertragsklauseln",
                                    r"standard contractual clauses")),
}

_SENT_SPLIT = re.compile(r"(?<=[.!?:])\s+|\n+")


@dataclass
class Answer:
    found: dict[str, str] = field(default_factory=dict)   # item → quoted evidence
    missing: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    retention: str = ""
    source: str = ""

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def score(self) -> float:
        return round(len(self.found) / len(ITEMS), 2)


def _evidence(text: str, pats: tuple[str, ...]) -> str:
    low = text.lower()
    for p in pats:
        m = re.search(p, low)
        if m:
            # return the sentence/line containing the hit
            start = max(low.rfind("\n", 0, m.start()), low.rfind(". ", 0, m.start()) + 1, 0)
            end_candidates = [i for i in (low.find("\n", m.end()), low.find(". ", m.end())) if i != -1]
            end = min(end_candidates) if end_candidates else min(len(text), m.end() + 200)
            return text[start:end].strip()[:300]
    return ""


_LIST_AFTER = re.compile(r"(?:empf[äa]nger|recipients?|weitergegeben an|shared with)[^\n:]*[:\n]\s*((?:[-•*]?\s*[^\n]+\n?){1,12})",
                         re.IGNORECASE)
_CAT_AFTER = re.compile(r"(?:kategorien?[^\n:]*|folgende daten|categories of data)[:\n]\s*((?:[-•*]?\s*[^\n]+\n?){1,15})",
                        re.IGNORECASE)


def _bullets(block: str) -> list[str]:
    out = []
    for line in block.splitlines():
        line = line.strip(" -•*\t")
        if 2 < len(line) < 120 and not line.lower().startswith(("wir ", "we ", "die ", "the ")):
            out.append(line)
    return out[:15]


def analyse(text: str) -> Answer:
    a = Answer()
    for key, (_label, pats) in ITEMS.items():
        ev = _evidence(text, pats)
        if ev:
            a.found[key] = ev
        elif key not in ("third_country",):  # third-country info only owed if transfers exist
            a.missing.append(key)
    m = _LIST_AFTER.search(text)
    if m:
        a.recipients = _bullets(m.group(1))
    m = _CAT_AFTER.search(text)
    if m:
        a.categories = _bullets(m.group(1))
    a.retention = a.found.get("d_retention", "")
    a.source = a.found.get("g_source", "")
    return a


def label(key: str) -> str:
    return ITEMS[key][0]
