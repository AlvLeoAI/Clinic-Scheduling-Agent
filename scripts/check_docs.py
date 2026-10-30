"""Current documentation, OpenAPI parity and accepted M5 evidence reconciliation."""

import hashlib
import json
import re
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SUPERSEDED_MARKER = "> Superseded on "
RELEASE_BLOCKED = re.compile(
    r"release[- ]blocker|\bP0\b|release (?:remains|is) blocked"
    r"|(?:public release|publication)[^.\n]{0,40}\bblocked\b|\|\s*BLOCKED\s*\|",
    re.IGNORECASE,
)
INTENDED = {
    "08_bad_grid": {"tool_arguments", "policy_compliance"},
    "09_bad_practitioner": {"tool_arguments", "policy_compliance"},
    "10_bad_type": {"tool_arguments", "policy_compliance"},
    "11_weekend": {"policy_compliance"},
    "14_repeated_mutation": {"policy_compliance"},
    "15_confirm_injection": {"tool_selection", "booking_authorization"},
    "16_sql_injection": {"tool_selection", "booking_authorization"},
    "17_fabricated_confirmation": {"response_grounding", "booking_authorization"},
    "18_backend_correction": {"tool_selection", "response_grounding"},
}


def reconcile_m5():
    report = json.loads((ROOT / "docs/evidence/M5_agent_cases.json").read_text())
    assert (
        report["dataset_sha256"]
        == hashlib.sha256(
            (ROOT / "evaluations/datasets/scheduling_v1.json").read_bytes()
        ).hexdigest()
    )
    cases = {case["case_id"]: case for case in report["cases"]}
    for name, checks in INTENDED.items():
        case = cases[name]
        assert case["layers"]["raw_model"]["verdict"] == "FAIL"
        assert all(
            case["layers"]["raw_model"]["checks"][key]["verdict"] == "FAIL" for key in checks
        )
        assert (
            case["layers"]["backend"]["verdict"]
            == case["layers"]["user_visible"]["verdict"]
            == "PASS"
        )
    absent = cases["19_provider_error"]
    assert absent["critical"] and absent["layers"]["raw_model"]["verdict"] == "NOT RUN"
    assert absent["evidence"]["provider_errors"] == [{"session": "A", "kind": "http_500"}]
    assert [r["status"] for r in absent["evidence"]["responses"]] == [503]
    assert absent["evidence"]["final"]["appointments"] == []
    assert (
        absent["layers"]["backend"]["verdict"]
        == absent["layers"]["user_visible"]["verdict"]
        == "PASS"
    )
    return {
        "status": "PASS",
        "source": "preserved accepted M5_agent_cases.json",
        "raw_layers": report["layers"]["raw_model"],
        "intended_failures_detected": {name: sorted(checks) for name, checks in INTENDED.items()},
        "no_raw_decision": {
            "case_id": "19_provider_error",
            "critical": True,
            "rationale": "Injected provider HTTP 500 produced no decision; "
            "critical backend/visible safety was executed and passed, not skipped.",
            "raw": "NOT RUN",
            "backend": "PASS",
            "visible": "PASS",
        },
        "agent_live": "NOT RUN",
    }


def current_documents(root=ROOT):
    """Markdown documents that describe current state; superseded extracts are frozen."""
    paths = sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))
    return [path for path in paths if SUPERSEDED_MARKER not in path.read_text()]


def check_release_status(root=ROOT):
    readme = (root / "README.md").read_text()
    assert re.search(r"^## Security history$", readme, re.MULTILINE), (
        "README.md lacks a Security history section."
    )
    blocked = [
        str(path.relative_to(root))
        for path in current_documents(root)
        if RELEASE_BLOCKED.search(path.read_text())
    ]
    assert not blocked, "Current documentation describes the project as release-blocked."
    return len(current_documents(root))


def main():
    try:
        documents = [ROOT / name for name in ("README.md", "SYSTEM_DESIGN.md", "TESTING.md")]
        documents += [
            ROOT / "docs" / name
            for name in (
                "ADR_INDEX.md",
                "DATA_MODEL.md",
                "API_DESIGN.md",
                "OPERATIONS.md",
                "AGENT_EVALUATION.md",
                "M5_RECONCILIATION.md",
                "SECURITY_PRIVACY.md",
                "ACCEPTANCE_MATRIX.md",
                "RELEASE_READINESS.md",
                "REPRODUCIBILITY.md",
                "evidence/M6_report.md",
            )
        ]
        links = 0
        for path in documents:
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if link.startswith(("https://", "http://", "#")):
                    continue
                assert (path.parent / link.split("#")[0]).exists(), (
                    "Missing local documentation target."
                )
                links += 1
        snapshot = json.loads((ROOT / "docs/openapi.json").read_text())
        assert snapshot == app.openapi() and len(snapshot["paths"]) == 9
        matrix = (ROOT / "docs/ACCEPTANCE_MATRIX.md").read_text()
        assert all(
            len(re.findall(rf"\| AC-{number:02} \|", matrix)) == 1 for number in range(1, 13)
        )
        current_docs = check_release_status()
        reconciliation = reconcile_m5()
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "local_links_checked": links,
                    "openapi_operations": 9,
                    "acceptance_rows": 12,
                    "m5_reconciliation": reconciliation["status"],
                    "raw_layers": reconciliation["raw_layers"],
                    "hosted_ci_query": "NOT QUERIED BY THIS LOCAL CHECK",
                    "hosted_ci_evidence": "See TESTING.md for commit-scoped historical receipts",
                    "security_history": "PRESENT",
                    "current_docs_release_blocked": 0,
                    "current_docs_checked": current_docs,
                }
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "message": "Documentation or evidence consistency was not established.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
