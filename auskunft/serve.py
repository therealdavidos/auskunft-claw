"""Tiny read-only dashboard server. Renders the report live from the ledger on every request, so the
link the agent sends never goes stale. Only two paths exist, both behind a random token:
  /r/<token>/        the real ledger
  /r/<token>/demo    the simulated timeline (data-demo)
Everything else is 404. Bound to the LAN so a phone on the same network can open it; the token is the
only credential, so the link must not be shared. Set AUSKUNFT_PUBLIC_HOST to advertise another host
(e.g. a Tailscale name)."""

from __future__ import annotations

import os
import platform
import secrets
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("AUSKUNFT_PORT", "8765"))


def token(data_dir: Path) -> str:
    p = data_dir / "dashboard.token"
    if p.is_file():
        return p.read_text().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(18)
    p.write_text(t)
    p.chmod(0o600)
    return t


def lan_host() -> str:
    if os.environ.get("AUSKUNFT_PUBLIC_HOST"):
        return os.environ["AUSKUNFT_PUBLIC_HOST"]
    if platform.system() == "Darwin":
        for iface in ("en0", "en1"):
            try:
                res = subprocess.run(["/usr/sbin/ipconfig", "getifaddr", iface], capture_output=True,
                                     text=True, check=False, timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    try:  # no packet is sent; this only asks the OS which source address it would use
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def url(data_dir: Path, demo: bool = False) -> str:
    return f"http://{lan_host()}:{PORT}/r/{token(data_dir)}/{'demo' if demo else ''}"


def running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_running(data_dir: Path) -> None:
    """Start the server detached if it is not listening yet."""
    if running():
        return
    log = open(data_dir / "dashboard.log", "ab")  # noqa: SIM115 - handed to the child process
    subprocess.Popen([sys.executable, "-m", "auskunft.serve"], stdout=log, stderr=log,
                     start_new_session=True, cwd=os.getcwd(), env=os.environ.copy())
    for _ in range(30):
        if running():
            return
        __import__("time").sleep(0.1)


def _render(demo: bool) -> bytes:
    from auskunft.config import load_settings
    from auskunft.ledger import Ledger
    from auskunft.report import render

    settings = load_settings()
    data_dir = Path("data-demo") if demo else settings.data_dir
    led = Ledger(data_dir / "ledger.db")
    today = None
    if demo:
        from datetime import date
        today = date(2026, 11, 11)
    html = render(led, today, "Auskunfts-Claw · Demo" if demo else "Auskunfts-Claw",
                  own_name="Max Mustermann" if demo else settings.from_name)
    led.close()
    return html.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "auskunft"

    def do_GET(self) -> None:
        from auskunft.config import load_settings

        tok = token(load_settings().data_dir)
        path = self.path.split("?", 1)[0].rstrip("/")
        routes = {f"/r/{tok}": False, f"/r/{tok}/demo": True}
        if path not in routes or not secrets.compare_digest(path.split("/")[2] if path.count("/") >= 2 else "", tok):
            self.send_response(404)
            self.end_headers()
            return
        try:
            body = _render(routes[path])
        except Exception as e:  # noqa: BLE001 - show the error on the page, keep serving
            body = f"<pre>report error: {e}</pre>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
