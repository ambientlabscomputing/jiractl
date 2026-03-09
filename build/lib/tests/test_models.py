import pytest
from models.epic import Epic
from models.ticket import Story


def test_epic_creation():
    """Test creating an Epic model"""
    epic = Epic(
        epic_name="Test Epic",
        summary="Test Summary",
        description="Test Description",
        project_key="TEST",
    )
    assert epic.epic_name == "Test Epic"
    assert epic.summary == "Test Summary"


def test_epic_validates_empty_name():
    """Test that Epic requires non-empty epic_name"""
    with pytest.raises(ValueError):
        Epic(
            epic_name="",
            summary="Summary",
            description="Desc",
            project_key="TEST",
        )


def test_story_creation():
    """Test creating a Story model"""
    story = Story(
        summary="Test Story",
        description="Test Description",
        epic_link="Epic 1",
        project_key="TEST",
    )
    assert story.summary == "Test Story"
    assert story.epic_link == "Epic 1"


def test_story_validates_empty_epic_link():
    """Test that Story requires non-empty epic_link"""
    with pytest.raises(ValueError):
        Story(
            summary="Summary",
            description="Desc",
            epic_link="",
            project_key="TEST",
        )
