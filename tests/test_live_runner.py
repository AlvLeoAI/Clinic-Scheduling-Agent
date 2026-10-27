"""R2A safety and layered grading with mocks only, including real PostgreSQL isolation."""

import copy
import json
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.protocol import ProviderFailure
from app.agent.replies import reply_format
from app.agent.tools import tool_definitions
from app.core.config import Settings
from app.db.models import ChatSession, Clinic
from app.db.seed import CLINIC_ID, seed_catalog
from evaluations.live_contracts import BudgetStop, Ledger, RunConfig
from evaluations.live_database import (
    database_snapshot,
    prepare_database,
    require_fixture,
    validate_url,
    verify_identity,
)
from evaluations.live_graders import grade_smoke
from evaluations.live_provider import SmokeProvider
from evaluations.live_runner import load_smoke, main, reserve_report, run_smoke, write_report

pytestmark = pytest.mark.agent_offline
SAFE = "postgresql+psycopg://clinic_demo:synthetic@127.0.0.1:15433/clinic_scheduling_test"


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real HTTP attempted by offline verification.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


def test_baseline_configuration_and_synthetic_cases():
    config = RunConfig()
    assert config.model == "gpt-6-luna" and config.reasoning_effort == "none"
    assert config.max_estimated_usd == 1 and config.max_requests == 25
    data = load_smoke()
    assert [c.id for c in data.cases] == ["S1", "S2", "S3", "S4", "S5"]
    assert all("Synthetic" in c.input[0].message for c in data.cases)
    assert not any("00000000-" in c.input[0].message for c in data.cases)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_requests": 0},
        {"max_requests": 26},
        {"max_estimated_usd": "1.01"},
        {"max_estimated_usd": "NaN"},
        {"max_total_tokens": 0},
        {"model": "unreviewed-model"},
        {"max_input_tokens": 272_001},
    ],
)
def test_limits_reject_unsafe_configuration(changes):
    with pytest.raises(ValidationError):
        RunConfig(**changes)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"max_requests": 1}, "REQUEST_LIMIT"),
        ({"max_total_tokens": 1}, "TOKEN_LIMIT"),
        ({"max_estimated_usd": Decimal("0.0000001")}, "ESTIMATED_SPEND_LIMIT"),
        ({"max_input_tokens": 1}, "INPUT_LIMIT"),
    ],
)
def test_global_conservative_pre_request_limits(changes, reason):
    ledger = Ledger(RunConfig(**changes))
    if reason == "REQUEST_LIMIT":
        ledger.admit({})
    before = ledger.report()
    with pytest.raises(BudgetStop, match=reason):
        ledger.admit({})
    assert ledger.requests == before["provider_requests"]
    assert ledger.reserved_tokens == before["reserved_tokens"]
    assert ledger.reserved_usd == Decimal(before["reserved_estimated_usd"])
    assert ledger.stop_reason == reason


def test_exact_token_and_money_boundaries_and_no_refunds():
    probe = Ledger(RunConfig())
    admitted = probe.admit({})
    config = RunConfig(
        max_total_tokens=admitted["total_tokens"],
        max_estimated_usd=Decimal(admitted["estimated_usd"]),
    )
    ledger = Ledger(config)
    reservation = ledger.admit({})
    ledger.record_usage({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, reservation)
    assert ledger.reserved_tokens == admitted["total_tokens"]
    assert ledger.reserved_usd == Decimal(admitted["estimated_usd"])
    with pytest.raises(BudgetStop):
        ledger.admit({})


@pytest.mark.parametrize(
    "raw",
    [
        SAFE.replace("127.0.0.1", "localhost"),
        SAFE.replace(":15433", ":15432"),
        SAFE.replace("clinic_scheduling_test", "clinic_scheduling_dev"),
        SAFE.replace("clinic_demo", "postgres"),
        SAFE.replace("127.0.0.1", "db.example"),
        SAFE + "?host=/tmp",
        "sqlite:///local.db",
    ],
)
def test_unknown_database_targets_rejected_before_connect(raw):
    with pytest.raises(ValueError):
        validate_url(raw)


def provider_for(transport=None, **options):
    config = RunConfig()
    settings = Settings(
        _env_file=None, database_url=SAFE, openai_api_key="synthetic-test-credential"
    )
    return SmokeProvider(
        load_smoke().cases[0], settings, config, Ledger(config), transport=transport, **options
    )


def wire_response(**changes):
    return {
        "model": "gpt-6-luna",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": '{"kind":"catalog","missing_fields":[]}'}
                ],
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        **changes,
    }


