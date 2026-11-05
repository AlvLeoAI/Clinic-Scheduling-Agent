"""Cached availability, bound to the query that produced it. Pure Python.

Slots are fetched for one date, practitioner and appointment type. Showing them after
any of the three changes would let "propose" pair an old slot time with new IDs, so a
cache whose query differs from the current selection is treated as empty.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from ui.client import Slot


@dataclass(frozen=True)
class SlotQuery:
    day: date
    practitioner_id: UUID
    appointment_type_id: UUID


Cache = tuple[SlotQuery, list[Slot]]


def cached_slots(cache: Cache | None, query: SlotQuery) -> list[Slot] | None:
    """The cached slots if they answer exactly this query, otherwise None (not fetched)."""
    if cache is None or cache[0] != query:
        return None
    return cache[1]
