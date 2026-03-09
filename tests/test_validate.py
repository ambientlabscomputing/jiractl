import pytest
import pandas as pd
from commands.batch.validate.cmd import validate_epics, validate_stories
from models.epic import Epic


def test_validate_epics_valid(sample_config, sample_epics_csv):
    """Test validating valid epics"""
    df = pd.read_csv(sample_epics_csv)
    valid, errors = validate_epics(df, sample_config)
    
    assert len(valid) == 3
    assert len(errors) == 0


def test_validate_epics_invalid_project(sample_config, sample_epics_csv):
    """Test validating epics with invalid project key"""
    df = pd.read_csv(sample_epics_csv)
    df.loc[0, "Project Key"] = "INVALID"
    
    valid, errors = validate_epics(df, sample_config)
    
    assert len(errors) == 1
    assert "not in allowed_projects" in errors[0]["error"]


def test_validate_stories_valid(sample_config, sample_stories_csv, sample_epics_csv):
    """Test validating valid stories"""
    epics_df = pd.read_csv(sample_epics_csv)
    stories_df = pd.read_csv(sample_stories_csv)
    
    valid_epics, _ = validate_epics(epics_df, sample_config)
    valid_stories, errors = validate_stories(stories_df, sample_config, valid_epics)
    
    assert len(valid_stories) == 3
    assert len(errors) == 0


def test_validate_stories_missing_epic(sample_config, sample_stories_csv, sample_epics_csv):
    """Test validating stories with missing epic link"""
    epics_df = pd.read_csv(sample_epics_csv)
    stories_df = pd.read_csv(sample_stories_csv)
    stories_df.loc[0, "Epic Link"] = "NonExistent"
    
    valid_epics, _ = validate_epics(epics_df, sample_config)
    valid, errors = validate_stories(stories_df, sample_config, valid_epics)
    
    assert len(errors) == 1
    assert "not found in epics" in errors[0]["error"]
