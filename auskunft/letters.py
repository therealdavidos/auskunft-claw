"""Follow-up letters: reminder (Mahnung), complaint (Beschwerde, Art. 77) and gap follow-up.
Templates are datenanfragen.de's; the competent authority is derived from the company's seat."""

from __future__ import annotations

import re
from datetime import date

from auskunft.analysis import label
from auskunft.data import Authority, DataStore
from auskunft.render import fill_template

# Postcode leading digits → Land → authority slug for private-sector controllers.
# Bavaria: BayLDA (private sector); other Länder: one authority; federal bodies/telecom/post: BfDI.
_PLZ_LAND: list[tuple[range, str]] = [
    (range(1000, 2000), "desaechsdsb"),   # 01xxx Sachsen (also some Brandenburg 03xxx below)
    (range(2000, 3000), "desaechsdsb"),
    (range(3000, 4000), "debralda"),
    (range(4000, 5000), "desaechsdsb"),
    (range(6000, 7000), "desalbd"),
    (range(7000, 8000), "detlfdi"),
    (range(8000, 10000), "desaechsdsb"),
    (range(10000, 15000), "deberlbdi"),
    (range(15000, 17000), "debralda"),
    (range(17000, 20000), "demvldi"),
    (range(20000, 23000), "dehmbbfdi"),
    (range(23000, 26000), "deshuld"),
    (range(26000, 32000), "dendslfd"),
    (range(32000, 34000), "denrwldi"),
    (range(34000, 37000), "dehessbdi"),
    (range(37000, 38000), "dendslfd"),
    (range(38000, 40000), "dendslfd"),
    (range(40000, 49000), "denrwldi"),
    (range(49000, 50000), "dendslfd"),
    (range(50000, 54000), "denrwldi"),
    (range(54000, 57000), "derlpbdi"),
    (range(57000, 60000), "denrwldi"),
    (range(60000, 66000), "dehessbdi"),
    (range(66000, 67000), "desaarudz"),
    (range(67000, 68000), "derlpbdi"),
    (range(68000, 78000), "debawueldb"),
    (range(78000, 80000), "debawueldb"),
    (range(80000, 88000), "debaylda"),
    (range(88000, 89000), "debawueldb"),
    (range(89000, 98000), "debaylda"),
    (range(98000, 100000), "detlfdi"),
]
_SPECIAL = {
    "hannover": "dendslfd", "hamburg": "dehmbbfdi", "bremen": "debrelfdi", "berlin": "deberlbdi",
}


def authority_slug_for(address: str, fallback: str = "dendslfd") -> str:
    """Competent German authority for a controller seated at `address`; fallback = user's Land."""
    if not is_german(address):
        return fallback
    m = re.search(r"\b(\d{5})\s+([A-Za-zÄÖÜäöüß.\- ]+)", address or "")
    if not m:
        return fallback
    plz, city = int(m.group(1)), m.group(2).strip().lower()
    for key, slug in _SPECIAL.items():
        if city.startswith(key):
            return slug
    for rng, slug in _PLZ_LAND:
        if plz in rng:
            return slug
    return fallback


_GERMAN_COUNTRIES = {"deutschland", "germany", "de"}


def is_german(address: str) -> bool:
    """German seat: country line says so, or there is no country line and the last line is 'PLZ Ort'."""
    lines = [ln.strip() for ln in (address or "").splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1].lower()
    # country line says Germany, or no country line and a German-style "PLZ Ort" last line
    return last in _GERMAN_COUNTRIES or bool(re.match(r"^\d{5}\s+\S", lines[-1]))


def authority_for(store: DataStore, company_address: str, user_authority: str = "dendslfd") -> Authority:
    slug = authority_slug_for(company_address, user_authority) if is_german(company_address) else user_authority
    return store.authority(slug)


def _head(sender_name: str, sender_address: str, sender_email: str, to_name: str, to_address: str,
          today: date, subject: str) -> str:
    return (f"{sender_name}\n{sender_address}\n{sender_email}\n\n{to_name}\n{to_address}\n\n"
            f"{today.strftime('%d.%m.%Y')}\n\nBetreff: {subject}\n\n")


