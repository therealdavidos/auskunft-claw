from auskunft.intake import REF_RE, classify


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
