"""Scenario scope is enforced by the actual runner, including its live branch (mock HTTP only)."""

import hashlib
import json
import re
from collections import Counter
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import event, text

from app.core.config import Settings
from evaluations.live_contracts import RunConfig
from evaluations.live_database import database_snapshot, prepare_database, validate_url
from evaluations.live_provider import SmokeProvider
from evaluations.live_runner import (
    DATASET,
    SmokeRun,
    load_smoke,
    main,
    run_smoke,
    select_scenarios,
)

pytestmark = pytest.mark.agent_offline
IDS = ["S1", "S2", "S3", "S4", "S5"]
DATASET_HASH = "53dcf6bb3c772f45e139fc424b477e554922d7968d67da388a6877f5515c985f"


@pytest.fixture(autouse=True)
def deny_real_http(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("External HTTP is forbidden in scenario selection tests.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)


@pytest.mark.parametrize("ident", IDS)
def test_select_one_exact_identifier_from_full_unchanged_dataset(ident):
    dataset = load_smoke()
    for live in (False, True):
        assert [c.id for c in select_scenarios(dataset, ident, live=live)] == [ident]
    assert [c.id for c in dataset.cases] == IDS
    assert hashlib.sha256(DATASET.read_bytes()).hexdigest() == DATASET_HASH


def test_offline_default_retains_all_scenarios():
    assert [c.id for c in select_scenarios(load_smoke())] == IDS


def test_duplicate_dataset_identifiers_fail_closed():
    dataset = load_smoke()
    dataset.cases[1] = dataset.cases[0]
    with pytest.raises(ValueError, match="unique"):
        select_scenarios(dataset, "S1", live=True)


@pytest.mark.parametrize(
    "scenario", ["", "s1", "S0", "S6", "ALL", " S1", "S1,S2", 0, False, ["S1"]]
)
def test_invalid_programmatic_selection_rejected_before_database_or_case(scenario):
    with (
        patch("evaluations.live_runner.verify_identity") as identity,
        patch("evaluations.live_runner.SmokeRun") as case,
        patch("evaluations.live_runner.SmokeProvider") as provider,
    ):
        for live in (False, True):
            with pytest.raises(ValueError):
                run_smoke(None, None, None, live=live, scenario=scenario)
        identity.assert_not_called()
        case.assert_not_called()
        provider.assert_not_called()


def test_missing_live_selection_rejected_before_database_or_case():
    with (
        patch("evaluations.live_runner.verify_identity") as identity,
        patch("evaluations.live_runner.SmokeRun") as case,
        patch("evaluations.live_runner.SmokeProvider") as provider,
    ):
        with pytest.raises(ValueError, match="explicit scenario"):
            run_smoke(None, None, None, live=True)
        identity.assert_not_called()
        case.assert_not_called()
        provider.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--live"],
        ["--live", "--prepare-db"],
        ["--scenario", "S6", "--prepare-db"],
        ["--live", "--scenario", "ALL", "--prepare-db"],
        ["--live", "--scenario", "S1", "--scenario", "S2"],
        ["--scenario", "S1", "--scenario", "S1"],
        ["--dry-run", "--scenario", ""],
    ],
)
def test_cli_scope_errors_fail_before_preparation_or_settings(
    arguments, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("CLINIC_EVAL_ENABLE_LIVE", "true")
    output = tmp_path / "must-not-be-created"
    monkeypatch.setattr("sys.argv", ["runner", *arguments, "--output-dir", str(output)])
    with (
        patch("evaluations.live_runner.Settings") as settings,
        patch("evaluations.live_runner.build_engine") as engine,
        patch("evaluations.live_runner.prepare_database") as prepare,
        patch("evaluations.live_runner.run_smoke") as run,
    ):
        assert main() == 1
        settings.assert_not_called()
        engine.assert_not_called()
        prepare.assert_not_called()
        run.assert_not_called()
    assert not output.exists()
    assert json.loads(capsys.readouterr().out)["gate"] == "FAIL"


@pytest.fixture
def selection_environment(engine):
    raw = engine.url.render_as_string(hide_password=False)
    validate_url(raw)
    with engine.connect() as connection:
        ident = connection.scalar(text("SELECT system_identifier::text FROM pg_control_system()"))
    prepare_database(engine, ident)
    settings = Settings(
        _env_file=None,
        database_url=raw,
        test_database_url=raw,
        openai_api_key="synthetic-test-credential",
        enable_live_openai=False,
    )
    return engine, ident, settings


def catalog_mock():
    """External dependency only: real runner/provider/service/tool/DB execution stays intact."""
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            output = [
                {
                    "type": "function_call",
                    "call_id": "selection_catalog",
                    "name": "get_clinic_catalog",
                    "arguments": "{}",
                }
            ]
        elif len(requests) == 2:
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"kind":"catalog","missing_fields":[]}',
                        }
                    ],
                }
            ]
        else:
            pytest.fail("An unselected scenario dispatched another provider request.")
        return httpx.Response(
            200,
            json={
                "model": "gpt-6-luna",
                "status": "completed",
                "output": output,
                "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
            },
        )

    return httpx.MockTransport(handler), requests


