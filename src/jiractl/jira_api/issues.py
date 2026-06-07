from jiractl.jira_api.client import JiraClient


def _description_as_adf(text: str) -> dict:
    """Convert plain text description to ADF (Atlassian Document Format)"""
    if not text:
        return {"type": "doc", "version": 1, "content": []}

    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def get_project_issue_types(client: JiraClient, project_key: str) -> list[dict]:
    """
    Return the list of available issue types for a project.
    Uses /rest/api/3/issue/createmeta/{projectKey}/issuetypes
    Each dict has keys: id, name, description, subtask.
    """
    data = client.get(f"/issue/createmeta/{project_key}/issuetypes")
    return data.get("issueTypes", [])


def resolve_issue_type_name(client: JiraClient, project_key: str, preferred_name: str) -> str:
    """
    Resolve an issue type name for a project, falling back gracefully if the
    preferred name doesn't exist (e.g. 'Story' vs 'Task').
    Returns the resolved name or raises ValueError.
    """
    types = get_project_issue_types(client, project_key)
    names = [t["name"] for t in types]
    if preferred_name in names:
        return preferred_name
    # Common fallbacks
    fallbacks = {
        "Story": ["Task", "User Story"],
        "Epic": ["Epic"],
    }
    for fallback in fallbacks.get(preferred_name, []):
        if fallback in names:
            return fallback
    raise ValueError(f"Issue type '{preferred_name}' not found in project {project_key}. Available types: {names}")


def create_epic(
    client: JiraClient,
    project_key: str,
    epic_name: str,
    summary: str,
    description: str,
) -> str:
    """
    Create an Epic in Jira.
    Returns the issue key (e.g., "PROJ-123").

    In Jira Cloud REST API v3 the Epic's display name is its summary.
    """
    issue_type_name = resolve_issue_type_name(client, project_key, "Epic")
    payload = {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type_name},
            "summary": epic_name if epic_name else summary,
            "description": _description_as_adf(description),
        }
    }

    result = client.post("/issue", payload)
    assert result is not None, "Jira API returned no body for issue creation"
    return result["key"]


def create_story(
    client: JiraClient,
    project_key: str,
    summary: str,
    description: str,
    epic_key: str,
) -> str:
    """
    Create a Story in Jira linked to an Epic via the 'parent' field.
    This is the correct Jira Cloud REST API v3 approach (Epic Link is deprecated).
    Returns the issue key (e.g., "PROJ-456").
    """
    issue_type_name = resolve_issue_type_name(client, project_key, "Story")
    payload = {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type_name},
            "summary": summary,
            "description": _description_as_adf(description),
            "parent": {"key": epic_key},
        }
    }

    result = client.post("/issue", payload)
    assert result is not None, "Jira API returned no body for issue creation"
    return result["key"]


def create_bug(
    client: JiraClient,
    project_key: str,
    summary: str,
    adf_description: dict,
    issue_type: str = "Bug",
) -> str:
    """
    Create a Bug (or fallback issue type) in Jira using a pre-built ADF
    description dict.  Falls back to "Task" if the requested issue type is
    not available in the project.
    Returns the issue key (e.g., "DEV-42").
    """
    # Attempt to resolve the requested type, then fall back to Task.
    resolved_type = issue_type
    try:
        resolved_type = resolve_issue_type_name(client, project_key, issue_type)
    except ValueError:
        try:
            resolved_type = resolve_issue_type_name(client, project_key, "Task")
        except ValueError:
            pass  # send as-is and let Jira return a helpful error

    payload = {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": resolved_type},
            "summary": summary,
            "description": adf_description,
        }
    }

    result = client.post("/issue", payload)
    assert result is not None, "Jira API returned no body for issue creation"
    return result["key"]
