"""Limited current-tree credential/fixture checks; never claims to clear Git history."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from evaluations.contracts import Dataset

ROOT = Path(__file__).resolve().parents[1]
SKIP = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".local",
    ".pytest_cache",
    ".ruff_cache",
    "recordings",
    "demos",
    "test-results",
    "tmp",
    "temp",
    "pgdata",
    "volumes",
}
KNOWN = {
    b"your_openai_api_key_here",
    b"your_elevenlabs_api_key_here",
    b"your_openai_api_key",
    b"your_elevenlabs_api_key",
    b"synthetic-test-credential",
    b"synthetic-m5-credential",
    b"synthetic-protocol-credential",
}
PATTERNS = [
    re.compile(rb"(sk-(?:proj-)?[A-Za-z0-9_-]{20,})"),
    re.compile(rb"(?i)(?:OPENAI_API_KEY|ELEVENLABS_API_KEY)\s*=\s*[\x22\x27]?([A-Za-z0-9_-]{20,})"),
]


def check_tree(root=ROOT):
    root = Path(root)
    candidates, mock_matches, scanned = set(), 0, 0
    for directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in SKIP]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root)
            if path.is_symlink() or (name.startswith(".env") and name != ".env.example"):
                continue
            if path.suffix.lower() in {".zip", ".mp3", ".wav", ".pyc", ".db", ".sqlite"}:
                continue
            scanned += 1
            value = path.read_bytes()
            for pattern in PATTERNS:
                for match in pattern.finditer(value):
                    if match.group(1) in KNOWN:
                        mock_matches += 1
                    else:
                        candidates.add(str(relative))
            if relative.parts[:2] == ("docs", "evidence") and any(
                part.startswith("M6") for part in relative.parts[2:]
            ):
                if re.search(
                    rb'(?i)"(?:api[_-]?key|session_token|token_hash|authorization|patient_name|phone|visit_reason)"\s*:',
                    value,
                ):
                    candidates.add(str(relative))
    dataset = Dataset.model_validate_json(
        (root / "evaluations/datasets/scheduling_v1.json").read_text()
    )
    assert len(dataset.cases) == 25 and all(
        "Synthetic" in row.message for case in dataset.cases for row in case.input
    )
    retired = json.loads((root / "data/appointments.json").read_text())
    assert retired["booked_appointments"] == [] and retired["available_slots"] == {}
    tracked_sensitive = []
    if (root / ".git").exists():
        listed = subprocess.check_output(["git", "ls-files"], cwd=root).decode().splitlines()
        tracked_sensitive = [
            p
            for p in listed
            if Path(p).name == ".env"
            or Path(p).suffix.lower() in {".zip", ".mp3", ".wav", ".pem", ".key"}
        ]
    return {
        "status": "FAIL" if candidates or tracked_sensitive else "PASS",
        "scope": "limited current text tree and artificial fixtures; history NOT SCANNED",
        "files_scanned": scanned,
        "unknown_candidate_paths": sorted(candidates),
        "known_placeholder_mock_matches": mock_matches,
        "tracked_sensitive_paths": tracked_sensitive,
        "synthetic_dataset_cases": 25,
        "retired_bookings_empty": True,
        "historical_security": "CLOSED; see README Security history",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = check_tree(args.root)
    except Exception:
        result = {
            "status": "FAIL",
            "message": "Current-tree/fixture check could not be established.",
        }
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
