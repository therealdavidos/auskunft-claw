from auskunft.redact import redact


def test_redact_masks_pii_keeps_company_mail():
    txt = ("Kundennummer: 123456789, IBAN DE89 3704 0044 0532 0130 00, Tel. +49 511 1234567, "
           "geb. 01.02.1990, Musterstraße 1, 12345 Musterstadt, max@example.org, datenschutz@schufa.de, "
           "Karte 4111 1111 1111 1111. Gruß Max Mustermann")
    out = redact(txt, keep_emails_at=("schufa.de",), own_name="Max Mustermann")
    for token in ("123456789", "DE89", "1234567", "01.02.1990", "Musterstraße", "max@example.org",
                  "4111", "Mustermann"):
        assert token not in out, out
    assert "datenschutz@schufa.de" in out
    assert "[IBAN]" in out and "[EMAIL]" in out and "[NAME]" in out
