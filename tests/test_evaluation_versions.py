"""Explicit contract dispatch and immutable v1 behavior, including actual runner paths."""

import copy
import hashlib
import json
from unittest.mock import patch

import httpx
import pytest

from evaluations import graders, live_runner, runner
from evaluations.scoring import contract_metadata, select_contract
from tests import test_live_runner as live_helpers

isolated = live_helpers.isolated
pytestmark = pytest.mark.agent_offline


def test_historical_scorer_fingerprint_is_unchanged():
    assert contract_metadata("1.0", smoke=True)["scorer_sha256"] == (
        "e56a5caba1349fecbdc61d9a0fca49ffd816d27505b1303d8847ceb3cad5f2be"
    )
    legacy_sources = ["live_graders.py", "graders.py", "oracle.py"]
    assert (
        hashlib.sha256(
            b"".join((runner.ROOT / "evaluations" / name).read_bytes() for name in legacy_sources)
        ).hexdigest()
        == contract_metadata("1.0", smoke=True)["scorer_sha256"]
    )
    current = contract_metadata("1.1", smoke=True)
    assert current["scorer_version"] == "r2-layered-1.1.0"
    assert current["scorer_sha256"] != contract_metadata("1.0", smoke=True)["scorer_sha256"]
    assert set(current["scorer_sources"]) == {
        "graders.py",
        "live_graders.py",
        "oracle.py",
        "graders_v1_1.py",
        "live_graders_v1_1.py",
        "scoring.py",
    }


@pytest.mark.parametrize("version", [None, "", "1", "v1.1", "1.2", "latest", False])
def test_unknown_contract_fails_before_case_database_or_provider(version):
    with pytest.raises(ValueError):
        select_contract(version)
    with patch.object(runner, "CaseRun", side_effect=AssertionError("No case effects")):
        with pytest.raises(ValueError):
            runner.run_case(None, None, object(), evaluation_contract=version)
    with patch.object(live_runner, "verify_identity", side_effect=AssertionError("No DB")):
        with pytest.raises(ValueError):
            live_runner.run_smoke(object(), object(), None, evaluation_contract=version)


@pytest.mark.parametrize("module", [runner, live_runner])
def test_unknown_cli_version_fails_before_any_runtime_preparation(module, monkeypatch):
    monkeypatch.setattr("sys.argv", ["runner", "--evaluation-contract", "latest"])
    with patch.object(module, "Settings", side_effect=AssertionError("No settings")):
        with pytest.raises(SystemExit) as result:
            module.main()
    assert result.value.code == 2


@pytest.mark.postgres
@pytest.mark.parametrize(
    "case_id", ["02_availability_30", "03_availability_60", "25_isolation_restart"]
)
def test_actual_current_application_has_explicit_legacy_and_v11_results(engine, case_id):
    data = runner.load_dataset()
    case = next(c for c in data.cases if c.id == case_id)
    result = runner.run_case(case, data, engine, evaluation_contract="1.1")
    assert result["verdict"] == "PASS"
    obs = result["evidence"]
    original = copy.deepcopy(obs)
    historical_contract = graders.grade(case, obs, data.catalog, data.clock)
    assert historical_contract["layers"]["raw_model"]["verdict"] == "PASS"
    assert historical_contract["layers"]["backend"]["verdict"] == "PASS"
    assert historical_contract["layers"]["user_visible"]["verdict"] == "FAIL"
    assert obs == original


@pytest.mark.postgres
def test_v11_runner_retains_raw_semantic_failure_through_actual_mocked_transport(isolated):
    engine, ident, settings = isolated
    bad_plan = {"kind": "confirmation_required", "missing_fields": ["local_date"]}

    def transport(request):
        payload = json.loads(request.content)
        assert payload["store"] is False and payload["parallel_tool_calls"] is False
        return httpx.Response(
            200,
            json={
                "model": "gpt-6-luna",
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130},
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": json.dumps(bad_plan)}],
                    }
                ],
            },
        )

    result = live_runner.run_smoke(
        engine,
        settings,
        ident,
        evaluation_contract="1.1",
        scenario="S5",
        transport_factory=lambda _: httpx.MockTransport(transport),
    )
    assert result["scorer_version"] == "r2-layered-1.1.0"
    assert result["live_openai_evals"] == "NOT RUN"
    assert result["budget"]["provider_requests"] == 1
    case = result["cases"][0]
    assert case["evidence"]["raw_plans"][0]["value"] == bad_plan
    assert case["RAW_MODEL_VERDICT"] == case["USER_VISIBLE_VERDICT"] == "FAIL"
    assert case["BACKEND_VERDICT"] == "PASS"
    assert case["layers"]["raw_model"]["checks"]["reply_semantics"]["verdict"] == "FAIL"
    assert case["evidence"]["responses"][0]["status"] == 503
    assert case["evidence"]["final"]["appointments"] == []
    assert case["evidence"]["final"]["proposals"] == []
    assert case["evidence"]["explicit_confirmations"] == []
    assert result["database_unchanged_after_scoped_cleanup"]
