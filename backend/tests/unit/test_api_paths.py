"""Path validation.

The builder save handler used to reject '/', '\\', '..' and require a
'.yaml' suffix. On Windows the name 'C:evil.yaml' passes all four checks,
because Path('data/lines') / 'C:evil.yaml' evaluates to 'C:evil.yaml': the
drive letter re-anchors the join and the intended root is discarded.
Verified on the development machine. A separator scan cannot see that, so
safe_child resolves the candidate and compares parents instead.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lineage.api.app import create_app
from lineage.api.deps import AppState, reset_app_state
from lineage.api.paths import safe_child

ESCAPES = [
    "C:evil.yaml",
    "c:evil.yaml",
    "../evil.yaml",
    "..\\evil.yaml",
    "sub/evil.yaml",
    "sub\\evil.yaml",
    "/etc/passwd",
    "\\\\server\\share\\evil.yaml",
    "..",
    ".",
    "",
]


@pytest.mark.parametrize("name", ESCAPES)
def test_rejects_anything_that_is_not_a_plain_child_name(tmp_path, name):
    with pytest.raises(ValueError):
        safe_child(tmp_path, name)


def test_accepts_a_plain_child_name(tmp_path):
    assert safe_child(tmp_path, "line.yaml") == tmp_path / "line.yaml"


def test_accepts_a_name_with_dots_that_is_still_a_child(tmp_path):
    assert safe_child(tmp_path, "my.line.v2.yaml") == tmp_path / "my.line.v2.yaml"


def test_result_is_always_inside_the_root(tmp_path):
    result = safe_child(tmp_path, "line.yaml")
    assert result.resolve().parent == Path(tmp_path).resolve()


def test_builder_save_rejects_a_drive_relative_filename(tmp_path, tiny_line):
    lines_root = tmp_path / "lines"
    lines_root.mkdir()
    reset_app_state(
        AppState(line=tiny_line, runs_root=tmp_path / "runs", lines_root=lines_root)
    )
    with TestClient(create_app()) as client:
        assert client.post("/api/builder/draft/start").status_code == 200
        response = client.post("/api/builder/save", json={"filename": "C:evil.yaml"})

    assert response.status_code == 400
    # Nothing may have been written outside lines_root. Before the fix this
    # landed in the process working directory.
    assert not Path("C:evil.yaml").exists()
    assert list(lines_root.iterdir()) == []


def test_builder_save_still_accepts_a_legitimate_filename(tmp_path, tiny_line):
    """The hardening must not break the path it exists to protect."""
    lines_root = tmp_path / "lines"
    lines_root.mkdir()
    reset_app_state(
        AppState(line=tiny_line, runs_root=tmp_path / "runs", lines_root=lines_root)
    )
    with TestClient(create_app()) as client:
        assert client.post("/api/builder/draft/start").status_code == 200
        response = client.post("/api/builder/save", json={"filename": "my_line.yaml"})

    assert response.status_code == 200
    assert (lines_root / "my_line.yaml").exists()


def test_replay_load_rejects_a_traversing_run_id(tmp_path, tiny_line):
    """Unvalidated, runs_root / run_id was an unauthenticated existence
    oracle for arbitrary filesystem paths."""
    reset_app_state(AppState(line=tiny_line, runs_root=tmp_path / "runs"))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/replay/control", json={"action": "load", "run_id": "../../etc"}
        )

    assert response.status_code == 400


def test_replay_load_still_reports_404_for_a_plain_unknown_run(tmp_path, tiny_line):
    """A well-formed but absent run_id is 'not found', not 'malformed'. The
    two must stay distinguishable."""
    reset_app_state(AppState(line=tiny_line, runs_root=tmp_path / "runs"))
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/replay/control", json={"action": "load", "run_id": "no-such-run"}
        )

    assert response.status_code == 404
