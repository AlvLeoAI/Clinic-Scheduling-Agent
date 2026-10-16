"""Independent interval/DB oracle: no production scheduling, tools or renderer imports."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Chicago")


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def candidate(args, catalog, now, occupied):
    try:
        duration = catalog["types"][args["appointment_type_id"]]
        if args["practitioner_id"] not in catalog["practitioners"]:
            return False
        day = date.fromisoformat(args["local_date"])
        local = time.fromisoformat(args["local_time"])
        start = datetime.combine(day, local, ZONE)
        end = start + timedelta(minutes=duration)
        if day.weekday() > 4 or local.minute not in (0, 30) or local.second:
            return False
        if local < time(9) or end.date() != day or end.time() > time(17):
            return False
        delta = start.astimezone(UTC) - now.astimezone(UTC)
        if not timedelta(hours=24) <= delta <= timedelta(days=90):
            return False
        return not any(
            row["practitioner_id"] == args["practitioner_id"]
            and start < instant(row["ends_at"])
            and end > instant(row["starts_at"])
            for row in occupied
        )
    except (KeyError, ValueError, TypeError):
        return False


def slots(args, catalog, now, occupied):
    result = []
    for offset in range(16):
        hour, minute = divmod(9 * 60 + offset * 30, 60)
        trial = {**args, "local_time": f"{hour:02}:{minute:02}"}
        if candidate(trial, catalog, now, occupied):
            start = datetime.combine(
                date.fromisoformat(trial["local_date"]), time(hour, minute), ZONE
            )
            end = start + timedelta(minutes=catalog["types"][args["appointment_type_id"]])
            result.append({"starts_at": start.isoformat(), "ends_at": end.isoformat()})
    return result


def database_integrity(snapshot):
    appointments, proposals = snapshot["appointments"], snapshot["proposals"]
    for row in appointments:
        proposal = next((p for p in proposals if p["id"] == row["proposal_id"]), None)
        fields = ("session", "practitioner_id", "starts_at", "ends_at", "duration_minutes")
        if proposal is None or proposal["status"] != "CONFIRMED":
            return False
        if any(row[f] != proposal[f] for f in fields):
            return False
    for i, left in enumerate(appointments):
        for right in appointments[i + 1 :]:
            if left["proposal_id"] == right["proposal_id"]:
                return False
            if left["practitioner_id"] == right["practitioner_id"] and (
                instant(left["starts_at"]) < instant(right["ends_at"])
                and instant(left["ends_at"]) > instant(right["starts_at"])
            ):
                return False
    sources = [p["source_turn_id"] for p in proposals if p["source_turn_id"] is not None]
    return len(sources) == len(set(sources))
