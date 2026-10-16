"""Isolated working-tree copy, fresh venv and project-owned PostgreSQL; never a clone claim."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def reproduce():
    results, project = [], "clinic-m6-repro-" + uuid4().hex[:10]
    with tempfile.TemporaryDirectory(prefix="clinic-m6-repro-") as directory:
        target = Path(directory)
        for name in (
            "app",
            "cli",
            "scripts",
            "tests",
            "evaluations",
            "alembic",
            "docker",
            "docs",
            ".github",
        ):
            shutil.copytree(
                ROOT / name,
                target / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "raw", ".local"),
            )
        for name in (
            "README.md",
            "SYSTEM_DESIGN.md",
            "TESTING.md",
            ".env.example",
            ".gitignore",
            "compose.yaml",
            "alembic.ini",
            "pyproject.toml",
            "requirements-foundation.lock",
        ):
            shutil.copy2(ROOT / name, target / name)
        (target / "data").mkdir()
        shutil.copy2(ROOT / "data/appointments.json", target / "data/appointments.json")
        source_files = {
            str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ("app", "cli", "scripts", "tests", "evaluations")
            for p in (target / folder).rglob("*")
            if p.is_file()
        }
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        password = secrets.token_hex(24)
        envfile = target / ".env"
        envfile.write_text(
            f"POSTGRES_PASSWORD={password}\nPOSTGRES_PORT={port}\nDATABASE_URL=postgresql+psycopg://clinic_demo:{password}@127.0.0.1:{port}/clinic_scheduling_dev\nTEST_DATABASE_URL=postgresql+psycopg://clinic_demo:{password}@127.0.0.1:{port}/clinic_scheduling_test\nENABLE_LIVE_OPENAI=false\nOPENAI_API_KEY=\nOPENAI_MODEL=\n"
        )
        envfile.chmod(0o600)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("POSTGRES_", "OPENAI_", "ELEVENLABS_"))
            and k
            not in {
                "DATABASE_URL",
                "TEST_DATABASE_URL",
                "COMPOSE_PROJECT_NAME",
                "PYTHONPATH",
                "VIRTUAL_ENV",
                "PYTEST_ADDOPTS",
            }
        }
        env["ENABLE_LIVE_OPENAI"] = "false"
        env["CLINIC_BOOKING_EVIDENCE_FILE"] = "M6_booking_regression_cases.json"
        env["CLINIC_AGENT_EVIDENCE_FILE"] = "M6_m4_regression_cases.json"
        compose = ["docker", "compose", "-p", project]
        created, success = False, False

        def run(command, timeout=60):
            print(json.dumps({"phase": "running", "command": command}), flush=True)
            process = subprocess.run(
                command, cwd=target, env=env, capture_output=True, text=True, timeout=timeout
            )
            output = (process.stdout + process.stderr).replace(
                password, "<redacted-local-password>"
            )
            results.append({"command": command, "exit_code": process.returncode, "output": output})
            if process.returncode:
                raise RuntimeError("An isolated reproduction command failed.")
            return output

        try:
            assert not subprocess.check_output(
                compose + ["ps", "-a", "-q"], cwd=target, env=env
            ).strip()
            run(["uv", "venv", "--python", sys.executable, ".venv"])
            run(
                [
                    "uv",
                    "pip",
                    "sync",
                    "--offline",
                    "--python",
                    ".venv/bin/python",
                    "requirements-foundation.lock",
                ]
            )
            created = True
            run(compose + ["up", "-d", "--wait", "--pull", "never", "postgres"])
            run([".venv/bin/alembic", "upgrade", "head"])
            run([".venv/bin/python", "-m", "scripts.seed"])
            run([".venv/bin/python", "-m", "scripts.seed"])
            run([".venv/bin/alembic", "check"])
            run([".venv/bin/alembic", "current"])
            run(
                [
                    ".venv/bin/ruff",
                    "check",
                    "app",
                    "cli",
                    "scripts",
                    "alembic",
                    "tests",
                    "evaluations",
                ]
            )
            run(
                [
                    ".venv/bin/ruff",
                    "format",
                    "--check",
                    "app",
                    "cli",
                    "scripts",
                    "alembic",
                    "tests",
                    "evaluations",
                ]
            )
            run([".venv/bin/pytest", "-q"])
            run(
                [
                    ".venv/bin/python",
                    "-m",
                    "evaluations.runner",
                    "--output-dir",
                    "test-results/repro/evals",
                ]
            )
            run([".venv/bin/python", "scripts/demo_concurrency.py", "--synthetic-only"])
            run([".venv/bin/python", "-m", "cli", "--synthetic-only", "--scripted"])
            run([".venv/bin/python", "-m", "scripts.check_synthetic"])
            run([".venv/bin/python", "-m", "scripts.check_docs"])
            success = True
        except Exception:
            success = False
        finally:
            if created:
                # Only this fresh random project and newly created, exactly prefixed volumes.
                volumes = (
                    subprocess.check_output(
                        [
                            "docker",
                            "volume",
                            "ls",
                            "-q",
                            "--filter",
                            "label=com.docker.compose.project=" + project,
                        ],
                        env=env,
                    )
                    .decode()
                    .splitlines()
                )
                if not all(name.startswith(project + "_") for name in volumes):
                    raise RuntimeError("Resource ownership check failed; teardown refused.")
                run(compose + ["down", "--volumes", "--remove-orphans"])
                assert not subprocess.check_output(
                    [
                        "docker",
                        "volume",
                        "ls",
                        "-q",
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    ],
                    env=env,
                ).strip()
        return {
            "status": "PASS" if success else "FAIL",
            "kind": "isolated working-tree copy; NOT a fresh clone",
            "fresh_clone": "NOT RUN",
            "project": project,
            "loopback_postgres_port": port,
            "fresh_private_env_mode": "0600",
            "fresh_virtual_environment": True,
            "source_runtime_sha256": hashlib.sha256(
                json.dumps(source_files, sort_keys=True).encode()
            ).hexdigest(),
            "source_file_hashes": source_files,
            "commands": results,
            "new_project_resources_removed": created,
            "live_calls": 0,
            "legacy_source_audio_archives_copied": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-only", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if not args.synthetic_only:
        parser.error("--synthetic-only is required before any local resource creation.")
    result = reproduce()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "kind": result["kind"],
                "fresh_clone": "NOT RUN",
                "new_project_resources_removed": result["new_project_resources_removed"],
            }
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
