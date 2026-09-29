"""Turn reply attachments into text: PDF, ZIP (optionally password-protected), CSV/JSON/TXT/HTML.
Everything is written under data/replies/<ref>/ and never leaves the machine."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from auskunft.discover import to_text

TEXT_SUFFIXES = {".txt", ".csv", ".json", ".html", ".htm", ".md", ".xml"}


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:  # noqa: BLE001 - corrupt/encrypted PDFs are data, not bugs
        return f"[pdf could not be read: {e}]"


def csv_text(data: bytes) -> str:
    txt = data.decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(txt[:2000])
    except csv.Error:
        return txt
    rows = list(csv.reader(io.StringIO(txt), dialect))
    return "\n".join(" | ".join(r) for r in rows)


def any_text(name: str, data: bytes) -> str:
    suf = Path(name).suffix.lower()
    if suf == ".pdf":
        return pdf_text(data)
    if suf == ".csv":
        return csv_text(data)
    if suf == ".json":
        try:
            return json.dumps(json.loads(data.decode("utf-8", errors="replace")), ensure_ascii=False,
                              indent=1)
        except json.JSONDecodeError:
            return data.decode("utf-8", errors="replace")
    if suf in {".html", ".htm"}:
        return to_text(data.decode("utf-8", errors="replace"))
    if suf in TEXT_SUFFIXES:
        return data.decode("utf-8", errors="replace")
    return ""


def unpack(name: str, data: bytes, out_dir: Path, password: str | None = None) -> list[tuple[str, str]]:
    """Save the attachment and return [(filename, extracted_text)], recursing into ZIPs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_bytes(data)
    if Path(name).suffix.lower() != ".zip":
        return [(name, any_text(name, data))]
    results: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            pwd = password.encode() if password else None
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    inner = zf.read(info, pwd=pwd)
                except RuntimeError as e:  # wrong/missing password
                    results.append((f"{name}/{info.filename}", f"[locked: {e}]"))
                    continue
                results.extend((f"{name}/{n}", t) for n, t in
                               unpack(Path(info.filename).name, inner, out_dir / Path(name).stem, password))
    except zipfile.BadZipFile:
        results.append((name, "[not a valid zip]"))
    return results
