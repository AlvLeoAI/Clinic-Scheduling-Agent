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


def test_purge_is_registered_only_after_migration_and_stable_services():
    steps = release_steps()
    register = index(steps, "Register the release's task definitions")
    migrate = index(steps, "Run migrations")
    stable = index(steps, "Update services and wait until stable")
    purge = index(steps, "Register the purge revision")
    assert register < migrate < stable < purge == len(steps) - 1

    loop = re.search(r"for key in ([a-z ]+); do", steps[register][1])
    assert loop and loop.group(1).split() == ["api", "ui", "migrate"]
    # Nothing before the last step registers or names the purge family.
    for name, body in steps[:purge]:
        assert "families.purge" not in body and "register-task-definition" not in body, name
    stable_body = steps[stable][1]
    assert "services-stable" in stable_body and "rolled back" in stable_body
    assert 'test "$(jq -r .exit "$RUNNER_TEMP/migrate.json")" = 0' in steps[migrate][1]
    assert "families.purge" in steps[purge][1]


def test_register_helper_changes_only_the_image_and_keeps_tags(tmp_path):
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")
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
    fake = tmp_path / "aws"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$FAKE_DIR/calls"\n'
        'case "$2" in\n'
        '  describe-task-definition) cat "$FAKE_DIR/current.json" ;;\n'
        '  register-task-definition) cp "${4#file://}" "$FAKE_DIR/registered.json"\n'
        "    echo arn:aws:ecs:us-east-2:1:task-definition/clinic-purge:5 ;;\n"
        "esac\n"
    )
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_DIR": str(tmp_path)}

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
