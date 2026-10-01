"""Read-only HTML report from the ledger: clocks, per-request timeline, data map. No server."""

from __future__ import annotations

import html
from datetime import date

from auskunft.analysis import ITEMS, label
from auskunft.deadline import days_left
from auskunft.ledger import Ledger

_CSS = """
body{font:15px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:0;padding:24px;background:#f7f7f5;color:#1a1a1a}
h1{margin:0 0 4px}h2{margin:28px 0 8px;font-size:18px}.sub{color:#666;margin-bottom:18px}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e3e3df}
th,td{padding:8px 10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top;font-size:14px}
th{background:#f0efe9;font-weight:600}.st{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#e8e8e3}
.st.sent,.st.acknowledged{background:#e6f0ff}.st.overdue,.st.refused{background:#ffe3e3}.st.reminded,.st.escalated,.st.complaint-filed{background:#ffe9c7}
.st.answered-full,.st.no-data{background:#dff5e1}.st.download-ready{background:#d7ecff;font-weight:600}.st.answered-partial,.st.extended,.st.id-requested,.st.portal-redirect,.st.clarification{background:#fff4cc}
.days{font-variant-numeric:tabular-nums}.neg{color:#b00020;font-weight:600}.soon{color:#9a6700;font-weight:600}
.tl{margin:4px 0 0 0;padding-left:18px;color:#444;font-size:13px}.tl li{margin:2px 0}
.ok{color:#137333}.miss{color:#b00020}.card{background:#fff;border:1px solid #e3e3df;padding:12px 14px;margin:10px 0}
.syn{color:#888;font-size:12px}.bar{height:8px;background:#eee;border-radius:4px;overflow:hidden;width:160px;display:inline-block;vertical-align:middle}
.bar i{display:block;height:100%;background:#137333}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 4px}.kpis div{background:#fff;border:1px solid #e3e3df;padding:10px 14px;min-width:92px}
.kpis b{display:block;font-size:24px}.kpis span{color:#666;font-size:12px}.scroll{overflow-x:auto}.sum{margin:6px 0;color:#333}
@media (max-width:600px){body{padding:14px}td,th{font-size:13px;padding:6px}}
"""