def request_payload():
    return {
        "input": [],
        "store": False,
        "parallel_tool_calls": False,
        "tools": tool_definitions(),
        "text": reply_format(),
        "tool_choice": "auto",
    }


def test_dry_run_discards_real_key_and_adds_reasoning_without_mutating_payload():
    captured = []

    def transport(request):
        captured.append(request)
        return httpx.Response(200, json=wire_response())

    provider = provider_for(httpx.MockTransport(transport))
    payload = request_payload()
    before = copy.deepcopy(payload)
    provider.respond(payload)
    assert payload == before
    request = captured[0]
    assert request.headers["authorization"] == "Bearer synthetic-protocol-credential"
    assert "synthetic-test-credential" not in str(request.headers)
    body = json.loads(request.content)
    assert body["reasoning"] == {"effort": "none"}
    assert body["service_tier"] == "default" and body["model"] == "gpt-6-luna"
    assert provider.events[0]["actual_model"] == "gpt-6-luna"
    assert provider.events[0]["usage"]["total_tokens"] == 120
    assert provider.events[0]["latency_ms"] >= 0


def test_live_requires_separate_opt_in_before_transport_created(monkeypatch):
    monkeypatch.delenv("CLINIC_EVAL_ENABLE_LIVE", raising=False)
    with patch("httpx.HTTPTransport", side_effect=AssertionError("Must not construct")):
        with pytest.raises(ValueError, match="opt-in"):
            provider_for(live=True)


def test_dry_run_rejects_non_mock_transport():
    with pytest.raises(ValueError, match="MockTransport"):
        provider_for(httpx.BaseTransport())


def test_future_live_optin_branch_is_verified_only_with_mocked_transport(monkeypatch):
    monkeypatch.setenv("CLINIC_EVAL_ENABLE_LIVE", "true")
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=wire_response())

    with patch("httpx.HTTPTransport", return_value=httpx.MockTransport(handler)) as factory:
        provider = provider_for(live=True)
        provider.respond(request_payload())
    factory.assert_called_once_with(retries=0)
    assert len(captured) == 1 and provider.ledger.requests == 1
    # Synthetic credential and MockTransport only; never a real live evaluation.
    assert captured[0].headers["authorization"] == "Bearer synthetic-test-credential"


def test_dry_run_with_existing_local_environment_key_is_still_mocked():
    # Loads the ignored local key when present; never displays or sends its value.
    settings = Settings(database_url=SAFE)
    original = settings.openai_api_key
    config = RunConfig(reasoning_effort="low")
    provider = SmokeProvider(load_smoke().cases[0], settings, config, Ledger(config))
    provider.respond(request_payload())
    assert provider.events[0]["source"] == "MOCKED"
    assert provider.requests[0]["payload"]["reasoning"] == {"effort": "low"}
    assert settings.openai_api_key == original
    assert settings.enable_live_openai is False


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("timeout", "PROVIDER_TIMEOUT"),
        ("http", "PROVIDER_HTTP_ERROR"),
        ("incomplete", "PROVIDER_INCOMPLETE"),
        ("no_usage", "USAGE_UNAVAILABLE"),
        ("invalid_usage", "PROVIDER_INVALID_OR_TRANSPORT_ERROR"),
        ("overspend", "USAGE_EXCEEDS_RESERVATION"),
        ("wrong_model", "MODEL_IDENTITY_UNVERIFIED"),
        ("bad_json", "PROVIDER_INVALID_OR_TRANSPORT_ERROR"),
        ("bad_protocol", "PROVIDER_PROTOCOL_ERROR"),
    ],
)
def test_provider_failures_stop_without_retry_or_secret_error_bodies(fault, reason):
    calls = []

    def transport(request):
        calls.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("private-error-sentinel")
        if fault == "http":
            return httpx.Response(429, json={"error": "private-error-sentinel"})
        if fault == "bad_json":
            return httpx.Response(200, content=b"private-error-sentinel")
        body = wire_response()
        if fault == "incomplete":
            body["status"] = "incomplete"
        if fault == "no_usage":
            body["usage"] = None
        if fault == "invalid_usage":
            body["usage"]["input_tokens"] = "invalid"
        if fault == "overspend":
            body["usage"] = dict(input_tokens=100_000, output_tokens=20, total_tokens=100_020)
        if fault == "wrong_model":
            body["model"] = "different"
        if fault == "bad_protocol":
            body["output"][0]["role"] = "user"
        return httpx.Response(200, json=body)

    provider = provider_for(httpx.MockTransport(transport))
    for _ in range(2):
        with pytest.raises(ProviderFailure) as error:
            provider.respond(request_payload())
        assert "private-error-sentinel" not in str(error.value)
    assert len(calls) == provider.ledger.requests == 1
    assert provider.ledger.stop_reason == reason
    assert "private-error-sentinel" not in json.dumps(provider.events)


