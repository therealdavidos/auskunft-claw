"""Model judgement of an Art. 15 answer against a legal rubric. The heuristic (analysis.py) finds
candidates and is the fallback; the judge decides adequacy. Every quote the model returns is
verified against the source text, so it cannot invent evidence. Input is the redacted answer text."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field

from auskunft.analysis import ITEMS, Answer, analyse

RUBRIC = """Du prüfst die Antwort eines Unternehmens auf ein Auskunftsersuchen nach Art. 15 DSGVO.
Bewerte für jeden Punkt, ob er in der Antwort enthalten ist (present) und ob er den gesetzlichen
Anforderungen genügt (adequate). Zitiere für jeden Punkt die kürzeste Textstelle (quote), die deine
Bewertung belegt – wörtlich aus der Antwort, sonst leer.

Punkte und Maßstab:
- a_purposes: Verarbeitungszwecke konkret benannt (nicht nur "gesetzliche Zwecke").
- b_categories: Kategorien der Daten benannt.
- c_recipients: Empfänger KONKRET benannt (EuGH C-154/21). Nur "Dienstleister" oder "Kategorien von
  Empfängern" ohne Namen ist NICHT adequate, außer das Unternehmen erklärt, dass Empfänger nicht
  identifizierbar sind.
- d_retention: Speicherdauer als Zeitraum ODER die Kriterien dafür. "siehe Datenschutzerklärung" ist
  NICHT adequate.
- e_rights: Hinweis auf Berichtigung/Löschung/Einschränkung/Widerspruch.
- f_complaint: Hinweis auf das Beschwerderecht bei einer Aufsichtsbehörde.
- g_source: Herkunft der Daten, wenn nicht beim Betroffenen erhoben. Wenn die Antwort sagt, alle Daten
  stammen vom Betroffenen selbst, ist das adequate.
- h_automated: Aussage, ob automatisierte Entscheidungsfindung/Profiling stattfindet (auch "findet
  nicht statt" ist adequate).
- copy: eine tatsächliche Kopie der Daten (Anhang, Export, Tabelle), nicht nur eine Beschreibung
  (EuGH C-487/21).
- third_country: Angabe zu Drittlandübermittlung/Garantien; wenn keine Übermittlung stattfindet und
  das gesagt wird, adequate. Wenn nichts dazu steht: present=false, adequate=false.

reason: höchstens 15 Wörter, sachlich, ohne Verweis auf diesen Maßstab. Ohne wörtliches quote gilt ein
Punkt als nicht belegt.

Antworte NUR mit JSON in genau dieser Form:
{"items": {"a_purposes": {"present": bool, "adequate": bool, "quote": str, "reason": str}, ... alle zehn ...},
 "summary": "ein Satz auf Deutsch, was fehlt oder dass die Auskunft vollständig ist"}"""

MODEL = os.environ.get("AUSKUNFT_LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
BASE = os.environ.get("AUSKUNFT_LLM_BASE", "https://integrate.api.nvidia.com/v1")


@dataclass
class Verdict:
    items: dict[str, dict] = field(
        default_factory=dict
    )  # key → {present, adequate, quote, reason, verified}
    summary: str = ""
    model: str = ""
    fallback: bool = False

    @property
    def missing(self) -> list[str]:
        return [
            k for k in ITEMS if k != "third_country" and not self.items.get(k, {}).get("adequate")
        ]

    @property
    def score(self) -> float:
        ok = sum(1 for k in ITEMS if self.items.get(k, {}).get("adequate"))
        return round(ok / len(ITEMS), 2)

    def as_analysis(self) -> dict:
        return {
            "found": {k: v.get("quote", "") for k, v in self.items.items() if v.get("adequate")},
            "missing": self.missing,
            "score": self.score,
            "judge": self.model,
            "reasons": {
                k: v.get("reason", "") for k, v in self.items.items() if not v.get("adequate")
            },
            "summary": self.summary,
        }


def available() -> bool:
    return bool(os.environ.get("AUSKUNFT_LLM_KEY"))


def _chat(text: str, timeout: int = 90) -> dict:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": f"Antwort des Unternehmens:\n\n{text[:12000]}"},
        ],
        "temperature": 0,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['AUSKUNFT_LLM_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    content = data["choices"][0]["message"]["content"]
    start, end = content.find("{"), content.rfind("}")
    return json.loads(content[start : end + 1])


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def judge(text: str, heuristic: Answer | None = None) -> Verdict:
    """Judge with the model; verify quotes; fall back to the heuristic if the model is unavailable."""
    heuristic = heuristic or analyse(text)
    if not available():
        return _from_heuristic(heuristic)
    try:
        raw = _chat(text)
    except Exception:  # noqa: BLE001 - network/model errors → heuristic, never a crash
        return _from_heuristic(heuristic)
    if not isinstance(raw, dict):
        return _from_heuristic(heuristic)
    items = raw.get("items") if isinstance(raw.get("items"), dict) else {}
    v = Verdict(model=MODEL, summary=str(raw.get("summary", ""))[:300])
    norm_text = _norm(text)
    for key in ITEMS:
        it = items.get(key)
        if not isinstance(it, dict):  # model returned "n/a", a list, null …: treat as not stated
            it = {}
        quote = str(it.get("quote") or "").strip()
        verified = bool(quote) and _norm(quote)[:120] in norm_text
        present = bool(it.get("present")) and (verified or not quote)
        adequate = bool(it.get("adequate")) and present and verified  # no evidence, no credit
        if quote and not verified:
            # the model cited something that is not in the text: distrust this item
            present, adequate = key in heuristic.found, False
            quote = heuristic.found.get(key, "")
        v.items[key] = {
            "present": present,
            "adequate": adequate,
            "quote": quote[:300],
            "reason": str(it.get("reason") or "")[:200],
            "verified": verified,
        }
    return v


def _from_heuristic(h: Answer) -> Verdict:
    v = Verdict(model="heuristic", fallback=True, summary="")
    for key in ITEMS:
        found = key in h.found
        v.items[key] = {
            "present": found,
            "adequate": found,
            "quote": h.found.get(key, ""),
            "reason": "" if found else "nicht gefunden (Heuristik)",
            "verified": found,
        }
    return v
