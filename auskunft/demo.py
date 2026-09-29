"""Demo / simulation on a separate data directory. Generates realistic reply fixtures (.eml) for
every archetype, addressed to the synthetic requests' tracking IDs, so the real intake, analysis
and letter pipeline can be shown end to end within minutes. Everything here is clearly synthetic."""

from __future__ import annotations

import io
import subprocess
import tempfile
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from auskunft.ledger import Ledger

PERSONA = {"name": "Max Mustermann", "email": "max.mustermann@example.org",
           "address": "Musterstraße 1, 12345 Musterstadt"}

# slug → archetype the fixture will play
SCENARIO: list[tuple[str, str]] = [
    ("deutsche-bahn", "zip-answer"),     # encrypted ZIP + separate password mail, decent answer
    ("flixbus", "pdf-partial"),          # PDF answer missing recipients/retention
    ("schufa", "id-requested"),
    ("telekom-de", "extended"),
    ("google", "portal-redirect"),
    ("az-direct", "no-data"),
    ("adsquare", "refused"),
    ("bolt", "acknowledged"),
    ("payback", "silent"),
]


def _msg(frm: tuple[str, str], to: tuple[str, str], subject: str, body: str, when: datetime,
         attachments: list[tuple[str, bytes, str]] | None = None) -> bytes:
    m = EmailMessage()
    m["From"] = f"{frm[0]} <{frm[1]}>"
    m["To"] = f"{to[0]} <{to[1]}>"
    m["Subject"] = subject
    m["Date"] = format_datetime(when)
    m["Message-ID"] = make_msgid(domain=frm[1].split("@")[1])
    m.set_content(body)
    for name, data, mime in attachments or []:
        maintype, subtype = mime.split("/", 1)
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


def _pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(50, y, line[:110])
        y -= 16
        if y < 60:
            c.showPage()
            y = 800
    c.save()
    return buf.getvalue()


def _zip_with_password(files: dict[str, bytes], password: str) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        for n, b in files.items():
            (dp / n).write_bytes(b)
        out = dp / "export.zip"
        subprocess.run(["zip", "-q", "-j", "-P", password, str(out), *[str(dp / n) for n in files]],
                       check=True)
        return out.read_bytes()


