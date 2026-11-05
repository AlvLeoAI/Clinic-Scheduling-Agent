"""Deploy workflow ordering and the task-definition helper, without AWS.

The workflow is read as text (PyYAML is not a test dependency); the helper runs
against a fake `aws` on PATH.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy.yml"
REGISTER = ROOT / "infra/tools/register_task_definition.sh"
RUN_ONE_OFF = ROOT / "infra/tools/run_one_off_task.sh"


def release_steps() -> list[tuple[str, str]]:
    job = WORKFLOW.read_text().split("\n  release:\n", 1)[1]
    steps = []
    for chunk in job.split("\n      - ")[1:]:
        name = re.match(r"(?:name: (.+)|uses: (\S+))", chunk)
        steps.append((name.group(1) or name.group(2), chunk))
    return steps


def index(steps, fragment: str) -> int:
    matches = [i for i, (name, _) in enumerate(steps) if fragment in name]
    assert len(matches) == 1, (fragment, [name for name, _ in steps])
    return matches[0]


def test_purge_is_registered_only_after_migration_stable_services_and_smoke():
    steps = release_steps()
    register = index(steps, "Register the release's task definitions")
    migrate = index(steps, "Run migrations")
    stable = index(steps, "Update services and wait until stable")
    smoke = index(steps, "Post-deploy smoke")
    purge = index(steps, "Register the purge revision")
    assert register < migrate < stable < smoke < purge == len(steps) - 1

    loop = re.search(r"for key in ([a-z ]+); do", steps[register][1])
    assert loop and loop.group(1).split() == ["api", "ui", "migrate"]
    # Nothing before the last step registers or names the purge family.
    for name, body in steps[:purge]:
        assert "families.purge" not in body and "register-task-definition" not in body, name
    stable_body = steps[stable][1]
    assert "services-stable" in stable_body and "rolled back" in stable_body
    assert "run_one_off_task.sh" in steps[migrate][1] and "TASKDEF_MIGRATE" in steps[migrate][1]
    assert "families.smoke" in steps[smoke][1] and "run_one_off_task.sh" in steps[smoke][1]
    assert "families.purge" in steps[purge][1]


def test_the_workflow_never_prints_the_deploy_configuration_or_the_url():
    text = WORKFLOW.read_text()
    # No step reads the URL out of the configuration, so none can echo it.
    assert not re.search(r"\.url\b", text)
    assert "cloudfront.net" not in text and "set -x" not in text
    # The configuration file is read only field by field or with its output discarded.
    config = r'"?\$(?:RUNNER_TEMP/deploy\.json|cfg)"?'
    for line in text.splitlines():
        printed = re.search(rf"\b(?:cat|jq\s+(?:-\w+\s+)*['\"]?\.['\"]?)\s+{config}", line)
        assert not printed or ">/dev/null" in line or "> " in line, line
        assert not re.search(rf"\becho\b.*{config}", line), line


def fake_aws(tmp_path: Path, script: str) -> dict[str, str]:
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")
    fake = tmp_path / "aws"
    fake.write_text('#!/usr/bin/env bash\necho "$*" >> "$FAKE_DIR/calls"\n' + script)
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_DIR": str(tmp_path)}


def test_register_helper_changes_only_the_image_and_keeps_tags(tmp_path):
    current = {
        "taskDefinition": {
            "family": "clinic-purge",
            "taskDefinitionArn": "arn:aws:ecs:us-east-2:1:task-definition/clinic-purge:4",
            "revision": 4,
            "status": "ACTIVE",
            "registeredAt": "2030-01-01T00:00:00Z",
            "containerDefinitions": [{"name": "purge", "image": "repo:old", "cpu": 0}],
            "cpu": "256",
        },
        "tags": [{"key": "Project", "value": "clinic-scheduling-agent"}],
    }
    (tmp_path / "current.json").write_text(json.dumps(current))
    env = fake_aws(
        tmp_path,
        'case "$2" in\n'
        '  describe-task-definition) cat "$FAKE_DIR/current.json" ;;\n'
        '  register-task-definition) cp "${4#file://}" "$FAKE_DIR/registered.json"\n'
        "    echo arn:aws:ecs:us-east-2:1:task-definition/clinic-purge:5 ;;\n"
        "esac\n",
    )

    result = subprocess.run(
        [str(REGISTER), "clinic-purge", "repo:new"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().endswith("clinic-purge:5")
    registered = json.loads((tmp_path / "registered.json").read_text())
    assert registered["containerDefinitions"] == [{"name": "purge", "image": "repo:new", "cpu": 0}]
    assert registered["tags"] == current["tags"] and registered["cpu"] == "256"
    for dropped in ("taskDefinitionArn", "revision", "status", "registeredAt"):
        assert dropped not in registered, dropped


@pytest.mark.parametrize(
    ("task_arn", "exit_code", "succeeds"),
    [
        ("arn:aws:ecs:us-east-2:1:task/clinic-scheduling-agent/abc123", 0, True),
        ("arn:aws:ecs:us-east-2:1:task/clinic-scheduling-agent/abc123", 1, False),
        ("arn:aws:ecs:us-east-2:1:task/clinic-scheduling-agent/abc123", None, False),
        ("None", 0, False),
    ],
)
def test_one_off_helper_fails_unless_the_task_ran_and_exited_zero(
    tmp_path, task_arn, exit_code, succeeds
):
    (tmp_path / "deploy.json").write_text(
        json.dumps({"cluster": "clinic-scheduling-agent", "subnets": ["subnet-1", "subnet-2"]})
    )
    result = {"stopped": "Essential container in task exited", "exit": exit_code}
    env = fake_aws(
        tmp_path,
        'case "$2" in\n'
        f"  run-task) echo {task_arn} ;;\n"
        "  wait) ;;\n"
        f"  describe-tasks) echo '{json.dumps(result)}' ;;\n"
        "  get-log-events) echo 'PASS readiness' ;;\n"
        "esac\n",
    )
    done = subprocess.run(
        [str(RUN_ONE_OFF), str(tmp_path / "deploy.json"), "arn:td", "sg-1", "/logs/smoke", "smoke"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert (done.returncode == 0) is succeeds, done.stderr
    calls = (tmp_path / "calls").read_text()
    assert '"securityGroups":["sg-1"]' in calls and '"subnets":["subnet-1","subnet-2"]' in calls
    if task_arn != "None":
        assert "--log-stream-name smoke/smoke/abc123" in calls