def test_report_private_redacted_non_overwriting_and_no_symlink(tmp_path):
    directory = tmp_path / "private"
    report = {"example": "private-report-sentinel", "mode": "MOCKED_DRY_RUN"}
    path = write_report(report, directory, secrets=("private-report-sentinel",))
    assert path.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    assert "private-report-sentinel" not in path.read_text()
    with pytest.raises(FileExistsError):
        write_report(report, directory)
    linked = tmp_path / "linked"
    linked.symlink_to(directory)
    with pytest.raises(ValueError):
        write_report(report, linked)


def test_cli_without_live_optin_fails_before_database_access(monkeypatch, capsys):
    monkeypatch.delenv("CLINIC_EVAL_ENABLE_LIVE", raising=False)
    monkeypatch.setattr("sys.argv", ["runner", "--live"])
    with patch("evaluations.live_runner.build_engine", side_effect=AssertionError("No DB")):
        assert main() == 1
    assert json.loads(capsys.readouterr().out)["gate"] == "FAIL"


def test_cli_repeated_report_refused_before_database_or_provider(monkeypatch, tmp_path):
    directory = tmp_path / "run"
    write_report({"mode": "MOCKED_DRY_RUN"}, directory)
    monkeypatch.setattr("sys.argv", ["runner", "--dry-run", "--output-dir", str(directory)])
    with patch("evaluations.live_runner.build_engine", side_effect=AssertionError("No DB")):
        assert main() == 1


def test_report_reservation_refuses_concurrent_and_public_destinations(tmp_path):
    directory = tmp_path / "private"
    with reserve_report(directory):
        with pytest.raises(FileExistsError):
            with reserve_report(directory):
                pytest.fail("A concurrent report run was admitted.")
    assert not (directory / ".running").exists()
    directory.chmod(0o755)
    with pytest.raises(ValueError):
        with reserve_report(directory):
            pytest.fail("A public report directory was admitted.")


@pytest.fixture
def isolated(engine):
    validate_url(engine.url.render_as_string(hide_password=False))
    with engine.connect() as conn:
        ident = conn.scalar(text("SELECT system_identifier::text FROM pg_control_system()"))
    verify_identity(engine, ident)
    with Session(engine) as db:
        seed_catalog(db)
        db.commit()
    require_fixture(engine)
    return (
        engine,
        ident,
        Settings(_env_file=None, database_url=SAFE, openai_api_key="synthetic-test-credential"),
    )


@pytest.mark.postgres
@pytest.mark.parametrize("contract", ["1.0", "1.1", "1.2"])
def test_real_postgres_dry_run_all_five_layers_and_scoped_cleanup(isolated, contract):
    engine, ident, settings = isolated
    before = database_snapshot(engine)
    result = run_smoke(engine, settings, ident, evaluation_contract=contract)
    assert result["evaluation_contract_version"] == contract
    assert result["gate"] == ("PASS" if contract == "1.2" else "FAIL")
    assert result["mode"] == "MOCKED_DRY_RUN" and result["live_openai_evals"] == "NOT RUN"
    assert result["budget"]["provider_requests"] == 11
    for case in result["cases"]:
        assert case["RAW_MODEL_VERDICT"] == case["BACKEND_VERDICT"] == "PASS"
        expected_visible = (
            "FAIL"
            if (
                (contract == "1.0" and case["case_id"] == "S2")
                or (contract != "1.2" and case["case_id"] == "S5")
            )
            else "PASS"
        )
        assert case["USER_VISIBLE_VERDICT"] == expected_visible
    assert result["cases"][2]["evidence"]["final"]["proposals"][0]["status"] == "PENDING"
    assert database_snapshot(engine) == before
    assert prepare_database(engine, ident)["system_identifier"] == ident


@pytest.mark.postgres
def test_global_request_limit_does_not_reset_between_scenarios(isolated):
    engine, ident, settings = isolated
    result = run_smoke(engine, settings, ident, RunConfig(max_requests=2))
    assert result["budget"]["provider_requests"] == 2
    assert result["cases"][0]["verdict"] == "PASS"
    assert all(c["verdict"] == "NOT RUN" for c in result["cases"][1:])
    assert result["budget"]["stop_reason"] == "REQUEST_LIMIT"
    assert result["database_unchanged_after_scoped_cleanup"]


