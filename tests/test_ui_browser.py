"""Browser tests: Playwright drives the real Streamlit page; the fault sits behind it.

Chromium -> Streamlit (ui/app.py from the UI venv) -> FaultProxy -> the real app under
uvicorn -> the throwaway PostgreSQL. Excluded from the default run; `make browser-test`
installs the hashed locks and Chromium and runs them. The demo provider and the real
clock are used, so dates are picked from today, like a user would.
"""

import os
import re
import socket
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.db.models import Appointment
from app.db.seed import seed_catalog
from tests.support.live_stack import FaultProxy, LiveApi, counts, delete_sessions, write_receipt

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = [pytest.mark.browser, pytest.mark.postgres]
ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("America/Chicago")
UUID_TEXT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(url: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


@pytest.fixture
def ui(engine):
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    api = LiveApi(engine, utc_now).start()
    proxy = FaultProxy(api.url)
    port = free_port()
    python = os.environ.get("CLINIC_UI_PYTHON", str(ROOT / ".venv-ui/bin/python"))
    streamlit = subprocess.Popen(
        [
            python,
            "-m",
            "streamlit",
            "run",
            "ui/app.py",
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--server.headless=true",
            "--server.fileWatcherType=none",
            "--browser.gatherUsageStats=false",
        ],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT), "API_BASE_URL": proxy.url},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(f"http://127.0.0.1:{port}/_stcore/health")
        with sync_api.sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_default_timeout(20_000)
            page.goto(f"http://127.0.0.1:{port}/")
            sync_api.expect(page.get_by_text("Agent provider:")).to_be_visible()
            yield SimpleNamespace(page=page, proxy=proxy, engine=engine)
            browser.close()
    finally:
        streamlit.terminate()
        streamlit.wait(timeout=15)
        proxy.close()
        api.stop()
        delete_sessions(engine, proxy.session_ids)


