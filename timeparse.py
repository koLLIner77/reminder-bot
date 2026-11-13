"""Turns the words after /remind into a due time (in UTC)."""
import re
from datetime import datetime, timedelta, timezone


class NeedTimezone(Exception):
    """A clock time was given, but the user hasn't set a time zone yet."""


CLOCK = r"\d{1,2}:\d{2}"        # 18:30
DATE = r"\d{4}-\d{2}-\d{2}"     # 2026-12-01


def parse_when(args, tz):
    """Read the time from the start of `args`.

    Returns (due_datetime_in_utc, number_of_words_used).
    Raises ValueError if the time can't be understood,
    NeedTimezone if a clock time is used but tz is None.
    """
    if not args:
        raise ValueError("no time given")

    now = datetime.now(timezone.utc)
    first = args[0].lower()

    # 1) Relative times: 10m, 2h, 3d  (no time zone needed)
    m = re.fullmatch(r"(\d+)([mhd])", first)
    if m:
        amount, unit = int(m.group(1)), m.group(2)
        try:
            step = {
                "m": timedelta(minutes=amount),
                "h": timedelta(hours=amount),
                "d": timedelta(days=amount),
            }[unit]
            return now + step, 1
        except OverflowError:
            raise ValueError("number too large")

    # 2) Clock times need a time zone
    looks_absolute = (
        first == "tomorrow" or re.fullmatch(CLOCK, first) or re.fullmatch(DATE, first)
    )
    if not looks_absolute:
        raise ValueError("unknown time format")
    if tz is None:
        raise NeedTimezone()

    local_now = now.astimezone(tz)

    # tomorrow 09:00
    if first == "tomorrow" and len(args) >= 2:
        clock = datetime.strptime(args[1], "%H:%M").time()
        local = datetime.combine(local_now.date() + timedelta(days=1), clock, tzinfo=tz)
        return local.astimezone(timezone.utc), 2

    # 18:30  -> today, or tomorrow if that time has already passed
    if re.fullmatch(CLOCK, first):
        clock = datetime.strptime(first, "%H:%M").time()
        local = datetime.combine(local_now.date(), clock, tzinfo=tz)
        if local <= local_now:
            local += timedelta(days=1)
        return local.astimezone(timezone.utc), 1

    # 2026-12-01 09:00
    if len(args) >= 2 and re.fullmatch(DATE, first):
        local = datetime.strptime(f"{first} {args[1]}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        return local.astimezone(timezone.utc), 2

    raise ValueError("unknown time format")