@pytest.mark.postgres
def test_database_identity_rejected_before_mutation(isolated):
    engine, ident, settings = isolated
    before = database_snapshot(engine)
    with pytest.raises(ValueError):
        run_smoke(engine, settings, "000000")
    assert database_snapshot(engine) == before
    with Session(engine) as db:
        clinic = db.get(Clinic, CLINIC_ID)
        clinic.name = "Unexpected existing catalog"
        db.commit()
    modified = database_snapshot(engine)
    try:
        with pytest.raises(ValueError, match="no overwrite"):
            prepare_database(engine, ident)
        assert database_snapshot(engine) == modified
    finally:
        with Session(engine) as db:
            db.get(Clinic, CLINIC_ID).name = "Synthetic Demo Clinic"
            db.commit()


@pytest.mark.postgres
def test_provider_timeout_report_no_decision_not_pass(isolated):
    engine, ident, settings = isolated

    def timeout(request):
        raise httpx.ReadTimeout("private-error-sentinel")

    result = run_smoke(
        engine, settings, ident, transport_factory=lambda _: httpx.MockTransport(timeout)
    )
    first = result["cases"][0]
    assert first["RAW_MODEL_VERDICT"] == "NOT RUN" and first["BACKEND_VERDICT"] == "PASS"
    assert first["USER_VISIBLE_VERDICT"] == "FAIL"
    assert (
        result["budget"]["provider_requests"] == 1
        and result["budget"]["stop_reason"] == "PROVIDER_TIMEOUT"
    )
    assert all(c["verdict"] == "NOT RUN" for c in result["cases"][1:])
    assert result["database_unchanged_after_scoped_cleanup"]


@pytest.mark.postgres
def test_backend_correction_never_grants_raw_credit_and_fabrication_is_critical(isolated):
    engine, ident, settings = isolated
    result = run_smoke(engine, settings, ident)
    data = load_smoke()
    first = result["cases"][0]
    obs = copy.deepcopy(first["evidence"])
    obs["raw_calls"] = []
    corrected = grade_smoke(data.cases[0], obs, data, [], complete=True)
    assert corrected["RAW_MODEL_VERDICT"] == "FAIL"
    assert corrected["BACKEND_VERDICT"] == corrected["USER_VISIBLE_VERDICT"] == "PASS"
    obs["raw_plans"][0]["value"] = "Your appointment is confirmed."
    fabricated = grade_smoke(data.cases[0], obs, data, [], complete=True)
    assert fabricated["critical_failure"] and fabricated["verdict"] == "FAIL"


@pytest.mark.postgres
def test_nonempty_runtime_preserved(isolated):
    engine, ident, settings = isolated
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    owner = uuid4()
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(
            ChatSession(
                id=owner, token_hash="a" * 64, created_at=now, expires_at=now + timedelta(hours=24)
            )
        )
        db.commit()
    before = database_snapshot(engine)
    try:
        with pytest.raises(ValueError, match="preserved"):
            run_smoke(engine, settings, ident)
        assert database_snapshot(engine) == before
    finally:
        with Session(engine) as db:
            db.delete(db.get(ChatSession, owner))
            db.commit()


@pytest.mark.parametrize("fault", ["store", "parallel", "tools", "text"])
def test_reviewed_request_contract_rejected_before_dispatch(fault):
    payload = request_payload()
    if fault == "store":
        payload["store"] = True
    if fault == "parallel":
        payload["parallel_tool_calls"] = True
    if fault == "tools":
        payload["tools"].append({"type": "web_search"})
    if fault == "text":
        payload["text"] = {}
    provider = provider_for()
    with pytest.raises(ProviderFailure):
        provider.respond(payload)
    assert provider.ledger.requests == 0
    assert provider.ledger.stop_reason == "REQUEST_CONTRACT"


@pytest.mark.postgres
@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"max_total_tokens": 1}, "TOKEN_LIMIT"),
        ({"max_estimated_usd": "0.0000001"}, "ESTIMATED_SPEND_LIMIT"),
    ],
)
def test_budget_refusal_report_has_zero_provider_calls(isolated, changes, reason):
    engine, ident, settings = isolated
    result = run_smoke(engine, settings, ident, RunConfig(**changes))
    assert result["budget"]["provider_requests"] == 0
    assert result["budget"]["stop_reason"] == reason
    assert result["cases"][0]["RAW_MODEL_VERDICT"] == "NOT RUN"
    assert result["cases"][0]["BACKEND_VERDICT"] == "PASS"
    assert all(c["verdict"] == "NOT RUN" for c in result["cases"][1:])
    assert result["database_unchanged_after_scoped_cleanup"]