def render_admonition(store: DataStore, *, sender: tuple[str, str, str], company_name: str,
                      company_address: str, request_date: date, tracking_id: str, today: date,
                      days_over: int) -> tuple[str, str]:
    problem = (f"Leider erhielt ich bisher keine Antwort von Ihnen. Damit ist die Frist von einem Monat "
               f"nach Art. 12 Abs. 3 S. 1 DSGVO seit {days_over} {'Tag' if days_over == 1 else 'Tagen'} überschritten.")
    body = fill_template(store.template("admonition"),
                         {"request_date": request_date.strftime("%d.%m.%Y"), "request_article": "15"}, {},
                         prompts={"Beschreibung des Problems, z. B.: Leider erhielt ich bisher keine Antwort "
                                  "von Ihnen. Damit ist die Frist von einem Monat nach Art. 12 Abs. 3 S. 1 "
                                  "DSGVO überschritten.": problem})
    subject = f"Erinnerung: Auskunftsersuchen nach Art. 15 DSGVO vom {request_date:%d.%m.%Y} [Ref: {tracking_id}]"
    text = _head(*sender, company_name, company_address, today, subject) + body + f"{sender[0]}\n"
    return subject, text


def render_complaint(store: DataStore, *, sender: tuple[str, str, str], company_name: str,
                     company_address: str, request_date: date, reminder_date: date | None,
                     tracking_id: str, today: date, authority: Authority) -> tuple[str, str]:
    steps = (f"Der Verantwortliche hat auf meine Anfrage vom {request_date:%d.%m.%Y} (Referenz {tracking_id}) "
             f"innerhalb der Monatsfrist des Art. 12 Abs. 3 DSGVO nicht geantwortet")
    if reminder_date:
        steps += f" und auch auf meine Erinnerung vom {reminder_date:%d.%m.%Y} nicht reagiert"
    steps += ". Die Anfrage und die Erinnerung füge ich als Belege bei"
    body = fill_template(
        store.template("complaint"),
        {"request_date": request_date.strftime("%d.%m.%Y"), "request_article": "15",
         "request_recipient_address": f"{company_name}\n{company_address}"}, {},
        prompts={"Beschreibung der Verstöße des Verantwortlichen und der unternommenen Schritte (z. B. "
                 "Mahnungen, gesetzte Fristen oder weitere Korrespondenz; für solche auch Belege anfügen)": steps,
                 "Angabe von Kontaktmöglichkeit, z. B. E-Mail-Adresse, Postanschrift, Telefonnummer o. Ä.":
                 f"per E-Mail unter {sender[2]} oder postalisch unter {sender[1]}"})
    body = body.replace("[optional: Ich möchte Sie bitten, diese Informationen Dritten vorzuenthalten, "
                        "damit meine Anonymität gewahrt bleibt.]", "")
    subject = f"Beschwerde nach Art. 77 DSGVO gegen {company_name} [Ref: {tracking_id}]"
    text = _head(*sender, authority.name, authority.address, today, subject) + body + f"{sender[0]}\n"
    return subject, text


def render_followup(*, sender: tuple[str, str, str], company_name: str, company_address: str,
                    request_date: date, answer_date: date, tracking_id: str, today: date,
                    missing: list[str], reasons: dict[str, str] | None = None) -> tuple[str, str]:
    reasons = reasons or {}

    def _line(k: str) -> str:
        basis = f"Art. 15 Abs. 1 lit. {k[0]} DSGVO" if k[0] in "abcdefgh" and len(k) > 1 and k[1] == "_" \
            else "Art. 15 Abs. 3 DSGVO"
        why = f": {reasons[k]}" if reasons.get(k) else ""
        return f"- {label(k)} ({basis}){why}"

    items = "\n".join(_line(k) for k in missing)
    body = (f"Guten Tag,\n\nvielen Dank für Ihre Antwort vom {answer_date:%d.%m.%Y} auf mein "
            f"Auskunftsersuchen vom {request_date:%d.%m.%Y}.\n\nIhre Auskunft ist leider unvollständig. "
            f"Folgende Angaben, auf die ich nach Art. 15 DSGVO Anspruch habe, fehlen:\n{items}\n\n"
            f"Nach der Rechtsprechung des EuGH sind Empfänger konkret zu benennen (C-154/21) und die Kopie "
            f"muss eine vollständige, verständliche Wiedergabe der Daten sein (C-487/21).\n\n"
            f"Ich bitte Sie, die Auskunft innerhalb von zwei Wochen zu vervollständigen.\n\n"
            f"Mit freundlichen Grüßen\n{sender[0]}\n\n(Referenz: {tracking_id})\n")
    subject = f"Nachfrage zur Auskunft nach Art. 15 DSGVO [Ref: {tracking_id}]"
    return subject, _head(*sender, company_name, company_address, today, subject) + body
