"""Each versioned scenario runs through real PostgreSQL, HTTP and the mocked REST adapter."""

import pytest

from evaluations.runner import load_dataset, run_case

pytestmark = [pytest.mark.postgres, pytest.mark.api, pytest.mark.agent_offline]
DATA = load_dataset()


@pytest.mark.parametrize("case", DATA.cases, ids=lambda case: case.id)
def test_versioned_offline_scenario(engine, case):
    result = run_case(case, DATA, engine)
    assert result["verdict"] == "PASS", result["layers"]
    assert result["layers"]["raw_model"]["verdict"] == case.expected_raw_verdict
    assert (
        result["layers"]["backend"]["verdict"]
        == result["layers"]["user_visible"]["verdict"]
        == "PASS"
    )
    assert result["evidence"]["actual_usage"] is None
