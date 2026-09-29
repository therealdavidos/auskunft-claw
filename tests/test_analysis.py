from auskunft.analysis import analyse

DB = """Verarbeitungszwecke: Erbringung der Beförderungsleistung, Abrechnung.
Kategorien der Daten: Stammdaten, Buchungsdaten, Zahlungsdaten.
Empfänger: DB Fernverkehr AG, DB Regio AG, Zahlungsdienstleister (Adyen).
Speicherdauer: Buchungsdaten 10 Jahre (§ 147 AO).
Herkunft der Daten: von Ihnen selbst.
Automatisierte Entscheidungsfindung findet nicht statt.
Sie haben das Recht auf Berichtigung und Löschung sowie das Recht, Beschwerde bei einer Aufsichtsbehörde einzulegen.
Anbei die Kopie Ihrer Daten.
--- buchungen.csv ---
Buchung | Datum
1 | 2026-01-01
"""


def test_full_answer_complete_and_lists_clean():
    a = analyse(DB)
    assert a.complete, a.missing
    assert a.categories == ["Stammdaten", "Buchungsdaten", "Zahlungsdaten"]
    assert a.recipients == ["DB Fernverkehr AG", "DB Regio AG", "Zahlungsdienstleister (Adyen)"]


def test_partial_answer_names_gaps():
    a = analyse("Verarbeitungszwecke: Marketing.\nAnbei Ihre Daten.\nSie haben das Recht auf Löschung.")
    assert "c_recipients" in a.missing and "d_retention" in a.missing and "g_source" in a.missing
    assert not a.complete