def render(led: Ledger, today: date | None = None, title: str = "Auskunfts-Claw",
           own_name: str = "") -> str:
    from auskunft.redact import redact

    today = today or date.today()
    reqs = led.all(include_closed=True)
    real = sum(1 for r in reqs if not r.synthetic)
    def _r(t: str) -> str:
        return redact(t, own_name=own_name)

    open_states = {"sent", "acknowledged", "clarification", "portal-redirect", "id-requested", "extended",
                   "answered-partial", "overdue", "reminded", "escalated", "complaint-filed"}
    n_open = sum(1 for r in reqs if r.state in open_states)
    # a data delivery (download link) is an answer, even though the user still has to fetch it
    n_done = sum(1 for r in reqs if r.state in ("answered-full", "no-data", "closed", "download-ready"))
    n_over = sum(1 for r in reqs if r.effective_due and days_left(r.effective_due, today) < 0 and r.state in open_states)
    n_you = sum(1 for r in reqs if r.state in ("id-requested", "portal-redirect", "clarification", "refused",
                                               "answered-partial", "download-ready"))
    upcoming = sorted(r.effective_due for r in reqs if r.effective_due and r.state in open_states
                      and days_left(r.effective_due, today) >= 0)
    nxt = upcoming[0] if upcoming else None
    out = [(f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{_CSS}</style>"),
           (f"<h1>🦞 {html.escape(title)}</h1><div class='sub'>Stand {today:%d.%m.%Y} · {len(reqs)} Anfragen "
            f"({real} echt, {len(reqs) - real} synthetisch)</div>")]
    out.append("<div class='kpis'>"
               f"<div><b>{n_open}</b><span>offen</span></div><div><b>{n_done}</b><span>beantwortet</span></div>"
               f"<div><b class='{'neg' if n_over else ''}'>{n_over}</b><span>überfällig</span></div>"
               f"<div><b>{n_you}</b><span>brauchen dich</span></div>"
               f"<div><b>{nxt.strftime('%d.%m.') if nxt else '–'}</b><span>nächste Frist</span></div></div>")
    # clocks
    out.append("<h2>Anfragen und Fristen</h2><div class='scroll'><table><tr><th>#</th><th>Organisation</th><th>Status</th>"
               "<th>Gesendet</th><th>Frist</th><th>Tage</th><th>Referenz</th></tr>")
    for r in reqs:
        due = r.effective_due
        left = days_left(due, today) if due else None
        cls = "neg" if left is not None and left < 0 else ("soon" if left is not None and left <= 7 else "")
        out.append(f"<tr><td>{r.id}</td><td>{html.escape(r.org_name)}"
                   f"{' <span class=syn>synthetisch</span>' if r.synthetic else ''}</td>"
                   f"<td><span class='st {r.state}'>{r.state}</span></td>"
                   f"<td>{r.sent_at:%d.%m.%Y}</td><td>{due:%d.%m.%Y}</td>"
                   f"<td class='days {cls}'>{left}</td><td><code>{r.tracking_id}</code></td></tr>"
                   if r.sent_at and due else
                   f"<tr><td>{r.id}</td><td>{html.escape(r.org_name)}</td><td>{r.state}</td><td colspan=4></td></tr>")
    out.append("</table></div>")
    # timelines
    out.append("<h2>Verlauf</h2>")
    for r in reqs:
        evs = led.events(r.id)
        out.append(f"<div class='card'><b>#{r.id} {html.escape(r.org_name)}</b> "
                   f"<span class='st {r.state}'>{r.state}</span><ul class='tl'>")
        for e in evs:
            p = e.get("payload") or {}
            extra = ""
            if e["kind"] == "reply:received":
                extra = f" → <b>{html.escape(str(p.get('classified')))}</b> „{html.escape(str(p.get('subject') or ''))[:70]}“"
                if p.get("attachments"):
                    extra += f" 📎 {', '.join(html.escape(a) for a in p['attachments'])}"
            elif e["kind"].startswith("letter:"):
                extra = f" → {html.escape(str(p.get('subject') or ''))[:80]}"
            out.append(f"<li>{e['ts'][:16].replace('T', ' ')} · {html.escape(e['kind'])}{extra}</li>")
        out.append("</ul></div>")
    # map
    rows = []
    for r in reqs:
        for e in led.events(r.id):
            an = (e.get("payload") or {}).get("analysis")
            if an:
                rows.append((r, e["ts"][:10], an))
    out.append("<h2>Wer weiß was über mich</h2>")
    if not rows:
        out.append("<div class='card'>Noch keine Antworten ausgewertet.</div>")
    for r, ts, an in rows:
        score = an.get("score", 0)
        out.append(f"<div class='card'><b>{html.escape(r.org_name)}</b> · Antwort {ts} · Vollständigkeit "
                   f"<span class='bar'><i style='width:{int(score * 100)}%'></i></span> {int(score * 100)}%")
        if an.get("summary"):
            out.append(f"<div class='sum'>{html.escape(an['summary'])}</div>")
        if an.get("categories"):
            out.append("<div><b>Datenkategorien:</b> " + "; ".join(html.escape(_r(c)) for c in an["categories"]) + "</div>")
        if an.get("recipients"):
            out.append("<div><b>Empfänger:</b> " + "; ".join(html.escape(_r(c)) for c in an["recipients"]) + "</div>")
        out.append("<table><tr><th>Art. 15 Punkt</th><th>Beleg</th></tr>")
        for key in ITEMS:
            if key in an.get("found", {}):
                out.append(f"<tr><td class='ok'>✓ {label(key)}</td><td>{html.escape(_r(an['found'][key])[:200])}</td></tr>")
            elif key in an.get("missing", []):
                why = an.get("reasons", {}).get(key) or "fehlt"
                out.append(f"<tr><td class='miss'>✗ {label(key)}</td><td class='miss'>{html.escape(why)} → Nachfrage</td></tr>")
        out.append("</table></div>")
    out.append("<p class='syn'>Alle Fristen nach Art. 12 Abs. 3 DSGVO, berechnet nach VO (EWG) 1182/71. "
               "Kontaktdaten und Vorlagen: datenanfragen.de (CC0).</p>")
    return "\n".join(out)
