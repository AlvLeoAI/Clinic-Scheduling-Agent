"""Smoke test for the running container stack (compose.demo.yaml). Standard library only.

Checks liveness, readiness and /info, then one demo catalog turn through the API and
the UI health endpoint. Exits non-zero on the first failure.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


def call(method: str, url: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        raw = response.read()
        return response.status, response.headers, json.loads(raw) if raw[:1] == b"{" else raw


def wait_live(url: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if call("GET", url)[0] == 200:
                return
        except (urllib.error.URLError, ConnectionError):
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"FAIL: {url} did not answer within {seconds:.0f} s")
        time.sleep(1)


def check(label: str, condition: bool) -> None:
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:18000")
    parser.add_argument("--ui", default="http://127.0.0.1:8501")
    parser.add_argument("--wait", type=float, default=60)
    args = parser.parse_args(argv)
    api = args.api.rstrip("/") + "/api/v1"

    wait_live(f"{api}/health/live", args.wait)
    check("liveness", call("GET", f"{api}/health/live")[2]["status"] == "ok")
    check("readiness (database)", call("GET", f"{api}/health")[2]["database"] == "ok")
    check("info reports demo", call("GET", f"{api}/info")[2]["agent_provider"] == "demo")
    status, _, session = call("POST", f"{api}/sessions", {})
    check("session created", status == 201)
    message = {"client_message_id": str(uuid.uuid4()), "message": "catalog"}
    status, headers, reply = call("POST", f"{api}/chat/messages", message, session["session_token"])
    check("catalog turn 200", status == 200)
    check("X-Agent-Provider: demo", headers.get("X-Agent-Provider") == "demo")
    check("catalog reply lists practitioners", "Practitioners:" in reply["assistant_message"])
    wait_live(f"{args.ui.rstrip('/')}/_stcore/health", args.wait)
    check("ui health", call("GET", f"{args.ui.rstrip('/')}/_stcore/health")[2] == b"ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
