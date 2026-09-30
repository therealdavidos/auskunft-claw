"""Attachment unpacking: PDF, CSV, JSON, HTML, text, unknown binaries, plain and encrypted ZIPs."""

from __future__ import annotations

import io
import subprocess
import zipfile

import pytest
from conftest import HAS_ZIP, make_pdf

from auskunft.attachments import any_text, csv_text, pdf_text, unpack

SECRET = "Verarbeitungszwecke: Vertragsabwicklung"


def zip_bytes(files: dict[str, bytes], dirs: tuple[str, ...] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for d in dirs:
            zf.writestr(zipfile.ZipInfo(d.rstrip("/") + "/"), "")
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def locked_zip(tmp_path) -> bytes:
    if not HAS_ZIP:
        pytest.skip("zip CLI needed to build a password-protected archive")
    src = tmp_path / "src"
    src.mkdir()
    (src / "auskunft.txt").write_text(SECRET, encoding="utf-8")
    out = tmp_path / "locked.zip"
    subprocess.run(["zip", "-q", "-j", "-P", "DB-2026", str(out), str(src / "auskunft.txt")], check=True)
    return out.read_bytes()


# ---- single files ---------------------------------------------------------------------------
def test_pdf_text_and_unpack_saves_original(tmp_path):
    data = make_pdf(["Datenauskunft", SECRET])
    [(name, text)] = unpack("Auskunft.PDF", data, tmp_path / "att")
    assert name == "Auskunft.PDF" and "Datenauskunft" in text and "Vertragsabwicklung" in text
    assert (tmp_path / "att" / "Auskunft.PDF").read_bytes() == data


def test_corrupt_pdf_is_data_not_a_crash():
    assert pdf_text(b"%PDF-1.4 garbage").startswith("[pdf could not be read:")


def test_csv_sniffed_and_unsniffable():
    assert csv_text(b"Feld;Wert\nName;Max\nOrt;Musterstadt\n") == "Feld | Wert\nName | Max\nOrt | Musterstadt"
    assert csv_text(b"hallo\nwelt\n") == "hallo\nwelt\n"
    assert any_text("x.csv", b"a,b\n1,2\n") == "a | b\n1 | 2"


def test_json_valid_is_pretty_printed_invalid_is_raw():
    assert any_text("d.json", '{"name":"Max","orte":["Köln"]}'.encode()) == (
        '{\n "name": "Max",\n "orte": [\n  "Köln"\n ]\n}')
    assert any_text("d.json", b"{broken") == "{broken"


def test_html_text_and_unknown_suffixes(tmp_path):
    assert any_text("a.HTM", b"<h1>Auskunft</h1><p>Zweck&amp;Dauer</p>").split() == ["Auskunft", "Zweck&Dauer"]
    for name in ("a.txt", "a.md", "a.xml"):
        assert any_text(name, "Grüße".encode()) == "Grüße"
    assert any_text("a.txt", b"\xff\xfeok") == "��ok"
    assert any_text("image.png", b"\x89PNG\r\n") == ""
    assert unpack("blob.bin", b"\x00\x01", tmp_path / "new" / "dir") == [("blob.bin", "")]
    assert (tmp_path / "new" / "dir" / "blob.bin").is_file()


# ---- zips -----------------------------------------------------------------------------------
def test_plain_zip_recurses_skips_dirs_and_nested_zip(tmp_path):
    inner = zip_bytes({"deep.txt": b"tief"})
    data = zip_bytes({"auskunft.txt": SECRET.encode(), "sub/daten.csv": b"a;b\n1;2\n",
                      "inner.zip": inner}, dirs=("sub/",))
    res = dict(unpack("export.zip", data, tmp_path))
    assert res == {"export.zip/auskunft.txt": SECRET, "export.zip/daten.csv": "a | b\n1 | 2",
                   "export.zip/inner.zip/deep.txt": "tief"}
    assert (tmp_path / "export" / "daten.csv").is_file()        # flattened, no sub/ dir
    assert (tmp_path / "export" / "inner" / "deep.txt").read_bytes() == b"tief"
    assert (tmp_path / "export.zip").read_bytes() == data


def test_bad_zip(tmp_path):
    assert unpack("bad.zip", b"PK\x03\x04 not really", tmp_path) == [("bad.zip", "[not a valid zip]")]


def test_encrypted_zip_right_password(tmp_path, locked_zip):
    assert unpack("locked.zip", locked_zip, tmp_path, password="DB-2026") == [
        ("locked.zip/auskunft.txt", SECRET)]


def test_encrypted_zip_missing_password(tmp_path, locked_zip):
    [(name, text)] = unpack("locked.zip", locked_zip, tmp_path)
    assert name == "locked.zip/auskunft.txt"
    assert text.startswith("[locked:") and "password required" in text


def test_encrypted_zip_wrong_password(tmp_path, locked_zip):
    res = unpack("locked.zip", locked_zip, tmp_path, password="wrong")
    # ZipCrypto's 1-byte check lets ~1/256 wrong passwords through to a CRC error instead
    assert len(res) == 1 and res[0][1].startswith("[") and SECRET not in res[0][1]
    assert not (tmp_path / "locked" / "auskunft.txt").exists()


@pytest.mark.xfail(strict=True, reason="BUG: unpack() writes out_dir / <attachment filename> unsanitised; "
                   "a mail attachment named '../x' is written outside the reply directory")
def test_attachment_name_cannot_escape_out_dir(tmp_path):
    out = tmp_path / "replies" / "AK-1" / "attachments"
    unpack("../../escaped.txt", b"x", out)
    assert not (tmp_path / "replies" / "escaped.txt").exists()
