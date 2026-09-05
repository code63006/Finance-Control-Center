"""
Demonstration banking calendar — illustrative subset only.
Not a claim of complete or current Razorpay/Indian banking holiday policy.
"""

from datetime import date, timedelta

# Indian public holidays 2024 (major national + a few state-level)
# This is a DEMO SUBSET, not exhaustive.
DEMO_HOLIDAYS_2024 = {
    date(2024, 1, 26),    # Republic Day
    date(2024, 3, 25),    # Holi
    date(2024, 3, 29),    # Good Friday
    date(2024, 4, 11),    # Eid al-Fitr
    date(2024, 4, 14),    # Ambedkar Jayanti
    date(2024, 5, 1),     # Maharashtra Day
    date(2024, 6, 17),    # Eid al-Adha
    date(2024, 8, 15),    # Independence Day
    date(2024, 10, 2),    # Gandhi Jayanti
    date(2024, 10, 31),   # Diwali
    date(2024, 11, 1),    # Diwali Holiday
    date(2024, 11, 15),   # Guru Nanak Jayanti
    date(2024, 12, 25),   # Christmas
}

WEEKEND_DAYS = {5, 6}  # Saturday=5, Sunday=6


def is_business_day(d: date) -> bool:
    """Check if a date is a business day (not weekend, not holiday)."""
    if d.weekday() in WEEKEND_DAYS:
        return False
    return d not in DEMO_HOLIDAYS_2024


def next_business_day(d: date) -> date:
    """Return the next business day on or after d."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def business_days_between(start: date, end: date) -> int:
    """Count business days between start and end (inclusive of start)."""
    count = 0
    current = start
    while current <= end:
        if is_business_day(current):
            count += 1
        current += timedelta(days=1)
    return count