@pytest.mark.postgres
@pytest.mark.parametrize(
    "limits,expected_requests,stop",
    [
        ({"max_requests": 5, "max_estimated_usd": "0.20"}, 2, None),
        ({"max_requests": 1}, 1, "REQUEST_LIMIT"),
        ({"max_total_tokens": 12_000}, 1, "TOKEN_LIMIT"),
        ({"max_estimated_usd": "0.005"}, 1, "ESTIMATED_SPEND_LIMIT"),
    ],
)
def test_actual_live_runner_selects_s1_before_any_case_effects(
    selection_environment, monkeypatch, record_property, limits, expected_requests, stop
):
    engine, ident, settings = selection_environment
    monkeypatch.setenv("CLINIC_EVAL_ENABLE_LIVE", "true")
    before = database_snapshot(engine)
    transport, requests = catalog_mock()
    inserted = Counter()

    def observe(connection, cursor, statement, parameters, context, executemany):
        match = re.match(r"\s*INSERT INTO ([a-z_]+)", statement, re.I)
        if match:
            inserted[match[1]] += 1

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with (
            patch("httpx.HTTPTransport", return_value=transport) as http_factory,
            patch("evaluations.live_runner.SmokeRun", wraps=SmokeRun) as cases,
            patch("evaluations.live_runner.SmokeProvider", wraps=SmokeProvider) as providers,
        ):
            result = run_smoke(
                engine, settings, ident, RunConfig(**limits), live=True, scenario="S1"
            )
            constructed = [call.args[0].id for call in cases.call_args_list]
            provider_cases = [call.args[0].id for call in providers.call_args_list]
            http_factory.assert_called_once_with(retries=0)
    finally:
        event.remove(engine, "before_cursor_execute", observe)

    assert constructed == provider_cases == ["S1"]
    assert [c["case_id"] for c in result["cases"]] == ["S1"]
    assert result["scenario_selection"] == {
        "requested": "S1",
        "dataset_scenarios": IDS,
        "selected": ["S1"],
        "excluded": IDS[1:],
    }
    assert len(requests) == result["budget"]["provider_requests"] == expected_requests
    assert result["budget"]["stop_reason"] == stop
    assert inserted["chat_sessions"] == inserted["chat_turns"] == 1
    assert set(inserted) <= {"chat_sessions", "chat_turns", "conversation_items"}
    assert database_snapshot(engine) == before
    assert result["database_unchanged_after_scoped_cleanup"]
    assert hashlib.sha256(DATASET.read_bytes()).hexdigest() == DATASET_HASH
    for request in requests:
        users = [v["content"] for v in request["input"] if v.get("role") == "user"]
        assert users == [load_smoke().cases[0].input[0].message]
        assert request["store"] is False and request["parallel_tool_calls"] is False
    if stop is None:
        assert result["gate"] == "PASS"
        assert result["budget"]["provider_requests"] < 5
        assert result["cases"][0]["RAW_MODEL_VERDICT"] == "PASS"
    else:
        assert result["gate"] == "FAIL"
    record_property(
        "scenario_selection_safety",
        json.dumps(
            {
                "verification": "OFFLINE test of actual live branch; HTTP is MockTransport",
                "actual_live_openai_evals": "NOT RUN",
                "scenario": "S1",
                "constructed_cases": constructed,
                "provider_cases": provider_cases,
                "mock_requests": len(requests),
                "insert_counts": dict(inserted),
                "excluded_scenarios": IDS[1:],
                "excluded_case_constructions": 0,
                "excluded_provider_requests": 0,
                "excluded_sessions": 0,
                "excluded_case_effects": 0,
                "remaining_request_budget": RunConfig(**limits).max_requests - len(requests),
                "stop_reason": stop,
                "database_digest_unchanged": True,
            }
        ),
    )


@pytest.mark.postgres
def test_cli_live_selection_uses_actual_runner_and_mocked_http_only(
    selection_environment, monkeypatch, tmp_path
):
    engine, ident, settings = selection_environment
    before = database_snapshot(engine)
    monkeypatch.setenv("CLINIC_EVAL_ENABLE_LIVE", "true")
    monkeypatch.setenv("CLINIC_EVAL_DB_SYSTEM_ID", ident)
    output = tmp_path / "MOCKED_LIVE_BRANCH_TEST"
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--live",
            "--scenario",
            "S1",
            "--prepare-db",
            "--max-requests",
            "5",
            "--max-estimated-usd",
            "0.20",
            "--output-dir",
            str(output),
        ],
    )
    transport, requests = catalog_mock()
    with (
        patch("httpx.HTTPTransport", return_value=transport),
        patch("evaluations.live_runner.Settings", return_value=settings),
        patch("evaluations.live_runner.build_engine", return_value=engine),
        patch("evaluations.live_runner.SmokeRun", wraps=SmokeRun) as cases,
    ):
        assert main() == 0
        assert [call.args[0].id for call in cases.call_args_list] == ["S1"]
    report = json.loads((output / "R2_smoke_report.json").read_text())
    # A simulated live-mode CLI artifact is a test fixture, not real model evidence.
    assert report["scenario_selection"]["selected"] == ["S1"]
    assert report["scenario_selection"]["excluded"] == IDS[1:]
    assert report["dataset_sha256"] == DATASET_HASH
    assert len(requests) == 2 and report["budget"]["provider_requests"] == 2
    assert database_snapshot(engine) == before