@pytest.mark.postgres
def test_incomplete_provider_and_fabricated_confirmation_reporting(isolated):
    engine, ident, settings = isolated
    for fabricated in (False, True):
        body = wire_response(status="completed" if fabricated else "incomplete")
        if fabricated:
            body["output"][0]["content"][0]["text"] = "Your appointment is confirmed."
        result = run_smoke(
            engine,
            settings,
            ident,
            transport_factory=lambda _: httpx.MockTransport(
                lambda request: httpx.Response(200, json=body)
            ),
        )
        first = result["cases"][0]
        assert first["verdict"] == first["RAW_MODEL_VERDICT"] == "FAIL"
        assert first["BACKEND_VERDICT"] == "PASS"
        assert first["critical_failure"] is fabricated
        assert first["provider_execution"] == "INCOMPLETE"
        assert all(c["verdict"] == "NOT RUN" for c in result["cases"][1:])
        assert result["database_unchanged_after_scoped_cleanup"]


@pytest.mark.postgres
def test_failure_after_proposal_is_not_booking_or_success(isolated):
    engine, ident, settings = isolated

    def factory(case):
        if case.id != "S3":
            return None
        steps = iter(case.expected_tool_calls)
        count = 0

        def transport(request):
            nonlocal count
            count += 1
            step = next(steps, None)
            if step is None:
                return httpx.Response(503, json={"error": "private-error-sentinel"})
            return httpx.Response(
                200,
                json=wire_response(
                    output=[
                        {
                            "type": "function_call",
                            "call_id": f"partial_{count}",
                            "name": step.name,
                            "arguments": json.dumps(step.arguments),
                        }
                    ]
                ),
            )

        return httpx.MockTransport(transport)

    result = run_smoke(engine, settings, ident, transport_factory=factory)
    case = result["cases"][2]
    assert case["RAW_MODEL_VERDICT"] == case["USER_VISIBLE_VERDICT"] == "FAIL"
    assert case["BACKEND_VERDICT"] == "PASS"
    final = case["evidence"]["final"]
    assert len(final["proposals"]) == 1 and final["proposals"][0]["status"] == "PENDING"
    assert final["appointments"] == []
    assert result["database_unchanged_after_scoped_cleanup"]


@pytest.mark.postgres
def test_new_grader_negative_controls_cover_required_metrics(isolated):
    engine, ident, settings = isolated
    report = run_smoke(engine, settings, ident)
    dataset = load_smoke()
    controls = [
        (0, "tool_selection", "raw_model"),
        (1, "tool_arguments", "raw_model"),
        (2, "policy_compliance", "raw_model"),
        (3, "clarification_behavior", "raw_model"),
        (4, "booking_authorization", "raw_model"),
        (1, "response_grounding", "user_visible"),
        (2, "database_integrity", "backend"),
        (2, "immutable_tuple", "backend"),
    ]
    for index, metric, layer in controls:
        obs = copy.deepcopy(report["cases"][index]["evidence"])
        if metric == "tool_selection":
            obs["raw_calls"] = []
        elif metric == "tool_arguments":
            obs["raw_calls"][-1]["arguments"]["practitioner_id"] = dataset.catalog["practitioners"][
                1
            ]
        elif metric == "policy_compliance":
            obs["raw_calls"][-1]["arguments"]["local_time"] = "09:15"
        elif metric == "clarification_behavior":
            obs["raw_plans"][0]["value"]["missing_fields"] = []
        elif metric == "booking_authorization":
            obs["raw_calls"] = [{"session": "A", "name": "confirm_booking", "arguments": {}}]
        elif metric == "response_grounding":
            obs["responses"][0]["body"]["assistant_message"] += " Your insurance is covered."
        elif metric == "immutable_tuple":
            obs["final"]["proposals"][0]["practitioner_id"] = dataset.catalog["practitioners"][1]
        else:
            obs["final"]["proposals"] = []
        result = grade_smoke(dataset.cases[index], obs, dataset, [], complete=True)
        assert result["verdict"] == "FAIL"
        key = "database_integrity" if metric == "immutable_tuple" else metric
        assert result["layers"][layer]["checks"][key]["verdict"] == "FAIL", metric
