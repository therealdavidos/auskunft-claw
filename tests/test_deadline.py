from datetime import date

import pytest

from auskunft.deadline import add_months, due_date, extended_due_date, next_working_day


def test_same_day_next_month():
    # 25.09.2026 → 25.10.2026 is a Sunday → Monday 26.10.
    assert add_months(date(2026, 9, 25), 1) == date(2026, 10, 25)
    assert due_date(date(2026, 9, 25)) == date(2026, 10, 26)


def test_end_of_month_clamp():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_public_holiday_rolls_forward():
    # 03.10.2026 (Tag der Deutschen Einheit) is a Saturday → Monday 05.10.
    assert due_date(date(2026, 9, 3)) == date(2026, 10, 5)


def test_weekday_untouched():
    assert next_working_day(date(2026, 10, 7)) == date(2026, 10, 7)  # Wednesday


def test_extension_bounds():
    assert extended_due_date(date(2026, 9, 25), 2) == due_date(date(2026, 9, 25), 3)
    with pytest.raises(ValueError):
        extended_due_date(date(2026, 9, 25), 3)


def test_year_wrap():
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
