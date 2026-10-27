"""Explicit evaluation contract selection; historical v1 remains the default."""

import hashlib
from pathlib import Path

from evaluations import graders, graders_v1_1, live_graders, live_graders_v1_1

CONTRACT_VERSIONS = ("1.0", "1.1")
ROOT = Path(__file__).resolve().parent


def select_contract(version):
    if version == "1.0":
        return graders.grade, live_graders.grade_smoke
    if version == "1.1":
        return graders_v1_1.grade, live_graders_v1_1.grade_smoke
    raise ValueError("Select one exact evaluation contract version: 1.0 or 1.1.")


def contract_metadata(version, *, smoke=False):
    select_contract(version)
    paths = ["graders.py", "oracle.py"]
    if smoke:
        paths.insert(0, "live_graders.py")
    if version == "1.1":
        # Include every delegated grading dependency and the explicit selector.
        paths = ["graders_v1_1.py", "live_graders_v1_1.py", "live_graders.py", *paths, "scoring.py"]
        paths = list(dict.fromkeys(paths))
    return {
        "evaluation_contract_version": version,
        "scorer_version": ("r2-layered-" if smoke else "scheduling-layered-")
        + ("1.0.0" if version == "1.0" else "1.1.0"),
        "scorer_sha256": hashlib.sha256(
            b"".join((ROOT / path).read_bytes() for path in paths)
        ).hexdigest(),
        "scorer_sources": paths,
    }
