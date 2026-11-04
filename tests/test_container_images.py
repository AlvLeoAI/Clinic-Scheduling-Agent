"""Static checks on the container build inputs; no Docker needed."""

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
# `name==version`, optionally followed by an environment marker and a line continuation.
PIN = re.compile(r"^([a-z0-9][a-z0-9._-]*)==([^\s;\\]+)", re.MULTILINE)
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


LOCKS = [
    "requirements-foundation.lock",
    "requirements-runtime.lock",
    "ui/requirements.lock",
    "infra/tools/checkov.lock",
]
# Every command that installs one of the locks, and the lock it installs.
INSTALLS = {
    "Dockerfile": "requirements-runtime.lock",
    "ui/Dockerfile": "requirements.lock",
    "Makefile": "requirements-foundation.lock",
    ".github/workflows/ci.yml": "requirements-foundation.lock",
    ".github/workflows/infra.yml": "infra/tools/checkov.lock",
    "scripts/reproduce_local.py": "requirements-foundation.lock",
}


@pytest.mark.parametrize("lock", LOCKS)
def test_every_pin_in_a_lock_carries_a_hash(lock):
    # A requirement is a `name==version` line plus its continuation lines.
    entries = re.split(r"\n(?=[a-z0-9])", (ROOT / lock).read_text().split("\n", 2)[2])
    assert entries and len(entries) == len(pins(lock))
    for entry in entries:
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", entry), entry.splitlines()[0]


@pytest.mark.parametrize(("path", "lock"), INSTALLS.items())
def test_every_lock_install_requires_hashes(path, lock):
    text = (ROOT / path).read_text()
    lines = [line for line in text.splitlines() if lock in line and "install" in line]
    if path == "scripts/reproduce_local.py":  # uv pip sync, one argument per line
        start = text.index('"sync"')
        lines = [text[start : text.index(f'"{lock}"', start)]]
    assert lines, f"{path} no longer installs {lock}"
    assert all("--require-hashes" in line for line in lines), lines


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


def test_api_image_ships_the_rds_ca_bundle_verified_by_checksum():
    text = (ROOT / "Dockerfile").read_text()
    url = re.search(r"^ARG RDS_CA_URL=(\S+)$", text, re.MULTILINE)
    digest = re.search(r"^ARG RDS_CA_SHA256=([0-9a-f]{64})$", text, re.MULTILINE)
    assert url and url.group(1).startswith("https://truststore.pki.rds.amazonaws.com/")
    assert digest and "hexdigest() == sys.argv[2]" in text
    assert "/etc/ssl/certs/rds-ca-bundle.pem" in text


def test_ui_image_keeps_websockets_alive_behind_a_proxy():
    text = (ROOT / "ui/Dockerfile").read_text()
    ping = re.search(r"STREAMLIT_SERVER_WEBSOCKET_PING_INTERVAL=(\d+)", text)
    assert ping and 0 < int(ping.group(1)) < 300


def test_ui_image_copies_every_ui_module_the_page_imports():
    copied = re.search(r"^COPY (.+) \./ui/$", (ROOT / "ui/Dockerfile").read_text(), re.M)
    allowed = (ROOT / "ui/.dockerignore").read_text().split()
    imported = {
        f"{name}.py"
        for path in (ROOT / "ui").glob("*.py")
        for name in re.findall(r"^from ui\.(\w+) import", path.read_text(), re.M)
    }
    assert copied and imported
    for module in imported | {"app.py"}:
        assert module in copied.group(1).split(), module
        assert f"!{module}" in allowed, module


def test_api_image_carries_every_script_a_task_definition_runs():
    copied = re.search(r"^COPY (scripts/.+) \./scripts/$", (ROOT / "Dockerfile").read_text(), re.M)
    allowed = (ROOT / ".dockerignore").read_text().split()
    run = set(re.findall(r'"scripts\.(\w+)"', (ROOT / "infra/terraform/app/ecs.tf").read_text()))
    run |= set(
        re.findall(r"python -m scripts\.(\w+)", (ROOT / "infra/terraform/app/ecs.tf").read_text())
    )
    assert copied and {"smoke_deploy", "purge_chat", "db_roles", "seed"} <= run
    for name in run:
        assert f"scripts/{name}.py" in copied.group(1).split(), name
        assert f"!scripts/{name}.py" in allowed, name
