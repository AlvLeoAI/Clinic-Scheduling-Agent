"""R2 contract 1.2 preserves live-specific completeness and all three independent layers."""

from evaluations import live_graders_v1_1 as v1
from evaluations.graders_v1_2 import enhance

SCORER_VERSION = "r2-layered-1.2.0"


def grade_smoke(case, obs, dataset, events, *, complete):
    result = enhance(
        v1.grade_smoke(case, obs, dataset, events, complete=complete),
        case,
        obs,
        dataset.catalog,
        dataset.clock,
    )
    for key, layer in (
        ("RAW_MODEL_VERDICT", "raw_model"),
        ("BACKEND_VERDICT", "backend"),
        ("USER_VISIBLE_VERDICT", "user_visible"),
    ):
        result[key] = result["layers"][layer]["verdict"]
    result["verdict"] = (
        "PASS"
        if not result["critical_failure"]
        and all(
            result[key] == "PASS"
            for key in ("RAW_MODEL_VERDICT", "BACKEND_VERDICT", "USER_VISIBLE_VERDICT")
        )
        else "FAIL"
    )
    result["rationale"] = (
        "Contract 1.2: all three layers pass independently; no raw credit from rendering."
    )
    return result