def fixtures(led: Ledger, out_dir: Path, base: date) -> list[Path]:
    """Write .eml fixtures for every synthetic request in the ledger. Returns paths in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    user = (PERSONA["name"], PERSONA["email"])
    paths: list[Path] = []
    by_slug = {r.slug: r for r in led.all(include_closed=False)}
    for slug, kind in SCENARIO:
        r = by_slug.get(slug)
        if r is None or kind == "silent":
            continue
        ref = r.tracking_id
        subj = f"Re: Auskunftsersuchen nach Art. 15 DSGVO [Ref: {ref}]"
        frm = (r.org_name, r.to_email or f"datenschutz@{slug}.example")
        when = datetime.combine(base + timedelta(days=SCENARIO.index((slug, kind)) % 5 + 1),
                                datetime.min.time(), tzinfo=UTC).replace(hour=10)
        files: list[tuple[str, bytes]] = []
        if kind == "acknowledged":
            files.append((f"{slug}-ack.eml", _msg(frm, user, subj,
                "Vielen Dank für Ihre Nachricht. Ihre Anfrage ist bei uns eingegangen und wird unter "
                "der Vorgangsnummer 4711 bearbeitet. Wir melden uns innerhalb der gesetzlichen Frist.", when)))
        elif kind == "id-requested":
            files.append((f"{slug}-id.eml", _msg(frm, user, subj,
                "Sehr geehrter Herr Mustermann,\n\nzur Bearbeitung Ihres Auskunftsersuchens benötigen wir "
                "zur Prüfung Ihrer Identität eine Kopie Ihres Personalausweises (Vorder- und Rückseite). "
                "Bitte übermitteln Sie diese über unser Formular.\n\nMit freundlichen Grüßen\nDatenschutz", when)))
        elif kind == "extended":
            files.append((f"{slug}-ext.eml", _msg(frm, user, subj,
                "Sehr geehrter Herr Mustermann,\n\nauf Grund der Komplexität Ihrer Anfrage und der hohen Zahl "
                "von Anfragen nehmen wir eine Fristverlängerung um zwei weitere Monate gemäß Art. 12 Abs. 3 "
                "DSGVO in Anspruch. Wir werden Ihnen die Auskunft bis spätestens in drei Monaten erteilen.", when)))
        elif kind == "portal-redirect":
            files.append((f"{slug}-portal.eml", _msg(frm, user, subj,
                "Hello,\n\nThanks for reaching out. To access a copy of your data, please use our self-service "
                "privacy portal after you log in to your account: https://example.com/privacy-portal\n\n"
                "Privacy Team", when)))
        elif kind == "no-data":
            files.append((f"{slug}-nodata.eml", _msg(frm, user, subj,
                "Sehr geehrter Herr Mustermann,\n\nwir haben unsere Systeme anhand der von Ihnen mitgeteilten "
                "Daten (Name, Anschrift) geprüft. Zu Ihrer Person liegen uns keine personenbezogenen Daten vor.\n\n"
                "Mit freundlichen Grüßen\nAZ Direct Datenschutz", when)))
        elif kind == "refused":
            files.append((f"{slug}-refused.eml", _msg(frm, user, subj,
                "Dear Mr Mustermann,\n\nwe are unable to comply with your request because we process data "
                "only under pseudonymous advertising identifiers (MAID). Without such an identifier we "
                "cannot identify any record relating to you.\n\nPrivacy Office", when)))
        elif kind == "pdf-partial":
            pdf = _pdf([
                "Flix S.E. - Datenauskunft nach Art. 15 DSGVO", f"Referenz: {ref}", "",
                "Verarbeitungszwecke: Vertragsabwicklung, Kundenservice, Marketing mit Einwilligung.",
                "Kategorien der Daten:", "- Stammdaten (Name, E-Mail, Telefon)", "- Buchungsdaten (Strecken, Daten, Preise)",
                "- Zahlungsdaten (Zahlungsart, letzte 4 Ziffern)", "- Nutzungsdaten der App", "",
                "Ihre Rechte: Berichtigung, Löschung, Einschränkung, Widerspruch, Datenübertragbarkeit.",
                "Sie haben das Recht, Beschwerde bei einer Aufsichtsbehörde einzulegen.",
                "Automatisierte Entscheidungsfindung: findet nicht statt.", "",
                "Anbei die Kopie Ihrer Daten (Buchungen 2024-2026).",
            ])
            files.append((f"{slug}-pdf.eml", _msg(frm, user, subj,
                "Sehr geehrter Herr Mustermann,\n\nanbei erhalten Sie Ihre Datenauskunft als PDF.\n\n"
                "Mit freundlichen Grüßen\nData Protection", when, [("Datenauskunft.pdf", pdf, "application/pdf")])))
        elif kind == "zip-answer":
            csv = ("Buchung;Datum;Von;Nach;Preis\n12345;2026-03-02;Hannover;Berlin;29,90\n"
                   "12399;2026-05-14;Berlin;München;49,90\n").encode()
            txt = (f"DB Vertrieb GmbH - Auskunft nach Art. 15 DSGVO ({ref})\n\n"
                   "Verarbeitungszwecke: Erbringung der Beförderungsleistung, Abrechnung, Kundenbindung (BahnCard).\n"
                   "Kategorien der Daten: Stammdaten, Buchungsdaten, Zahlungsdaten, BahnBonus-Punkte.\n"
                   "Empfänger: DB Fernverkehr AG, DB Regio AG, Zahlungsdienstleister (Adyen), Druckdienstleister.\n"
                   "Speicherdauer: Buchungsdaten 10 Jahre (§ 147 AO), Kundenkonto bis Löschung des Kontos.\n"
                   "Herkunft der Daten: von Ihnen selbst bei Registrierung und Buchung.\n"
                   "Automatisierte Entscheidungsfindung einschließlich Profiling findet nicht statt.\n"
                   "Sie haben das Recht auf Berichtigung, Löschung, Einschränkung und Widerspruch sowie das Recht,\n"
                   "Beschwerde bei einer Aufsichtsbehörde einzulegen.\n"
                   "Eine Übermittlung in Drittländer findet nicht statt.\n").encode()
            zipped = _zip_with_password({"auskunft.txt": txt, "buchungen.csv": csv}, "DB-2026")
            files.append((f"{slug}-zip.eml", _msg(frm, user, subj,
                "Sehr geehrter Herr Mustermann,\n\nanbei erhalten Sie die Kopie Ihrer Daten als "
                "passwortgeschütztes ZIP-Archiv. Das Passwort senden wir Ihnen in einer separaten E-Mail.\n\n"
                "Mit freundlichen Grüßen\nDB Datenschutz", when, [("export.zip", zipped, "application/zip")])))
            files.append((f"{slug}-pw.eml", _msg(frm, user, "Ihr Passwort für das ZIP-Archiv",
                "Das Passwort für das ZIP-Archiv lautet: DB-2026", when + timedelta(minutes=3))))
        for name, data in files:
            p = out_dir / name
            p.write_bytes(data)
            paths.append(p)
    return paths
