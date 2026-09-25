from datetime import date

from auskunft.ledger import Ledger


def test_create_transition_events(tmp_path):
    led = Ledger(tmp_path / "l.db")
    r = led.create("deutsche-bahn", "DB Vertrieb GmbH", "x@y.de", "AK-1", synthetic=True)
    assert r.state == "drafted" and r.synthetic
    r = led.transition(r.id, "sent", {"via": "smtp"}, sent_at=date(2026, 9, 25),
                       due_at=date(2026, 10, 26))
    assert r.state == "sent" and r.effective_due == date(2026, 10, 26)
    r = led.transition(r.id, "extended", extended_until=date(2026, 12, 28))
    assert r.effective_due == date(2026, 12, 28)
    kinds = [e["kind"] for e in led.events(r.id)]
    assert kinds == ["created", "state:sent", "state:extended"]
    assert led.by_tracking("AK-1").id == r.id
    assert led.by_tracking("nope") is None
