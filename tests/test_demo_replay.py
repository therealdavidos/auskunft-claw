"""End-to-end: seed → fixtures → intake → tick → letters, on a temp data dir. Guards the video demo."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(subprocess.run(["which", "zip"], capture_output=True, check=False).returncode != 0, reason="zip CLI needed")
def test_demo_timeline(tmp_path):
    env = {**os.environ, "AUSKUNFT_DATA_DIR": str(tmp_path / "data-demo"), "AUSKUNFT_FROM_NAME": "Max Mustermann",
           "AUSKUNFT_FROM_EMAIL": "max.mustermann@example.org", "AUSKUNFT_POSTAL_ADDRESS": "Musterstraße 1, 12345 Musterstadt",
           "NO_COLOR": "1", "COLUMNS": "200"}
    fx = tmp_path / "fixtures"

    def run(*args):
        res = subprocess.run([sys.executable, "-m", "auskunft.cli", *args], env=env, capture_output=True, text=True, check=False,
                             cwd=Path(__file__).resolve().parents[1])
        assert res.returncode == 0, res.stdout + res.stderr
        return res.stdout

    run("demo", "seed")
    run("demo", "fixtures", "--out", str(fx))
    out = run("check", "--from-dir", str(fx), "--zip-password", "DB-2026")
    for expected in ("answered-full", "answered-partial", "id-requested", "extended", "portal-redirect",
                     "no-data", "refused", "acknowledged"):
        assert expected in out, out
    out = run("tick", "--today", "2026-10-28")
    assert out.count("overdue") == 3 and "Telekom" not in out
    out = run("ls", "--today", "2026-11-11", "--json")
    assert '"extended_until": "2026-12-28"' in out