def a_weekday(offset_days: int):
    day = datetime.now(ZONE).date() + timedelta(days=offset_days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def set_date(page, day) -> None:
    # Streamlit's date input is three react-aria spinbuttons: type into each segment.
    for part, value in [
        ("year", f"{day.year}"),
        ("month", f"{day.month:02d}"),
        ("day", f"{day.day:02d}"),
    ]:
        segment = page.get_by_role("spinbutton", name=f"{part}, Date")
        segment.click()
        page.keyboard.type(value)
    page.keyboard.press("Tab")
    sync_api.expect(page.get_by_role("spinbutton", name="day, Date")).to_have_attribute(
        "aria-valuenow", str(day.day)
    )


def button(page, name: str):
    return page.get_by_role("button", name=name, exact=True)


def check_availability(page, offset_days: int) -> None:
    set_date(page, a_weekday(offset_days))
    button(page, "Check availability").click()
    sync_api.expect(button(page, "Ask the agent to propose this slot")).to_be_visible()


def choose(page, label: str, index: int) -> None:
    # The selectbox opens from the keyboard; a click on its input does not. A rerun still
    # in flight closes the list, so wait until the app is idle and retry once.
    for attempt in range(2):
        sync_api.expect(page.get_by_test_id("stStatusWidget")).to_have_count(0)
        page.get_by_role("combobox", name=label).focus()
        page.keyboard.press("ArrowDown")
        option = page.get_by_role("listbox").get_by_role("option").nth(index)
        try:
            option.click(timeout=5_000)
            return
        except sync_api.TimeoutError:
            if attempt:
                raise


def propose(page) -> None:
    button(page, "Ask the agent to propose this slot").click()


def booked_ids(engine, session_ids: list[UUID]) -> list[str]:
    with Session(engine) as db:
        rows = db.scalars(select(Appointment.id).where(Appointment.session_id.in_(session_ids)))
        return [str(row) for row in rows]


def recovered_id(page) -> str:
    booked = page.get_by_text(re.compile(r"^Booked"))
    sync_api.expect(booked).to_be_visible()
    return re.search(UUID_TEXT, booked.inner_text()).group(0)


def test_a_lost_response_is_shown_uncertain_and_recovered_with_the_same_key(ui):
    page, proxy = ui.page, ui.proxy
    check_availability(page, 3)
    propose(page)
    proxy.arm("lose_response")
    button(page, "Confirm booking").click()

    sync_api.expect(page.get_by_text("The booking outcome is unknown")).to_be_visible()
    assert proxy.lost == 1 and counts(ui.engine, proxy.session_ids)["appointments"] == 1
    button(page, "Check booking status").click()

    appointment = recovered_id(page)
    sync_api.expect(button(page, "Check booking status")).to_have_count(0)
    result = {
        "case": "browser_lost_response",
        "evidence": "browser",
        "fault_boundary": "Streamlit-to-API response lost after commit",
        "confirm_requests_reaching_api": len(proxy.confirm_keys),
        "key_reused": len(proxy.confirm_keys) == 2 and len(set(proxy.confirm_keys)) == 1,
        "recovered_appointment_id": appointment,
        "db_appointment_ids": booked_ids(ui.engine, proxy.session_ids),
        **counts(ui.engine, proxy.session_ids),
    }
    write_receipt("browser_lost_response", result)
    assert result["key_reused"] and result["db_appointment_ids"] == [appointment]
    assert result["appointments"] == 1 and result["idempotency_records"] == 1


def test_a_new_proposal_keeps_the_uncertain_card_and_cannot_be_confirmed(ui):
    page, proxy = ui.page, ui.proxy
    check_availability(page, 4)
    propose(page)
    proxy.arm("lose_response")
    button(page, "Confirm booking").click()
    sync_api.expect(page.get_by_text("The booking outcome is unknown")).to_be_visible()

    # Another slot is proposed while the first outcome is unknown.
    choose(page, "Slot", 1)
    propose(page)
    sync_api.expect(page.get_by_text("An earlier confirmation is unresolved above")).to_be_visible()
    sync_api.expect(page.get_by_text("The booking outcome is unknown")).to_be_visible()
    sync_api.expect(button(page, "Check booking status")).to_be_enabled()
    sync_api.expect(button(page, "Confirm booking")).to_be_disabled()
    # Every card's heading says "(not booked until you confirm)" and the note says the
    # new proposal "does not cancel" the earlier one; anything else would be a claim.
    text = page.locator("body").inner_text().lower()
    for expected in ("(not booked until you confirm)", "does not cancel"):
        text = text.replace(expected, "")
    claims = [w for w in ("cancel", "not booked", "failed") if w in text]
    assert claims == [], claims

    button(page, "Check booking status").click()
    appointment = recovered_id(page)
    sync_api.expect(button(page, "Confirm booking")).to_be_enabled()
    result = {
        "case": "browser_new_proposal_while_uncertain",
        "evidence": "browser",
        "fault_boundary": "Streamlit-to-API response lost after commit, then a new proposal",
        "confirm_requests_reaching_api": len(proxy.confirm_keys),
        "key_reused": len(proxy.confirm_keys) == 2 and len(set(proxy.confirm_keys)) == 1,
        "recovered_appointment_id": appointment,
        "db_appointment_ids": booked_ids(ui.engine, proxy.session_ids),
        "cancellation_or_failure_claims": claims,
        **counts(ui.engine, proxy.session_ids),
    }
    write_receipt("browser_new_proposal_while_uncertain", result)
    assert result["key_reused"] and result["db_appointment_ids"] == [appointment]
    assert result["appointments"] == 1 and result["idempotency_records"] == 1


def test_changing_the_practitioner_hides_the_cached_slots(ui):
    page = ui.page
    check_availability(page, 5)
    choose(page, "Practitioner", 1)
    sync_api.expect(button(page, "Ask the agent to propose this slot")).to_have_count(0)
    sync_api.expect(
        page.locator('[data-testid="stSelectbox"]').filter(has_text="Slot")
    ).to_have_count(0)
