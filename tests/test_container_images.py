"""Static checks on the container build inputs; no Docker needed."""

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"^([a-z0-9][a-z0-9._-]*)==(\S+)$", re.MULTILINE)
DIGEST = re.compile(r"python:3\.12-slim@sha256:[0-9a-f]{64}")


def pins(name):
    return dict(PIN.findall((ROOT / name).read_text()))


def test_runtime_lock_matches_foundation_lock_without_test_tools():
    runtime, foundation = pins("requirements-runtime.lock"), pins("requirements-foundation.lock")
    assert runtime and all(foundation.get(name) == version for name, version in runtime.items())
    assert not {"pytest", "ruff", "pluggy", "iniconfig"} & set(runtime)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = {re.split(r"[\[<>=!~ ]", spec)[0].lower() for spec in project["dependencies"]}
    assert declared <= set(runtime)


@pytest.mark.parametrize("dockerfile", ["Dockerfile", "ui/Dockerfile"])
def test_images_are_pinned_non_root_and_env_free(dockerfile):
    path = ROOT / dockerfile
    if not path.exists():
        pytest.skip(f"{dockerfile} not present")
    text = path.read_text()
    assert DIGEST.search(text)
    assert re.search(r"^USER 10001$", text, re.MULTILINE)
    assert "HEALTHCHECK" in text
    assert not re.search(r"^COPY .*\.env", text, re.MULTILINE)
    # Migrations and seeding are one-off commands, never part of the start command.
    starts = re.findall(r"^(?:CMD|ENTRYPOINT) .*$", text, re.MULTILINE)
    assert starts and not any(re.search(r"alembic|seed", line) for line in starts)


def test_api_build_context_excludes_local_state():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert ignore[0].startswith("#") and "*" in ignore and "**/.env*" in ignore
    allowed = [line[1:] for line in ignore if line.startswith("!")]
    for private in [".env", ".venv/", ".git/", "tests/", "docs/", "test-results/"]:
        assert not any(private.startswith(entry) for entry in allowed), private
