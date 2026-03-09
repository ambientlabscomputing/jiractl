import json
import pytest
import tempfile
from pathlib import Path
from commands.batch.upload.cmd import (
    _load_state,
    _save_state,
    _state_path,
    _story_key,
    STATE_FILE,
)
from models.ticket import Story


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_load_state_missing_returns_empty(tmp_dir):
    """Loading state from a dir with no state file returns fresh empty state."""
    state = _load_state(tmp_dir)
    assert state == {"epics": {}, "stories": {}, "failures": []}


def test_save_and_load_state_roundtrip(tmp_dir):
    """State written to disk is loaded back identically."""
    state = {
        "epics": {"My Epic": "TEST-1"},
        "stories": {"TEST|My Epic|Story A": "TEST-2"},
        "failures": [],
    }
    _save_state(tmp_dir, state)
    assert _state_path(tmp_dir).exists()

    loaded = _load_state(tmp_dir)
    assert loaded == state


def test_save_state_creates_file(tmp_dir):
    """_save_state creates upload_state.json in the given dir."""
    _save_state(tmp_dir, {"epics": {}, "stories": {}, "failures": []})
    expected = tmp_dir / STATE_FILE
    assert expected.exists()
    data = json.loads(expected.read_text())
    assert "epics" in data


def test_state_path(tmp_dir):
    """_state_path returns the correct path."""
    assert _state_path(tmp_dir) == tmp_dir / STATE_FILE


def test_story_key_is_stable():
    """_story_key produces a consistent stable identifier."""
    story = Story(
        summary="My Story",
        description="Desc",
        epic_link="My Epic",
        project_key="TEST",
    )
    key = _story_key(story)
    assert key == "TEST|My Epic|My Story"
    # Calling again yields the same value
    assert _story_key(story) == key


def test_story_key_distinguishes_different_stories():
    """Two stories with different summaries or epic links get different keys."""
    s1 = Story(summary="Story A", description="", epic_link="Epic 1", project_key="TEST")
    s2 = Story(summary="Story B", description="", epic_link="Epic 1", project_key="TEST")
    s3 = Story(summary="Story A", description="", epic_link="Epic 2", project_key="TEST")

    assert _story_key(s1) != _story_key(s2)
    assert _story_key(s1) != _story_key(s3)


def test_existing_state_skips_already_created(tmp_dir):
    """
    When state records an epic, the upload loop should skip it.
    This tests the state structure, not the full upload (which requires live Jira).
    """
    # Simulate a partial upload: epic was created, nothing else
    state = {
        "epics": {"Provider operations": "TCRM-1"},
        "stories": {},
        "failures": [],
    }
    _save_state(tmp_dir, state)
    loaded = _load_state(tmp_dir)

    # The epic key is already in state — the upload would skip it
    assert "Provider operations" in loaded["epics"]
    assert loaded["epics"]["Provider operations"] == "TCRM-1"
