"""
High-level Jira search and read functions.
All functions accept a JiraClient and return plain Python dicts/lists.
"""

from __future__ import annotations

from typing import cast

from jira_api.client import JiraClient

# Fields we request for all issue lookups — keeps payloads lean
DEFAULT_FIELDS = [
    "summary",
    "description",
    "status",
    "issuetype",
    "priority",
    "assignee",
    "reporter",
    "parent",
    "subtasks",
    "created",
    "updated",
    "labels",
    "comment",
    "project",
]


# ---------------------------------------------------------------------------
# ADF → plain text
# ---------------------------------------------------------------------------


def adf_to_text(node: dict | None, _depth: int = 0) -> str:
    """
    Recursively walk an Atlassian Document Format (ADF) node and return
    plain text with minimal whitespace.
    """
    if not node:
        return ""

    node_type = node.get("type", "")
    text = node.get("text", "")

    if text:
        return text

    children = node.get("content", [])
    parts = [adf_to_text(c, _depth + 1) for c in children]

    if node_type in ("paragraph", "heading", "blockquote"):
        return " ".join(p for p in parts if p).rstrip() + "\n"
    if node_type in ("bulletList", "orderedList"):
        return "\n".join(p.strip() for p in parts if p.strip())
    if node_type == "listItem":
        return "• " + " ".join(p for p in parts if p).strip()
    if node_type == "hardBreak":
        return "\n"
    if node_type == "rule":
        return "\n---\n"
    if node_type == "codeBlock":
        return "\n".join(parts)

    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Single issue fetch
# ---------------------------------------------------------------------------


def get_issue(client: JiraClient, key: str) -> dict:
    """Fetch a single issue by key. Returns the full Jira issue dict."""
    params = {"fields": ",".join(DEFAULT_FIELDS)}
    return client.get(f"/issue/{key}", params=params)


# ---------------------------------------------------------------------------
# JQL search
# ---------------------------------------------------------------------------


def search_issues(
    client: JiraClient,
    jql: str,
    fields: list[str] | None = None,
    max_results: int = 50,
    next_page_token: str | None = None,
) -> tuple[list[dict], str | None]:
    """
    Run a JQL search via GET /rest/api/3/search/jql (cursor-based pagination).
    Returns (issues, next_page_token).
    next_page_token is None when there are no more pages.
    Each issue is the raw Jira dict with a 'fields' sub-dict.
    """
    params: dict = {
        "jql": jql,
        "maxResults": max_results,
        "fields": ",".join(fields or DEFAULT_FIELDS),
    }
    if next_page_token:
        params["nextPageToken"] = next_page_token
    data = client.get("/search/jql", params=params)
    is_last = data.get("isLast", True)
    cursor = None if is_last else data.get("nextPageToken")
    return data.get("issues", []), cursor


def search_all(
    client: JiraClient,
    jql: str,
    fields: list[str] | None = None,
    page_size: int = 50,
) -> list[dict]:
    """
    Paginate through all results for a JQL query using cursor-based pagination.
    """
    issues: list[dict] = []
    cursor: str | None = None
    while True:
        page, cursor = search_issues(
            client, jql, fields=fields, max_results=page_size, next_page_token=cursor
        )
        issues.extend(page)
        if cursor is None or not page:
            break
    return issues


# ---------------------------------------------------------------------------
# Convenience queries
# ---------------------------------------------------------------------------


def get_epic_children(
    client: JiraClient, epic_key: str, max_results: int = 100
) -> list[dict]:
    """
    Return all child issues of an Epic (Stories, Tasks, etc.).
    Uses 'parent = EPIC-KEY' JQL which works for Jira Cloud next-gen
    and classic projects where stories are linked via parent.
    """
    jql = f'parent = "{epic_key}" ORDER BY created ASC'
    return search_all(client, jql, page_size=min(max_results, 100))


def get_project_epics(
    client: JiraClient, project_key: str, max_results: int = 100
) -> list[dict]:
    """Return all Epics in a project, newest first."""
    jql = f'project = "{project_key}" AND issuetype = Epic ORDER BY created DESC'
    return search_all(client, jql, page_size=min(max_results, 100))


def get_project_issues(
    client: JiraClient,
    project_key: str,
    issue_type: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    text: str | None = None,
    max_results: int = 100,
) -> list[dict]:
    """
    Return issues in a project with optional filters.
    """
    parts = [f'project = "{project_key}"']
    if issue_type:
        parts.append(f'issuetype = "{issue_type}"')
    if status:
        parts.append(f'status = "{status}"')
    if assignee:
        parts.append(f'assignee = "{assignee}"')
    if text:
        parts.append(f'text ~ "{text}"')
    jql = " AND ".join(parts) + " ORDER BY created DESC"
    return search_all(client, jql, page_size=min(max_results, 100))


def get_my_issues(
    client: JiraClient,
    project_key: str | None = None,
    status: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Return issues assigned to the current user (currentUser())."""
    parts = ["assignee = currentUser()"]
    if project_key:
        parts.append(f'project = "{project_key}"')
    if status:
        parts.append(f'status = "{status}"')
    jql = " AND ".join(parts) + " ORDER BY updated DESC"
    return search_all(client, jql, page_size=min(max_results, 100))


# ---------------------------------------------------------------------------
# Project / field inspection
# ---------------------------------------------------------------------------


def get_project_meta(client: JiraClient, project_key: str) -> dict:
    """
    Return full project metadata from GET /project/{key}.
    Includes name, key, lead, projectTypeKey, description, etc.
    """
    return client.get(f"/project/{project_key}")


def get_project_statuses(client: JiraClient, project_key: str) -> list[dict]:
    """
    Return issue types and their available statuses for a project.
    Each item: {id, name, subtask, statuses: [{id, name, statusCategory}]}.
    """
    return cast(list[dict], client.get(f"/project/{project_key}/statuses"))


def get_project_issue_types(client: JiraClient, project_key: str) -> list[dict]:
    """
    Return the issue types available for a project via the createmeta API.
    Each item: {id, name, description, iconUrl, subtask}.
    """
    data = client.get(f"/issue/createmeta/{project_key}/issuetypes")
    return data.get("issueTypes", [])


def get_fields_for_issue_type(
    client: JiraClient,
    project_key: str,
    issue_type_id: str,
    page_size: int = 200,
) -> list[dict]:
    """
    Return all editable fields for a given issue type + project combination
    via the paginated createmeta fields endpoint.

    Each item is a field descriptor dict with at least:
      fieldId, key, name, required, schema {type, system/custom}, operations.
    """
    all_fields: list[dict] = []
    start = 0
    while True:
        data = client.get(
            f"/issue/createmeta/{project_key}/issuetypes/{issue_type_id}",
            params={"maxResults": page_size, "startAt": start},
        )
        page: list[dict] = data.get("fields", [])
        all_fields.extend(page)
        total = data.get("total", len(all_fields))
        start += page_size
        if start >= total or not page:
            break
    return all_fields
