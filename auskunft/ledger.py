"""SQLite ledger: one row per request, an event log, and state transitions.

States (legal meaning documented in docs/03a-feasibility-data-legal.md):
  drafted, sent, acknowledged, portal-redirect, id-requested, clarification, extended,
  answered-full, answered-partial, no-data, refused, overdue, reminded, escalated,
  complaint-filed, closed
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
from pathlib import Path
from typing import Any

STATES = (
    "drafted",
    "sent",
    "acknowledged",
    "portal-redirect",
    "id-requested",
    "clarification",
    "extended",
    "answered-full",
    "answered-partial",
    "no-data",
    "refused",
    "overdue",
    "reminded",
    "escalated",
    "complaint-filed",
    "closed",
)

OPEN_STATES = {
    "sent", "acknowledged", "portal-redirect", "id-requested", "clarification", "extended",
    "answered-partial", "overdue", "reminded", "escalated", "complaint-filed",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL,
    org_name     TEXT NOT NULL,
    to_email     TEXT,
    tracking_id  TEXT UNIQUE NOT NULL,
    state        TEXT NOT NULL,
    sent_at      TEXT,
    due_at       TEXT,
    extended_until TEXT,
    synthetic    INTEGER NOT NULL DEFAULT 0,
    notes        TEXT,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER NOT NULL REFERENCES requests(id),
    ts          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_request ON events(request_id);
"""


@dataclass
class Request:
    id: int
    slug: str
    org_name: str
    to_email: str | None
    tracking_id: str
    state: str
    sent_at: date | None
    due_at: date | None
    extended_until: date | None
    synthetic: bool
    notes: str | None
    created_at: datetime

    @property
    def effective_due(self) -> date | None:
        return self.extended_until or self.due_at


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- writes -----------------------------------------------------------------------------
    def create(
        self,
        slug: str,
        org_name: str,
        to_email: str | None,
        tracking_id: str,
        state: str = "drafted",
        sent_at: date | None = None,
        due_at: date | None = None,
        synthetic: bool = False,
        notes: str | None = None,
    ) -> Request:
        if state not in STATES:
            raise ValueError(state)
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO requests(slug, org_name, to_email, tracking_id, state, sent_at, due_at,"
            " synthetic, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (slug, org_name, to_email, tracking_id, state,
             sent_at.isoformat() if sent_at else None, due_at.isoformat() if due_at else None,
             int(synthetic), notes, now),
        )
        self.conn.commit()
        req = self.get(cur.lastrowid)
        self.log(req.id, "created", {"state": state, "synthetic": synthetic})
        return req

    def transition(self, request_id: int, state: str, payload: dict[str, Any] | None = None,
                   ts: str | None = None, **fields: Any) -> Request:
        if state not in STATES:
            raise ValueError(state)
        sets = ["state = ?"]
        vals: list[Any] = [state]
        for k, v in fields.items():
            if k not in {"sent_at", "due_at", "extended_until", "notes", "to_email"}:
                raise ValueError(k)
            sets.append(f"{k} = ?")
            vals.append(v.isoformat() if isinstance(v, date) else v)
        vals.append(request_id)
        self.conn.execute(f"UPDATE requests SET {', '.join(sets)} WHERE id = ?", vals)
        self.conn.commit()
        self.log(request_id, f"state:{state}", payload, ts=ts)
        return self.get(request_id)

    def log(self, request_id: int, kind: str, payload: dict[str, Any] | None = None,
            ts: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events(request_id, ts, kind, payload) VALUES (?,?,?,?)",
            (request_id, ts or _now(), kind,
             json.dumps(payload, ensure_ascii=False, default=str) if payload else None),
        )
        self.conn.commit()

    # ---- reads ------------------------------------------------------------------------------
    def get(self, request_id: int) -> Request:
        row = self.conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        return _row(row)

    def by_tracking(self, tracking_id: str) -> Request | None:
        row = self.conn.execute(
            "SELECT * FROM requests WHERE tracking_id = ?", (tracking_id,)).fetchone()
        return _row(row) if row else None

    def by_slug(self, slug: str) -> list[Request]:
        rows = self.conn.execute(
            "SELECT * FROM requests WHERE slug = ? ORDER BY id", (slug,)).fetchall()
        return [_row(r) for r in rows]

    def all(self, include_closed: bool = True) -> list[Request]:
        rows = self.conn.execute("SELECT * FROM requests ORDER BY due_at, id").fetchall()
        reqs = [_row(r) for r in rows]
        return reqs if include_closed else [r for r in reqs if r.state != "closed"]

    def events(self, request_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT ts, kind, payload FROM events WHERE request_id = ? ORDER BY id",
            (request_id,)).fetchall()
        return [{"ts": r["ts"], "kind": r["kind"],
                 "payload": json.loads(r["payload"]) if r["payload"] else None} for r in rows]


def _row(r: sqlite3.Row) -> Request:
    return Request(
        id=r["id"], slug=r["slug"], org_name=r["org_name"], to_email=r["to_email"],
        tracking_id=r["tracking_id"], state=r["state"], sent_at=_d(r["sent_at"]),
        due_at=_d(r["due_at"]), extended_until=_d(r["extended_until"]),
        synthetic=bool(r["synthetic"]), notes=r["notes"],
        created_at=datetime.fromisoformat(r["created_at"]),
    )
