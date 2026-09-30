"""DataStore on a small deterministic vendor tree (plus one check against the real data)."""

from pathlib import Path

import pytest

from auskunft.data import Authority, Company, DataStore, _domain_of
from tests.conftest import VENDOR


@pytest.fixture
def store(mini_vendor) -> DataStore:
    return DataStore(mini_vendor)


def test_missing_vendor_dir_is_an_actionable_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="git clone"):
        DataStore(tmp_path / "nope")


def test_unknown_records_raise_keyerror(store):
    with pytest.raises(KeyError):
        store.company("does-not-exist")
    with pytest.raises(KeyError):
        store.authority("xx")
    with pytest.raises(KeyError, match="de/no-such-template"):
        store.template("no-such-template")


def test_template_and_pack(store):
    assert "Art. 15 DSGVO" in store.template("access-default")
    assert "Article 15" in store.template("access-default", lang="en") or "Art. 15" in store.template("access-default", lang="en")
    pack = store.pack("de")
    assert pack[0]["slug"] == "basics" and "example-gmbh" in pack[0]["companies"]


def test_company_view_fields(store):
    c = store.company("example-gmbh")
    assert isinstance(c, Company)
    assert c.needs_id_document and c.transport == "email" and c.can_email
    assert [e.desc for e in c.required_elements] == ["Name", "Anschrift", "Geburtsdatum"]
    assert c.required_elements[2].optional is True
    assert c.domains == ("example-gmbh.de", "example.shop")
    assert c.raw["slug"] == "example-gmbh"


def test_transport_defaults_without_suggestion(store):
    assert store.company("letter-only").transport == "letter"
    assert store.company("english-ltd").transport == "email"
    assert not store.company("letter-only").can_email


def test_letter_language_from_seat_or_record(store):
    assert store.company("example-gmbh").letter_language == "de"     # Deutschland
    assert store.company("austria-gmbh").letter_language == "de"     # Österreich
    assert store.company("letter-only").letter_language == "de"      # no country line, "80331 München"
    assert store.company("english-ltd").letter_language == "en"      # United Kingdom
    assert store.company("german-en").letter_language == "en"        # record asks for English


def test_iter_companies_skips_broken_records(store):
    slugs = [c.slug for c in store.iter_companies()]
    assert "broken" not in slugs and "nokey" not in slugs
    assert set(slugs) == {"example-gmbh", "letter-only", "english-ltd", "austria-gmbh", "german-en", "webform-only"}


def test_find_by_slug_domain_and_substring(store):
    assert [c.slug for c in store.find("example-gmbh")] == ["example-gmbh"]
    assert [c.slug for c in store.find("www.example-gmbh.de")] == ["example-gmbh"]
    assert [c.slug for c in store.find("https://example-gmbh.de/privacy")] == ["example-gmbh"]
    assert [c.slug for c in store.find("example.shop")] == ["example-gmbh"]        # via runs
    assert [c.slug for c in store.find("english.co.uk")] == ["english-ltd"]
    assert {c.slug for c in store.find("gmbh")} == {"example-gmbh", "austria-gmbh"}
    assert [c.slug for c in store.find("Example Shop")] == ["example-gmbh"]      # runs text, case-insensitive
    assert store.find("") == [] and store.find("   ") == []
    assert store.find("zzz-nothing") == [] and store.find("nothing.example") == []
    assert len(store.find("a", limit=2)) == 2


def test_domain_index_is_cached(store):
    idx = store._domain_index()
    assert idx["example.shop"] == ["example-gmbh"] and store._domain_index() is idx


def test_authorities(store):
    auths = list(store.iter_authorities())
    assert auths and all(isinstance(a, Authority) for a in auths)
    bay = store.authority("debaylda")
    assert "Bayerisches" in bay.name and bay.email and bay.complaint_language == "de"
    assert bay.raw["slug"] == "debaylda"


def test_domain_of():
    assert _domain_of("https://www.Example.org/path?x=1") == "example.org"
    assert _domain_of("http://shop.example.org") == "shop.example.org"


def test_real_vendor_find_by_domain():
    store = DataStore(Path(VENDOR))
    assert store.find("bahn.de")[0].slug == "deutsche-bahn"
    assert store.company("bolt").letter_language == "en"
    assert store.company("schufa").letter_language == "de"
