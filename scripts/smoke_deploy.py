"""Post-deploy smoke: one full booking through the API. Standard library only.

Runs after a release as a one-off task inside the VPC (it reaches the API through
Cloud Map, never through CloudFront), and locally against the container stack. It
checks readiness (the API's database login), books the last free slot in the booking
horizon, confirms it twice with the same Idempotency-Key and requires an identical
replay, then reads the appointment back. Exits non-zero on the first failure.

Each run leaves one synthetic appointment behind; nothing here deletes bookings.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

# (method, url, json body or None, extra headers) -> (status, raw body)
Http = Callable[[str, str, dict | None, dict[str, str]], tuple[int, bytes]]


class SmokeFailure(Exception):
    pass


def urllib_http(method: str, url: str, body: dict | None, headers: dict[str, str]):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json", **headers}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def check(label: str, condition: bool) -> None:
    print(("PASS " if condition else "FAIL ") + label, flush=True)
    if not condition:
        raise SmokeFailure(label)


class Smoke:
    def __init__(self, http: Http, api: str):
        self.http, self.api, self.token = http, api.rstrip("/") + "/api/v1", None

    def call(self, method: str, path: str, body: dict | None = None, **headers: str):
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        status, raw = self.http(method, self.api + path, body, headers)
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return status, raw, parsed

    def wait_ready(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            try:
                status, _, body = self.call("GET", "/health")
                if status == 200 and body and body.get("database") == "ok":
                    print("PASS readiness (the API's database login works)", flush=True)
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            if time.monotonic() > deadline:
                check(f"readiness within {seconds:.0f} s", False)
            time.sleep(2)

    def last_free_slot(self, today: date) -> tuple[str, str, date, str]:
        _, _, catalog = self.call("GET", "/catalog")
        _, _, info = self.call("GET", "/info")
        check("catalog and info", bool(catalog and info))
        first = today + timedelta(days=info["min_notice_hours"] // 24)
        day = today + timedelta(days=info["max_horizon_days"])
        while day >= first:
            for practitioner in catalog["practitioners"]:
                for kind in catalog["appointment_types"]:
                    query = (
                        f"/availability?date={day.isoformat()}"
                        f"&practitioner_id={practitioner['id']}&appointment_type_id={kind['id']}"
                    )
                    status, _, body = self.call("GET", query)
                    if status == 200 and body["slots"]:
                        start = datetime.fromisoformat(body["slots"][-1]["starts_at"])
                        return practitioner["id"], kind["id"], day, f"{start:%H:%M}"
            day -= timedelta(days=1)
        check("a free slot exists within the booking horizon", False)
        raise AssertionError("unreachable")

    def run(self, today: date, wait: float) -> dict:
        self.wait_ready(wait)
        practitioner, kind, day, hhmm = self.last_free_slot(today)
        print(f"PASS free slot {day.isoformat()} {hhmm}", flush=True)

        status, _, session = self.call("POST", "/sessions", {})
        check("session created", status == 201 and bool(session))
        self.token = session["session_token"]
        status, _, proposal = self.call(
            "POST",
            "/proposals",
            {
                "practitioner_id": practitioner,
                "appointment_type_id": kind,
                "local_date": day.isoformat(),
                "local_time": hhmm,
            },
        )
        check("proposal created", status == 201 and proposal.get("status") == "PENDING")

        key = f"smoke-{uuid.uuid4()}"
        confirm = f"/proposals/{proposal['proposal_id']}/confirm"
        first = self.call("POST", confirm, {}, **{"Idempotency-Key": key})
        check(
            "first confirm booked (201)", first[0] == 201 and first[2].get("status") == "CONFIRMED"
        )
        second = self.call("POST", confirm, {}, **{"Idempotency-Key": key})
        check("replay has the same status", second[0] == first[0])
        check("replay has a byte-identical body", second[1] == first[1])
        check(
            "replay has the same appointment and trace ID",
            (second[2]["appointment_id"], second[2]["trace_id"])
            == (first[2]["appointment_id"], first[2]["trace_id"]),
        )

        appointment_id = first[2]["appointment_id"]
        status, _, stored = self.call("GET", f"/appointments/{appointment_id}")
        check(
            "appointment readable",
            status == 200
            and stored["appointment_id"] == appointment_id
            and stored["proposal_id"] == proposal["proposal_id"],
        )
        return {"appointment_id": appointment_id, "slot": f"{day.isoformat()} {hhmm}"}


def main(argv: list[str] | None = None, *, http: Http = urllib_http, today: date | None = None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://api.clinic.internal:8000")
    parser.add_argument("--wait", type=float, default=60, help="Seconds to wait for readiness.")
    args = parser.parse_args(argv)
    try:
        result = Smoke(http, args.api).run(today or datetime.now(UTC).date(), args.wait)
    except SmokeFailure:
        return 1
    except Exception as error:  # an unexpected response shape is a failure, not a crash
        print(f"FAIL unexpected {type(error).__name__}: {str(error)[:200]}", flush=True)
        return 1
    print(json.dumps({"smoke": "ok", **result}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
