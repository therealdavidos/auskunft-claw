from auskunft.intake import REF_RE, classify, strip_quoted


def test_ref_regex():
    assert REF_RE.search("Re: Auskunft [Ref: AK-20260926-SCHU-18e8]").group(0) == "AK-20260926-SCHU-18e8"


def test_priority_id_over_ack():
    s, _ = classify("Ihre Anfrage ist eingegangen", "Bitte senden Sie uns eine Kopie Ihres Ausweises.")
    assert s == "id-requested"


def test_extension():
    s, _ = classify("Re: Auskunft", "Wir benötigen eine Fristverlängerung um zwei weitere Monate.")
    assert s == "extended"


def test_no_data_and_portal_and_default():
    assert classify("Re", "Zu Ihrer Person liegen uns keine Daten vor.")[0] == "no-data"
    assert classify("Re", "Please submit your request via our privacy portal.")[0] == "portal-redirect"
    assert classify("Automatische Antwort", "Vielen Dank, wir haben Ihre Nachricht erhalten.")[0] == "acknowledged"
    assert classify("Hi", "lorem ipsum")[0] == "acknowledged"


def test_attachment_answer():
    assert classify("Ihre Datenauskunft", "Anbei erhalten Sie die Kopie Ihrer Daten.")[0] == "answered-partial"


WISE = """##- Please type your reply above this line -##
----------------------------------------------
Gabriel, Sep 29, 2026, 13:12 UTC
Hallo Max,
Danke für deine Anfrage. Wir haben es am 27.09.2026 erhalten und arbeiten jetzt daran.
Liebe Grüße
----------------------------------------------
Max Mustermann, Sep 27, 2026, 15:28 UTC
Max Mustermann
Betreff: Auskunftsersuchen nach Art. 15 DSGVO [Ref: AK-1]
Zur Identifikation meiner Person habe ich folgende Daten beigefügt:
Name: Max Mustermann
"""


def test_quoted_own_letter_does_not_trigger_id_rule():
    kept = strip_quoted(WISE, "Max Mustermann")
    assert "arbeiten jetzt daran" in kept and "Identifikation" not in kept
    assert classify("Re: Auskunft", WISE, "Max Mustermann")[0] == "acknowledged"


def test_gmail_quote_header_cut():
    txt = "Wir brauchen nichts weiter.\n\nOn Mon, Sep 28, 2026 at 9:00 AM X wrote:\n> Ausweis bitte"
    assert classify("Re", txt)[0] == "acknowledged"
