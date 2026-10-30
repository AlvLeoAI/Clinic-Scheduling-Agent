"""Current documentation, OpenAPI parity and committed offline evaluation reconciliation."""

import hashlib
import json
import re
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (
    "README.md",
    "SYSTEM_DESIGN.md",
    "TESTING.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/API_DESIGN.md",
    "docs/EVALUATION.md",
    "docs/SECURITY_PRIVACY.md",
)
# README declares the release status once; any block described elsewhere must cite
# a blocker listed there, e.g. "- BLK-01: one-line reason".
STATUS_LINE = re.compile(r"^Release status: (OPEN|BLOCKED)$", re.MULTILINE)
STATUS_ANY = re.compile(r"^\s*Release status\s*:.*$", re.MULTILINE | re.IGNORECASE)
BLOCKER_ENTRY = re.compile(r"^- (BLK-\d{2}): \S.*$", re.MULTILINE)
BLOCKER_ID = re.compile(r"\bBLK-\d{2}\b")
RELEASE_BLOCK = re.compile(
    r"release[- ]blocker|(?:release|publication) (?:remains|is) blocked"
    r"|(?:public release|publication)[^.\n]{0,40}\bblocked\b|\|\s*BLOCKED\s*\|",
    re.IGNORECASE,
)
# Internal phase labels and decision-tracking wording belong only in docs/history/.
PHASE_JARGON = re.compile(
    r"\b(?:R[1-3][A-E](?:\.\d+[a-z]?)?|M[0-6]|S[1-5])\b|owner acceptance|UNDECIDED",
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
    """Markdown outside docs/history/; history records are frozen and never gate CI."""
    history = root / "docs/history"
    paths = sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))
    return [path for path in paths if not path.is_relative_to(history)]


def release_status(readme):
    declared = STATUS_LINE.findall(readme)
    assert len(declared) == 1 and len(STATUS_ANY.findall(readme)) == 1, (
        "README.md must declare exactly one release status line."
    )
    entries = BLOCKER_ENTRY.findall(readme)
    assert len(entries) == len(set(entries)), "README.md repeats a blocker identifier."
    if declared[0] == "BLOCKED":
        assert entries, "A BLOCKED release must list at least one blocker with a reason."
    else:
        assert not entries, "An OPEN release must not list blockers."
    return declared[0], set(entries)


def check_release_status(root=ROOT):
    readme = (root / "README.md").read_text()
    assert re.search(r"^## Security history$", readme, re.MULTILINE), (
        "README.md lacks a Security history section."
    )
    status, blockers = release_status(readme)
    documents = current_documents(root)
    for path in documents:
        text = STATUS_ANY.sub("", path.read_text())
        assert set(BLOCKER_ID.findall(text)) <= blockers, (
            "Current documentation cites a blocker that README.md does not list."
        )
        for paragraph in re.split(r"\n\s*\n", text):
            if not RELEASE_BLOCK.search(paragraph):
                continue
            assert status == "BLOCKED", "Current documentation describes a block while OPEN."
            assert BLOCKER_ID.search(paragraph), (
                "Current documentation describes a block without a blocker identifier."
            )
    return {"status": status, "blockers": len(blockers), "documents": len(documents)}


def check_phase_jargon(root=ROOT):
    flagged = [name for name in CURRENT_DOCS if PHASE_JARGON.search((root / name).read_text())]
    assert not flagged, "Current documentation contains internal phase wording."
    return len(CURRENT_DOCS)


def main():
    try:
        documents = [ROOT / name for name in CURRENT_DOCS]
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
        release = check_release_status()
        jargon_docs = check_phase_jargon()
        reconciliation = reconcile_m5()
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "local_links_checked": links,
                    "openapi_operations": 9,
                    "m5_reconciliation": reconciliation["status"],
                    "raw_layers": reconciliation["raw_layers"],
                    "hosted_ci_query": "NOT QUERIED BY THIS LOCAL CHECK",
                    "hosted_ci_evidence": "See the CI badge in README.md",
                    "security_history": "PRESENT",
                    "release_status": release["status"],
                    "release_blockers": release["blockers"],
                    "current_docs_checked": release["documents"],
                    "phase_jargon_docs_checked": jargon_docs,
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
