from jira_api.client import JiraClient


def _description_as_adf(text: str) -> dict:
    """Convert plain text description to ADF (Atlassian Document Format)"""
    if not text:
        return {"type": "doc", "version": 1, "content": []}

    # Simple paragraph node for now
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


def get_epic_link_field_id(client: JiraClient) -> str:
    """
    Discover the Epic Link custom field ID from Jira.
    Returns the field ID (e.g., "customfield_10000") or raises if not found.
    """
    fields = client.get("/field")
    
    for field in fields:
        # Look for Epic Link field
        if field.get("name") == "Epic Link" or field.get("id", "").startswith(
            "customfield_"
        ) and "epic" in field.get("name", "").lower():
            return field["id"]
    
    # Fallback: try common custom field IDs
    raise ValueError(
        "Could not find Epic Link custom field. "
        "This instance may use a different field configuration."
    )


def create_epic(
    client: JiraClient,
    project_key: str,
    epic_name: str,
    summary: str,
    description: str,
) -> str:
    """
    Create an Epic in Jira.
    Returns the issue key (e.g., "PROJ-123")
    """
    payload = {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": "Epic"},
            "summary": summary,
            "description": _description_as_adf(description),
            # Epic Name is a custom field - will be discovered and added as needed
            "customfield_10000": epic_name,  # Placeholder, may vary per instance
        }
    }

    result = client.post("/issue", payload)
    return result["key"]


def create_story(
    client: JiraClient,
    project_key: str,
    summary: str,
    description: str,
    epic_key: str,
) -> str:
    """
    Create a Story (task/sub-task) in Jira linked to an Epic.
    Returns the issue key (e.g., "PROJ-456")
    """
    # Get Epic Link field ID
    epic_link_field_id = get_epic_link_field_id(client)

    payload = {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": "Story"},
            "summary": summary,
            "description": _description_as_adf(description),
            epic_link_field_id: epic_key,
        }
    }

    result = client.post("/issue", payload)
    return result["key"]
