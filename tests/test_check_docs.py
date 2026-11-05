"""The documentation checks that guard the security history and the release status."""

import shutil
from pathlib import Path

import pytest

from scripts import check_docs

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def docs(tmp_path):
    for name in check_docs.CURRENT_DOCS:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


def rewrite(root: Path, name: str, old: str, new: str) -> None:
    path = root / name
    text = path.read_text()
    assert old in text, (name, old)
    path.write_text(text.replace(old, new))


def test_the_committed_docs_pass():
    assert check_docs.check_security_history() == "docs/SECURITY_HISTORY.md"
    assert check_docs.check_release_status()["status"] == "OPEN"


def test_the_readme_keeps_one_release_status_line_without_the_history_section():
    readme = (ROOT / "README.md").read_text()
    assert "## Security history" not in readme
    assert readme.count("Release status: OPEN") == 1


@pytest.mark.parametrize("section", check_docs.HISTORY_SECTIONS)
def test_the_record_must_keep_each_section(docs, section):
    rewrite(docs, check_docs.SECURITY_HISTORY, section, "## Something else")
    with pytest.raises(AssertionError, match="required section"):
        check_docs.check_security_history(docs)


def test_a_missing_record_fails(docs):
    (docs / check_docs.SECURITY_HISTORY).unlink()
    with pytest.raises(FileNotFoundError):
        check_docs.check_security_history(docs)


def test_the_security_document_must_link_to_the_record(docs):
    rewrite(docs, "docs/SECURITY_PRIVACY.md", "](SECURITY_HISTORY.md)", "](EVALUATION.md)")
    with pytest.raises(AssertionError, match="does not link to the security history"):
        check_docs.check_security_history(docs)


def test_the_readme_must_link_to_the_security_document(docs):
    rewrite(docs, "README.md", "](docs/SECURITY_PRIVACY.md)", "](docs/EVALUATION.md)")
    with pytest.raises(AssertionError, match="does not link to SECURITY_PRIVACY"):
        check_docs.check_security_history(docs)


@pytest.mark.parametrize("claim", ["What remains: nothing.", "Nothing remains to be done."])
def test_unbounded_closure_wording_fails_in_any_current_doc(docs, claim):
    rewrite(docs, "docs/SECURITY_PRIVACY.md", "## Data\n", f"{claim}\n\n## Data\n")
    with pytest.raises(AssertionError, match="unbounded security closure"):
        check_docs.check_security_history(docs)


def test_the_record_is_a_current_doc_checked_for_phase_codes(docs):
    assert check_docs.SECURITY_HISTORY in check_docs.CURRENT_DOCS
    rewrite(docs, check_docs.SECURITY_HISTORY, "## Conclusion", "## Conclusion (M0)")
    with pytest.raises(AssertionError, match="phase wording"):
        check_docs.check_phase_jargon(docs)
