"""Explicit evaluation contract selection; historical v1 remains the default."""

import hashlib
from pathlib import Path

from evaluations import (
    graders,
    graders_v1_1,
    graders_v1_2,
    live_graders,
    live_graders_v1_1,
    live_graders_v1_2,
)

CONTRACT_VERSIONS = ("1.0", "1.1", "1.2")
ROOT = Path(__file__).resolve().parent


def select_contract(version):
    if version == "1.0":
        return graders.grade, live_graders.grade_smoke
    if version == "1.1":
        return graders_v1_1.grade, live_graders_v1_1.grade_smoke
    if version == "1.2":
        return graders_v1_2.grade, live_graders_v1_2.grade_smoke
    raise ValueError("Select one exact evaluation contract version: 1.0, 1.1 or 1.2.")


def contract_metadata(version, *, smoke=False):
    select_contract(version)
    paths = ["graders.py", "oracle.py"]
    if smoke:
        paths.insert(0, "live_graders.py")
    if version in {"1.1", "1.2"}:
        # Include every delegated grading dependency and the explicit selector.
        paths = ["graders_v1_1.py", "live_graders_v1_1.py", "live_graders.py", *paths, "scoring.py"]
        paths = list(dict.fromkeys(paths))
    if version == "1.2":
        paths = ["graders_v1_2.py", "live_graders_v1_2.py", *paths]
    metadata = {
        "evaluation_contract_version": version,
        "scorer_version": ("r2-layered-" if smoke else "scheduling-layered-") + (version + ".0"),
        "scorer_sha256": hashlib.sha256(
            b"".join((ROOT / path).read_bytes() for path in paths)
        ).hexdigest(),
        "scorer_sources": paths,
    }

    if version == "1.2":
        metadata["contract_document_sha256"] = hashlib.sha256(
            (ROOT.parent / "docs/EVALUATION_CONTRACT_V1_2.md").read_bytes()
        ).hexdigest()
        metadata["control_fixture_sha256"] = hashlib.sha256(
            (ROOT.parent / "tests/test_graders_v1_2.py").read_bytes()
        ).hexdigest()
    return metadata
