"""Tiny read-only dashboard server. Renders the report live from the ledger on every request, so the
link the agent sends never goes stale. Only two paths exist, both behind a random token:
  /r/<token>/        the real ledger
  /r/<token>/demo    the simulated timeline (data-demo)
Everything else is 404. With Tailscale Serve in front (`tailscale serve --bg 8765`) the server binds to
loopback and the link is https://<machine>.<tailnet>.ts.net/…, reachable only from your own devices on
any network. Without Tailscale it binds to the LAN and the phone must share the Wi-Fi. The token is the
only credential inside that boundary, so the link must not be shared.
Overrides: AUSKUNFT_PUBLIC_URL (base URL), AUSKUNFT_BIND, AUSKUNFT_PUBLIC_HOST, AUSKUNFT_PORT."""

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
TAILSCALE_BINS = ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/usr/local/bin/tailscale",
                  "/opt/homebrew/bin/tailscale")


def _tailscale(*args: str) -> str | None:
    for b in TAILSCALE_BINS:
        try:
            res = subprocess.run([b, *args], capture_output=True, text=True, check=False, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if res.returncode == 0:
            return res.stdout
    return None


def tailscale_base() -> str | None:
    """https://<machine>.<tailnet>.ts.net if `tailscale serve` proxies to our port, else None."""
    status = _tailscale("serve", "status", "--json")
    if not status or str(PORT) not in status:
        return None
    me = _tailscale("status", "--json")
    if not me:
        return None
    import json

    name = (json.loads(me).get("Self") or {}).get("DNSName", "").rstrip(".")
    return f"https://{name}" if name else None


def public_base() -> str:
    """Base URL the link uses: explicit override, then Tailscale Serve, then the LAN address."""
    if os.environ.get("AUSKUNFT_PUBLIC_URL"):
        return os.environ["AUSKUNFT_PUBLIC_URL"].rstrip("/")
    ts = tailscale_base()
    if ts:
        return ts
    return f"http://{lan_host()}:{PORT}"


def bind_host() -> str:
    """Loopback when a proxy (Tailscale Serve) fronts us, LAN otherwise; AUSKUNFT_BIND overrides."""
    if os.environ.get("AUSKUNFT_BIND"):
        return os.environ["AUSKUNFT_BIND"]
    return "127.0.0.1" if (os.environ.get("AUSKUNFT_PUBLIC_URL") or tailscale_base()) else "0.0.0.0"


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
    return f"{public_base()}/r/{token(data_dir)}/{'demo' if demo else ''}"


def running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def ensure_running(data_dir: Path) -> None:
    """Start the server detached if it is not listening yet."""
    if running():
        return
    log = open(data_dir / "dashboard.log", "ab")  # noqa: SIM115 - handed to the child process
    # decide the bind address here: the detached child may not be able to query Tailscale itself
    env = {**os.environ, "AUSKUNFT_BIND": bind_host()}
    subprocess.Popen([sys.executable, "-m", "auskunft.serve"], stdout=log, stderr=log,
                     start_new_session=True, cwd=os.getcwd(), env=env)
    for _ in range(30):
        if running():
            return
        __import__("time").sleep(0.1)


_RELOADABLE = ("auskunft.redact", "auskunft.analysis", "auskunft.deadline", "auskunft.ledger", "auskunft.report")
_LOADED_MTIME: dict[str, float] = {}


def _reload_changed() -> None:
    """The server runs for days; reload rendering code whose source changed, so the page never goes stale."""
    import importlib

    for name in _RELOADABLE:
        mod = sys.modules.get(name) or importlib.import_module(name)
        try:
            mtime = Path(mod.__file__).stat().st_mtime
        except (OSError, TypeError):
            continue
        if name in _LOADED_MTIME and mtime > _LOADED_MTIME[name]:
            importlib.reload(mod)
        _LOADED_MTIME[name] = mtime


def _render(demo: bool) -> bytes:
    _reload_changed()
    from auskunft.config import load_settings
    from auskunft.ledger import Ledger
    from auskunft.report import render

    settings = load_settings()
    data_dir = Path("data-demo") if demo else settings.data_dir
    led = Ledger(data_dir / "ledger.db")
    today = None
    if demo:
        # the demo clock follows the timeline: "today" is the date of the latest recorded event,
        # so the dashboard advances step by step while the chat agent narrates the demo
        from datetime import date
        row = led.conn.execute("SELECT max(substr(ts, 1, 10)) FROM events").fetchone()
        try:
            today = date.fromisoformat(row[0]) if row and row[0] else date(2026, 9, 27)
        except ValueError:
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
    ThreadingHTTPServer((bind_host(), PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
