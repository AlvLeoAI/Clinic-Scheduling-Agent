"""R2 smoke runner. Default dry-run always mocks HTTP, even with a local API key."""

import argparse
import hashlib
import json
import logging
import os
import re
from contextlib import ExitStack, contextmanager
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AppointmentType, Clinic, Practitioner
from app.db.session import build_engine
from evaluations.live_contracts import PRICING, Ledger, RunConfig, SmokeDataset
from evaluations.live_database import (
    database_snapshot,
    prepare_database,
    require_fixture,
    validate_url,
    verify_identity,
)
from evaluations.live_provider import SmokeProvider
from evaluations.runner import ROOT, CaseRun
from evaluations.scoring import CONTRACT_VERSIONS, contract_metadata, select_contract

DATASET = ROOT / "evaluations/datasets/live_smoke_v1.json"


def load_smoke():
    return SmokeDataset.model_validate_json(DATASET.read_text())


def select_scenarios(dataset, scenario=None, *, live=False):
    """Select from the complete validated dataset before any case or DB effects."""
    by_id = {case.id: case for case in dataset.cases}
    if len(by_id) != len(dataset.cases):
        raise ValueError("Scenario identifiers must be unique.")
    if scenario is None:
        if live:
            raise ValueError("Live evaluation requires one explicit scenario selection.")
        return list(dataset.cases)
    if not isinstance(scenario, str) or scenario not in by_id:
        raise ValueError("Select one exact scenario identifier from the versioned dataset.")
    return [by_id[scenario]]


class SmokeRun(CaseRun):
    def setup(self, client):
        # Catalog is verified before the run, never upserted over existing state.
        with Session(self.engine) as db:
            self.catalog_truth = {
                "timezone": db.scalar(select(Clinic.timezone).order_by(Clinic.id).limit(1)),
                "practitioners": [
                    {"id": str(r.id), "name": r.display_name}
                    for r in db.scalars(select(Practitioner).order_by(Practitioner.id))
                ],
                "types": [
                    {"id": str(r.id), "code": r.code, "duration": r.duration_minutes}
                    for r in db.scalars(select(AppointmentType).order_by(AppointmentType.id))
                ],
            }
        response = client.post("/api/v1/sessions", json={})
        if response.status_code != 201:
            raise ValueError("Synthetic session could not be established.")
        self.ids["A"] = response.json()["session_id"]
        self.bearers["A"] = {"Authorization": "Bearer " + response.json()["session_token"]}


def not_run(case, reason):
    return {
        "case_id": case.id,
        "verdict": "NOT RUN",
        "RAW_MODEL_VERDICT": "NOT RUN",
        "BACKEND_VERDICT": "NOT RUN",
        "USER_VISIBLE_VERDICT": "NOT RUN",
        "critical_failure": False,
        "reason": reason,
        "provider_events": [],
    }


def run_smoke(
    engine,
    settings,
    expected_system_id,
    config=None,
    *,
    live=False,
    scenario=None,
    transport_factory=None,
    evaluation_contract="1.0",
):
    _, grade_smoke = select_contract(evaluation_contract)
    metadata = contract_metadata(evaluation_contract, smoke=True)
    dataset = load_smoke()
    selected = select_scenarios(dataset, scenario, live=live)
    config = config or RunConfig()
    identity = verify_identity(engine, expected_system_id)
    require_fixture(engine)
    before = database_snapshot(engine)
    if live and (os.environ.get("CLINIC_EVAL_ENABLE_LIVE") != "true" or transport_factory):
        raise ValueError("Live execution requires explicit opt-in; no test transport in live mode.")
    ledger, cases = Ledger(config), []
    for case in selected:
        if ledger.stop_reason:
            cases.append(not_run(case, ledger.stop_reason))
            continue
        verify_identity(engine, expected_system_id)
        require_fixture(engine)
        run = SmokeRun(case, dataset, engine)
        run.settings = run.settings.model_copy(
            update={
                "openai_model": config.model,
                "provider_max_output_tokens": config.max_output_tokens,
                "openai_api_key": settings.openai_api_key,
            }
        )
        provider = SmokeProvider(
            case,
            run.settings,
            config,
            ledger,
            live=live,
            transport=transport_factory(case) if transport_factory else None,
        )
        run.provider = provider
        result = None
        try:
            with run.client() as client:
                run.setup(client)
                initial = run.snapshot()
                run.exercise(client)
                obs = run.observation(initial)
            complete = bool(run.responses) and run.responses[-1]["status"] == 200
            complete &= ledger.stop_reason is None
            result = grade_smoke(case, obs, dataset, provider.events, complete=complete)
        except Exception:
            # No exception/body/DSN in reports. Infrastructure failures never pass.
            ledger.stop("RUNNER_FAILURE")
            result = not_run(case, "RUNNER_FAILURE")
            result.update(
                verdict="FAIL",
                BACKEND_VERDICT="FAIL",
                USER_VISIBLE_VERDICT="FAIL",
                RAW_MODEL_VERDICT="FAIL" if provider.raw_calls or provider.raw_plans else "NOT RUN",
                provider_execution="INCOMPLETE",
                provider_events=provider.events,
                partial_raw_calls=provider.raw_calls,
                partial_raw_plans=provider.raw_plans,
            )
        finally:
            # Recheck identity before scoped deletion. Never reset/clean other sessions.
            verify_identity(engine, expected_system_id)
            run.cleanup()
            provider.close()
        unchanged = database_snapshot(engine) == before
        result["cleanup_integrity"] = "PASS" if unchanged else "FAIL"
        if not unchanged:
            result.update(verdict="FAIL", BACKEND_VERDICT="FAIL")
            ledger.stop("DATABASE_INTEGRITY")
        cases.append(result)
        if result.get("critical_failure"):
            ledger.stop("CRITICAL_MODEL_FAILURE")
        if result.get("provider_execution") == "INCOMPLETE":
            ledger.stop("INCOMPLETE_TURN")
        if ledger.requests >= config.max_requests:
            ledger.stop("REQUEST_LIMIT")
    return {
        **metadata,
        "mode": "LIVE" if live else "MOCKED_DRY_RUN",
        "live_openai_evals": "EXECUTED" if live and ledger.requests else "NOT RUN",
        "not_model_reliability_evidence": not live,
        "config": config.model_dump(mode="json"),
        "scenario_selection": {
            "requested": scenario,
            "dataset_scenarios": [case.id for case in dataset.cases],
            "selected": [case.id for case in selected],
            "excluded": [case.id for case in dataset.cases if case not in selected],
        },
        "request_policy": {
            "store": False,
            "parallel_tool_calls": False,
            "strict_schemas": True,
            "max_tool_calls_per_turn": 5,
            "provider_timeout_seconds": 30,
            "turn_lease_seconds": 90,
            "retries": 0,
        },
        "pricing": PRICING,
        "dataset_version": dataset.version,
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "database_identity": identity,
        "database_unchanged_after_scoped_cleanup": database_snapshot(engine) == before,
        "budget": ledger.report(),
        "cases": cases,
        "gate": "PASS" if all(c["verdict"] == "PASS" for c in cases) else "FAIL",
    }


