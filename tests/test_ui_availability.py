"""Cached availability is shown only for the exact query that fetched it."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from ui.availability import SlotQuery, cached_slots
from ui.client import Slot

pytestmark = pytest.mark.unit
START = datetime(2030, 1, 9, 15, tzinfo=UTC)


def test_cached_slots_belong_to_one_date_practitioner_and_type():
    query = SlotQuery(date(2030, 1, 9), uuid4(), uuid4())
    slots = [Slot(START, START + timedelta(minutes=30))]
    cache = (query, slots)
    assert cached_slots(cache, query) == slots
    assert cached_slots(cache, replace(query)) == slots  # equal, not identical, still matches

    for changed in (
        replace(query, day=date(2030, 1, 10)),
        replace(query, practitioner_id=uuid4()),
        replace(query, appointment_type_id=uuid4()),
    ):
        assert cached_slots(cache, changed) is None, changed


def test_no_cache_and_an_empty_answer_are_different():
    query = SlotQuery(date(2030, 1, 9), uuid4(), uuid4())
    assert cached_slots(None, query) is None
    # A fetched day with no free slots is an answer ("no free slots"), not a miss.
    assert cached_slots((query, []), query) == []
