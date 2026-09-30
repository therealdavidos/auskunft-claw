"""Model judge: request shape, quote verification, malformed output, heuristic fallback."""

from __future__ import annotations

import io
import json

import pytest
from conftest import cli_json, make_eml

from auskunft import judge as J
from auskunft.analysis import ITEMS, analyse

ANSWER = ("Verarbeitungszwecke: Vertragsabwicklung und Kundenservice.\n"
          "Empfänger: Dienstleister.\n"
          "Speicherdauer: 10 Jahre nach § 147 AO.\n"
          "Automatisierte Entscheidungsfindung findet nicht statt.")


def item(quote: str = "", present: bool = True, adequate: bool = True, reason: str = "ok") -> dict:
    return {"present": present, "adequate": adequate, "quote": quote, "reason": reason}


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("AUSKUNFT_LLM_KEY", "test-key-not-real")


@pytest.fixture
def model(monkeypatch, with_key):
    """Replace the HTTP call with a canned reply; returns the list of texts sent to it."""
    sent: list[str] = []

    def install(reply: dict | Exception):
        def fake_chat(text, timeout=90):
            sent.append(text)
            if isinstance(reply, Exception):
                raise reply
            return reply
        monkeypatch.setattr(J, "_chat", fake_chat)
        return sent
    return install


def test_available_follows_the_key(monkeypatch):
    assert not J.available()
    monkeypatch.setenv("AUSKUNFT_LLM_KEY", "k")
    assert J.available()


def test_no_key_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr(J, "_chat", lambda *a, **k: pytest.fail("model must not be called"))
    v = J.judge(ANSWER)
    assert v.fallback and v.model == "heuristic" and v.summary == ""
    h = analyse(ANSWER)
    assert {k for k, it in v.items.items() if it["adequate"]} == set(h.found)
    assert v.items["g_source"] == {"present": False, "adequate": False, "quote": "",
                                   "reason": "nicht gefunden (Heuristik)", "verified": False}
    assert v.missing == h.missing and v.score == h.score


def test_model_verdict_verifies_quotes(model):
    sent = model({"summary": "Empfänger fehlen konkret. " * 30, "items": {
        "a_purposes": item("verarbeitungszwecke:   Vertragsabwicklung"),        # whitespace/case-insensitive
        "c_recipients": item("Empfänger: Dienstleister", adequate=False, reason="nicht konkret"),
        "d_retention": item("Speicherdauer: 5 Jahre"),                          # not in the text
        "h_automated": item(""),                                                # no evidence given
    }})
    v = J.judge(ANSWER)
    assert sent == [ANSWER] and not v.fallback and v.model == J.MODEL
    assert len(v.summary) == 300
    assert v.items["a_purposes"] == {"present": True, "adequate": True,
                                     "quote": "verarbeitungszwecke:   Vertragsabwicklung",
                                     "reason": "ok", "verified": True}
    assert v.items["c_recipients"]["present"] and not v.items["c_recipients"]["adequate"]
    ret = v.items["d_retention"]  # fabricated quote → distrusted, heuristic evidence instead
    assert (ret["verified"], ret["adequate"], ret["present"]) == (False, False, True)
    assert ret["quote"].startswith("Speicherdauer: 10 Jahre")
    assert v.items["h_automated"]["present"] and not v.items["h_automated"]["adequate"]
    assert v.items["g_source"]["present"] is False  # item the model left out
    assert set(v.items) == set(ITEMS)
    assert v.missing == [k for k in ITEMS if k not in ("a_purposes", "third_country")]
    assert v.score == 0.1
    an = v.as_analysis()
    assert an["found"] == {"a_purposes": "verarbeitungszwecke:   Vertragsabwicklung"}
    assert an["reasons"]["c_recipients"] == "nicht konkret" and an["judge"] == J.MODEL


def test_model_item_that_is_not_an_object(model):
    model({"summary": "", "items": {"g_source": "n/a"}})
    assert J.judge(ANSWER).items["g_source"]["present"] is False


def test_model_error_falls_back(model):
    model(TimeoutError("model timed out"))
    v = J.judge(ANSWER)
    assert v.fallback and v.model == "heuristic"


def test_model_reply_without_items(model):
    model({"summary": None, "items": None})
    v = J.judge(ANSWER)
    assert v.summary == "None" and not any(it["present"] for it in v.items.values())
    assert v.score == 0.0


# ---- _chat: the HTTP layer, with urlopen faked ----------------------------------------------
class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(monkeypatch, content: str) -> list:
    seen = []

    def _open(req, timeout):
        seen.append((req, timeout))
        return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode())
    monkeypatch.setattr(J.urllib.request, "urlopen", _open)
    return seen


def test_chat_request_shape_and_json_extraction(monkeypatch, with_key):
    seen = fake_urlopen(monkeypatch, 'Sure! {"items": {}, "summary": "vollständig"} Hope this helps.')
    assert J._chat("x" * 20000, timeout=5) == {"items": {}, "summary": "vollständig"}
    [(req, timeout)] = seen
    assert timeout == 5 and req.full_url == f"{J.BASE}/chat/completions" and req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer test-key-not-real"
    body = json.loads(req.data)
    assert body["model"] == J.MODEL and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": J.RUBRIC}
    assert body["messages"][1]["content"].endswith("x" * 12000)
    assert "x" * 12001 not in body["messages"][1]["content"]


def test_malformed_model_output_falls_back(monkeypatch, with_key):
    fake_urlopen(monkeypatch, "I cannot answer that.")
    with pytest.raises(json.JSONDecodeError):
        J._chat("text")
    v = J.judge(ANSWER)
    assert v.fallback and v.model == "heuristic"


# ---- through intake: the model's verdict decides answered-full ------------------------------
def test_intake_uses_model_verdict_on_redacted_text(mini_env, ledger, runner, model):
    from datetime import date

    sent = model({"summary": "Auskunft vollständig.",
                  "items": {k: item("Anbei") for k in ITEMS}})
    r = ledger.create("example-gmbh", "Example GmbH", "datenschutz@example-gmbh.de",
                      "AK-20260928-EXAM-0a1b", state="sent", sent_at=date(2026, 9, 28),
                      due_at=date(2026, 10, 28))
    eml = make_eml(mini_env / "a.eml", frm=("Example GmbH", "datenschutz@example-gmbh.de"),
                   subject=f"Ihre Auskunft [Ref: {r.tracking_id}]",
                   body="Anbei Ihre Daten, Herr Max Mustermann, max.mustermann@example.org.")
    [hit] = cli_json(runner, "check", "--from-file", str(eml), "--json")
    assert hit["state"] == "answered-full" and ledger.get(r.id).state == "answered-full"
    assert "Mustermann" not in sent[0] and "[NAME]" in sent[0] and "[EMAIL]" in sent[0]
    an = next(e for e in ledger.events(r.id) if e["kind"] == "reply:received")["payload"]["analysis"]
    assert an["judge"] == J.MODEL and an["score"] == 1.0 and an["summary"] == "Auskunft vollständig."
    assert "heuristic_missing" in an and an["heuristic_score"] < 1.0
