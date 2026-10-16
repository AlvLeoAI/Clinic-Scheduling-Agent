from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.domain.scheduling import (
    CLINIC_ZONE,
    Interval,
    PolicyViolation,
    candidate_slots,
    local_to_utc,
    subtract_reservations,
    validate_start,
)

DAY = date(2030, 1, 9)
START = datetime(2030, 1, 9, 15, tzinfo=UTC)
NOW = START - timedelta(days=2)


def validate(day=DAY, at=time(9), duration=30, now=NOW):
    return validate_start(
        day, at, opens_at=time(9), closes_at=time(17), duration_minutes=duration, now_utc=now
    )


def slots(day=DAY, duration=30, now=NOW):
    return candidate_slots(
        day, opens_at=time(9), closes_at=time(17), duration_minutes=duration, now_utc=now
    )


@pytest.mark.parametrize(
    "at,duration,allowed",
    [
        (time(8, 30), 30, False),
        (time(9), 30, True),
        (time(9), 60, True),
        (time(16), 60, True),
        (time(16, 30), 30, True),
        (time(16, 30), 60, False),
        (time(17), 30, False),
        (time(10, 15), 30, False),
        (time(10, 0, 1), 30, False),
        (time(10, 0, 0, 1), 30, False),
    ],
)
def test_business_boundaries_and_alignment(at, duration, allowed):
    if allowed:
        result = validate(at=at, duration=duration)
        assert result.ends_at - result.starts_at == timedelta(minutes=duration)
    else:
        with pytest.raises(PolicyViolation):
            validate(at=at, duration=duration)


@pytest.mark.parametrize("weekday", range(7))
def test_weekday_policy(weekday):
    day = date(2030, 1, 7) + timedelta(days=weekday)
    result = slots(day, now=datetime(2030, 1, 5, 15, tzinfo=UTC))
    assert len(result) == (16 if weekday < 5 else 0)
    if weekday >= 5:
        with pytest.raises(PolicyViolation):
            validate(day, now=datetime(2030, 1, 5, 15, tzinfo=UTC))


@pytest.mark.parametrize(
    "lead,allowed",
    [
        (timedelta(hours=24) - timedelta(microseconds=1), False),
        (timedelta(hours=24), True),
        (timedelta(hours=24) + timedelta(microseconds=1), True),
        (timedelta(days=90) - timedelta(microseconds=1), True),
        (timedelta(days=90), True),
        (timedelta(days=90) + timedelta(microseconds=1), False),
        (timedelta(0), False),
        (-timedelta(hours=1), False),
    ],
)
def test_inclusive_elapsed_notice_and_horizon(lead, allowed):
    now = START - lead
    if allowed:
        assert validate(now=now).starts_at == START
    else:
        with pytest.raises(PolicyViolation):
            validate(now=now)
    assert (START in [slot.starts_at for slot in slots(now=now)]) is allowed


@pytest.mark.parametrize("duration,count,last", [(30, 16, time(16, 30)), (60, 15, time(16))])
def test_stable_grid_duration_and_full_fit(duration, count, last):
    result = slots(duration=duration)
    assert len(result) == count
    assert result == slots(duration=duration)
    assert [row.starts_at for row in result] == sorted({row.starts_at for row in result})
    assert result[0].starts_at.astimezone(CLINIC_ZONE).time() == time(9)
    assert result[-1].starts_at.astimezone(CLINIC_ZONE).time() == last
    assert all(row.ends_at - row.starts_at == timedelta(minutes=duration) for row in result)


@pytest.mark.parametrize(
    "day,offset,utc_hour",
    [
        (date(2030, 3, 8), -6, 15),
        (date(2030, 3, 11), -5, 14),
        (date(2030, 11, 1), -5, 14),
        (date(2030, 11, 4), -6, 15),
    ],
)
def test_dst_transition_weeks(day, offset, utc_hour):
    result = slots(day, now=datetime.combine(day - timedelta(days=3), time(0), UTC))
    assert len(result) == 16
    assert result[0].starts_at == datetime.combine(day, time(utc_hour), UTC)
    assert all(
        row.starts_at.astimezone(CLINIC_ZONE).utcoffset() == timedelta(hours=offset)
        for row in result
    )


@pytest.mark.parametrize("day,utc_hour", [(date(2030, 3, 11), 14), (date(2030, 11, 4), 15)])
def test_elapsed_horizon_across_dst(day, utc_hour):
    limit = datetime.combine(day, time(utc_hour), UTC)
    result = slots(day, duration=60, now=limit - timedelta(hours=90 * 24))
    assert result == [Interval(limit, limit + timedelta(hours=1))]
    # The rule bounds starts, so the valid end can extend beyond the start horizon.
    assert result[0].ends_at > limit


@pytest.mark.parametrize(
    "day,at", [(date(2030, 3, 10), time(2, 30)), (date(2030, 11, 3), time(1, 30))]
)
def test_nonexistent_and_ambiguous_local_time_not_guessed(day, at):
    with pytest.raises(PolicyViolation):
        local_to_utc(day, at)


def test_partial_overlap_adjacency_and_utc_normalization():
    result = slots(duration=60)
    reservation = Interval(START + timedelta(minutes=75), START + timedelta(minutes=105))
    available = subtract_reservations(result, [reservation])
    assert [row.starts_at.astimezone(CLINIC_ZONE).time() for row in available][:2] == [
        time(9),
        time(11),
    ]
    adjacent = Interval(START - timedelta(hours=1), START)
    assert not adjacent.overlaps(result[0])
    assert (
        Interval(
            START.astimezone(CLINIC_ZONE), (START + timedelta(hours=1)).astimezone(CLINIC_ZONE)
        )
        == result[0]
    )


@pytest.mark.parametrize("duration", [0, 15, 45, 90])
def test_invalid_duration(duration):
    with pytest.raises(PolicyViolation):
        slots(duration=duration)


def test_naive_clock_rejected():
    with pytest.raises(ValueError, match="aware"):
        slots(now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("day", [date(2029, 1, 1), date(2031, 1, 1), date.min, date.max])
def test_past_out_of_horizon_and_extreme_dates_empty(day):
    assert slots(day) == []


def test_exhausted_notice_day_empty():
    assert slots(now=START - timedelta(hours=24) + timedelta(hours=8)) == []