def private_directory(directory):
    directory = Path(directory)
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("Symlinks are not accepted for private evaluation reports.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Evaluation report directory must be private (0700).")
    return directory


@contextmanager
def reserve_report(directory):
    directory = private_directory(directory)
    target = directory / "R2_smoke_report.json"
    if target.exists() or target.is_symlink():
        raise ValueError("Use a new private report directory for each run.")
    lock = directory / ".running"
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    try:
        yield directory
    finally:
        lock.unlink()


def write_report(report, directory, secrets=()):
    directory = private_directory(directory)
    value = json.dumps(report, indent=2)
    for secret in filter(None, secrets):
        value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}", "[REDACTED]", value)
    path = directory / "R2_smoke_report.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(value + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Default: only mocked HTTP.")
    modes.add_argument(
        "--live", action="store_true", help="Paid; separate owner authorization required."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="One exact dataset scenario ID (e.g. S1), supplied once; required for --live.",
    )
    parser.add_argument(
        "--prepare-db", action="store_true", help="Initialize only an empty verified DB."
    )
    parser.add_argument(
        "--reasoning-effort",
        default="none",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
    )
    parser.add_argument("--max-requests", type=int, default=25)
    parser.add_argument("--max-total-tokens", type=int, default=250_000)
    parser.add_argument("--max-estimated-usd", default="1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".local/r2-smoke")
    parser.add_argument("--evaluation-contract", choices=CONTRACT_VERSIONS, default="1.0")
    args = parser.parse_args()
    engine = None
    stack = ExitStack()
    try:
        if args.scenario is not None and len(args.scenario) != 1:
            raise ValueError("Supply --scenario exactly once.")
        scenario = args.scenario[0] if args.scenario is not None else None
        # Also validate before --prepare-db; run_smoke repeats this for direct callers.
        select_scenarios(load_smoke(), scenario, live=args.live)
        config = RunConfig(
            reasoning_effort=args.reasoning_effort,
            max_requests=args.max_requests,
            max_total_tokens=args.max_total_tokens,
            max_estimated_usd=args.max_estimated_usd,
        )
        if args.live and os.environ.get("CLINIC_EVAL_ENABLE_LIVE") != "true":
            raise ValueError("Separate live opt-in is required.")
        # Reserve a writable private destination before any DB effect or paid call.
        stack.enter_context(reserve_report(args.output_dir))
        settings = Settings()
        if settings.test_database_url is None:
            raise ValueError("Dedicated test configuration required.")
        raw_url = settings.test_database_url.get_secret_value()
        validate_url(raw_url)
        engine = build_engine(Settings(_env_file=None, database_url=raw_url))
        ident = os.environ.get("CLINIC_EVAL_DB_SYSTEM_ID")
        if args.prepare_db:
            prepare_database(engine, ident)
        logging.getLogger("clinic.requests").setLevel(logging.WARNING)
        result = run_smoke(
            engine,
            settings,
            ident,
            config,
            live=args.live,
            scenario=scenario,
            evaluation_contract=args.evaluation_contract,
        )
        path = write_report(
            result,
            args.output_dir,
            secrets=(
                settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
                engine.url.password,
            ),
        )
        print(
            json.dumps(
                {
                    "mode": result["mode"],
                    "gate": result["gate"],
                    "live_openai_evals": result["live_openai_evals"],
                    "report": str(path),
                }
            )
        )
        return 0 if result["gate"] == "PASS" else 1
    except Exception:
        print(
            json.dumps(
                {
                    "gate": "FAIL",
                    "reason": "Configuration, isolation or execution failed; diagnostics withheld.",
                }
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        stack.close()


if __name__ == "__main__":
    raise SystemExit(main())
