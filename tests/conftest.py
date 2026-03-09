import pytest
import tempfile
from pathlib import Path
from models.config import Config
from models.epic import Epic
from models.ticket import Story
import pandas as pd
import yaml


@pytest.fixture
def sample_config():
    """Create a sample config for testing"""
    return Config(
        base_url="https://test.atlassian.net",
        email="test@example.com",
        allowed_projects=["TEST", "PROJ"],
        synonyms={
            "TEST": ["test-key", "t1"],
            "PROJ": ["proj-key", "p1"],
        }
    )


@pytest.fixture
def temp_config_file(sample_config):
    """Create a temporary config file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({
            "base_url": sample_config.base_url,
            "email": sample_config.email,
            "allowed_projects": sample_config.allowed_projects,
            "synonyms": sample_config.synonyms,
        }, f)
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def sample_epics_csv():
    """Create a sample epics CSV file"""
    data = {
        "Project Key": ["TEST", "TEST", "PROJ"],
        "Epic Name": ["Epic 1", "Epic 2", "Epic 3"],
        "Summary": ["Summary 1", "Summary 2", "Summary 3"],
        "Description": ["Desc 1", "Desc 2", "Desc 3"],
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df = pd.DataFrame(data)
        df.to_csv(f.name, index=False)
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()


@pytest.fixture
def sample_stories_csv():
    """Create a sample stories CSV file"""
    data = {
        "Project Key": ["TEST", "TEST", "PROJ"],
        "Summary": ["Story 1", "Story 2", "Story 3"],
        "Description": ["Desc 1", "Desc 2", "Desc 3"],
        "Epic Link": ["Epic 1", "Epic 1", "Epic 3"],
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df = pd.DataFrame(data)
        df.to_csv(f.name, index=False)
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink()
