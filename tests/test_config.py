def test_config_creation(sample_config):
    """Test creating a Config model"""
    assert sample_config.base_url == "https://test.atlassian.net"
    assert sample_config.email == "test@example.com"
    assert "TEST" in sample_config.allowed_projects


def test_resolve_project_exact_match(sample_config):
    """Test resolving project by exact key match"""
    assert sample_config.resolve_project("TEST") == "TEST"
    assert sample_config.resolve_project("PROJ") == "PROJ"


def test_resolve_project_synonym_match(sample_config):
    """Test resolving project by synonym"""
    assert sample_config.resolve_project("test-key") == "TEST"
    assert sample_config.resolve_project("t1") == "TEST"
    assert sample_config.resolve_project("proj-key") == "PROJ"


def test_resolve_project_not_found(sample_config):
    """Test resolving a non-existent project"""
    assert sample_config.resolve_project("UNKNOWN") is None
    assert sample_config.resolve_project("foo") is None
