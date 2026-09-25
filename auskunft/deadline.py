"""Deadline arithmetic for GDPR Art. 12(3), computed by code, never by a model.

Rule (EDPB Guidelines 01/2022 §160, applying Regulation (EEC, Euratom) No 1182/71):
- The one-month period ends on the same calendar day of the following month
  (e.g. received 25.09. → ends 25.10.).
- If that day does not exist (31.01. → February), the period ends on the last day of that month.
- If the last day is a Saturday, Sunday or public holiday, the period ends at the end of the
  next working day.
- Extension: up to two further months (Art. 12(3) s. 2), only if notified within the first month.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

import holidays

WEEKEND = {5, 6}


def _holidays(year: int, subdiv: str | None) -> holidays.HolidayBase:
    # Use nationwide German holidays; add a Land (e.g. "BE") when the controller's seat is known.
    return holidays.country_holidays("DE", subdiv=subdiv, years=[year, year + 1])


def add_months(d: date, months: int) -> date:
    """Same day N months later, clamped to the last day of the target month."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def next_working_day(d: date, subdiv: str | None = None) -> date:
    hol = _holidays(d.year, subdiv)
    while d.weekday() in WEEKEND or d in hol:
        d += timedelta(days=1)
    return d


def due_date(received: date, months: int = 1, subdiv: str | None = None) -> date:
    """End of the statutory period that starts on `received`."""
    return next_working_day(add_months(received, months), subdiv)


def extension_allowed_until(received: date, subdiv: str | None = None) -> date:
    """Latest day on which a controller may still notify an extension (within the first month)."""
    return due_date(received, 1, subdiv)


def extended_due_date(received: date, extra_months: int, subdiv: str | None = None) -> date:
    if not 1 <= extra_months <= 2:
        raise ValueError("Art. 12(3) allows at most two further months")
    return due_date(received, 1 + extra_months, subdiv)


def days_left(due: date, today: date | None = None) -> int:
    today = today or date.today()
    return (due - today).days
