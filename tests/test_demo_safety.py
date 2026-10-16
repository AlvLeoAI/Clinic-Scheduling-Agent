"""Safety gates must reject before obtaining a DB connection or running a mutation."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from app.core.config import Settings
from cli.client import StateFile
from scripts import demo_support

pytestmark = pytest.mark.unit
LOCAL = "postgresql+psycopg://clinic_demo:synthetic@127.0.0.1:15432/clinic_scheduling_test"


@pytest.mark.parametrize(
    "unsafe",
    [
        LOCAL.replace("_test", "_dev"),
        LOCAL.replace("_test", "_production"),
        LOCAL.replace("127.0.0.1", "example.com"),
        LOCAL.replace("clinic_demo:", "admin:"),
        LOCAL + "?options=unsafe",
    ],
)
def test_invalid_target_rejected_before_engine_or_cleanup(monkeypatch, unsafe):
    settings = Settings(_env_file=None, database_url=unsafe)
    monkeypatch.setattr(
        demo_support, "build_engine", lambda *_: pytest.fail("Unsafe connection attempted")
    )
    with pytest.raises(ValueError):
        demo_support.prepare(settings)
    with pytest.raises(ValueError):
        demo_support.cleanup_owned(SimpleNamespace(url=make_url(unsafe)), [])


def test_mismatched_engine_refused_before_query():
    settings = Settings(_env_file=None, database_url=LOCAL)
    with pytest.raises(ValueError):
        demo_support.validate_engine(
            settings, SimpleNamespace(url=make_url(LOCAL.replace("_test", "_dev")))
        )
    with pytest.raises(ValueError):
        demo_support.validate_engine(
            settings, SimpleNamespace(url=make_url(LOCAL.replace("15432", "15433")))
        )


@pytest.mark.parametrize("which", ["cli", "concurrency"])
def test_synthetic_flag_required_before_prepare(monkeypatch, which):
    if which == "cli":
        from cli import __main__ as module
    else:
        from scripts import demo_concurrency as module
    monkeypatch.setattr(module, "prepare", lambda *_: pytest.fail("Unapproved preparation"))
    monkeypatch.setattr("sys.argv", ["demo"])
    with pytest.raises(SystemExit) as stopped:
        module.main()
    assert stopped.value.code == 2


def test_private_state_permissions_scope_and_symlink(tmp_path):
    path = tmp_path / "state.json"
    state = StateFile(path, "synthetic-scope")
    state.save()
    assert path.stat().st_mode & 0o777 == 0o600
    assert StateFile(path, "synthetic-scope").value == state.value
    with pytest.raises(ValueError):
        StateFile(path, "different-backend")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        StateFile(path, "synthetic-scope")
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        StateFile(link, "synthetic-scope")


def test_no_owned_ids_means_no_cleanup_sql(monkeypatch):
    monkeypatch.setattr(demo_support, "Session", lambda *_: pytest.fail("Empty cleanup issued SQL"))
    demo_support.cleanup_owned(SimpleNamespace(url=make_url(LOCAL)), [])


@pytest.mark.parametrize("fault", ["credential", "sensitive_export"])
def test_current_tree_checker_rejects_planted_material(tmp_path, fault):
    import json
    import shutil

    from scripts.check_synthetic import ROOT, check_tree

    for relative in ["data/appointments.json", "evaluations/datasets/scheduling_v1.json"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, path)
    if fault == "credential":
        path = tmp_path / "bad.py"
        material = "sk-" + "x" * 32
        path.write_text(material)
    else:
        path = tmp_path / "docs/evidence/M6_control.json"
        path.parent.mkdir(parents=True)
        material = "private-synthetic-bearer"
        path.write_text(json.dumps({"session_token": material}))
    bad = check_tree(tmp_path)
    assert bad["status"] == "FAIL" and bad["unknown_candidate_paths"]
    assert material not in json.dumps(bad)
    path.unlink()
    assert check_tree(tmp_path)["status"] == "PASS"
