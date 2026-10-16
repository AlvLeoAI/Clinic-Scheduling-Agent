"""Framework-free scheduling rules; all comparisons use elapsed UTC instants."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CLINIC_TIMEZONE = "America/Chicago"
CLINIC_ZONE = ZoneInfo(CLINIC_TIMEZONE)
OPENING = time(9)
CLOSING = time(17)
GRID = timedelta(minutes=30)
MIN_NOTICE = timedelta(hours=24)
MAX_HORIZON = timedelta(hours=90 * 24)


class PolicyViolation(ValueError):
    """A stable, safe domain message; never contains raw caller input."""


def as_utc(instant: datetime) -> datetime:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("An aware clock/instant is required.")
    return instant.astimezone(UTC)


@dataclass(frozen=True)
class Interval:
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self):
        object.__setattr__(self, "starts_at", as_utc(self.starts_at))
        object.__setattr__(self, "ends_at", as_utc(self.ends_at))
        if self.ends_at <= self.starts_at:
            raise ValueError("An interval must have positive elapsed duration.")

    def overlaps(self, other: "Interval") -> bool:
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at


def local_to_utc(local_date: date, local_time: time) -> datetime:
    """Reject non-existent/ambiguous wall times rather than choosing an offset."""
    if local_time.tzinfo is not None:
        raise PolicyViolation("A clinic-local time without an offset is required.")
    wall = datetime.combine(local_date, local_time)
    instants = set()
    for fold in (0, 1):
        instant = wall.replace(tzinfo=CLINIC_ZONE, fold=fold).astimezone(UTC)
        if instant.astimezone(CLINIC_ZONE).replace(tzinfo=None) == wall:
            instants.add(instant)
    if len(instants) != 1:
        raise PolicyViolation("The clinic-local time is ambiguous or does not exist.")
    return instants.pop()


def validate_start(
    local_date: date,
    local_time: time,
    *,
    opens_at: time,
    closes_at: time,
    duration_minutes: int,
    now_utc: datetime,
) -> Interval:
    """Validate one candidate against both approved policy and DB business hours."""
    now = as_utc(now_utc)
    if duration_minutes not in (30, 60):
        raise PolicyViolation("Appointment duration must be 30 or 60 minutes.")
    if local_date.isoweekday() > 5:
        raise PolicyViolation("The clinic is closed on weekends.")
    if local_time.tzinfo is not None:
        raise PolicyViolation("A clinic-local time without an offset is required.")
    if local_time.second or local_time.microsecond or local_time.minute % 30:
        raise PolicyViolation("Appointment starts must align to the 30-minute grid.")
    if not max(OPENING, opens_at) <= local_time < min(CLOSING, closes_at):
        raise PolicyViolation("The appointment must fit within clinic business hours.")
    start = local_to_utc(local_date, local_time)
    end = start + timedelta(minutes=duration_minutes)
    closing = local_to_utc(local_date, min(CLOSING, closes_at))
    if end > closing:
        raise PolicyViolation("The appointment must fit within clinic business hours.")
    if not now + MIN_NOTICE <= start <= now + MAX_HORIZON:
        raise PolicyViolation("Appointment notice must be between 24 hours and 90 days.")
    return Interval(start, end)


def candidate_slots(
    local_date: date,
    *,
    opens_at: time,
    closes_at: time,
    duration_minutes: int,
    now_utc: datetime,
) -> list[Interval]:
    """At most 16 candidates on the requested day; never searches another day."""
    now = as_utc(now_utc)
    if duration_minutes not in (30, 60):
        raise PolicyViolation("Appointment duration must be 30 or 60 minutes.")
    if local_date.isoweekday() > 5:
        return []
    earliest_date = (now + MIN_NOTICE).astimezone(CLINIC_ZONE).date()
    latest_date = (now + MAX_HORIZON).astimezone(CLINIC_ZONE).date()
    if not earliest_date <= local_date <= latest_date:
        return []
    slots = []
    for index in range(16):
        local_time = (datetime.combine(local_date, OPENING) + index * GRID).time()
        try:
            slot = validate_start(
                local_date,
                local_time,
                opens_at=opens_at,
                closes_at=closes_at,
                duration_minutes=duration_minutes,
                now_utc=now,
            )
        except PolicyViolation:
            continue
        slots.append(slot)
    return slots


def subtract_reservations(
    candidates: list[Interval], reservations: list[Interval]
) -> list[Interval]:
    return [slot for slot in candidates if not any(slot.overlaps(row) for row in reservations)]
