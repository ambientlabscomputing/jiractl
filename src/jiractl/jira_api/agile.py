"""
Jira Agile REST API helpers (Software boards, sprints, backlog).

Uses the /rest/agile/1.0/ endpoint (separate from the core REST v3 API).
The JiraClient._url() method passes /rest/agile/ paths through unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jiractl.jira_api.client import JiraClient


def get_boards(client: JiraClient, project_key: str | None = None) -> list[dict]:
    """Return all boards visible to the current user, optionally filtered by project key."""
    params: dict = {"maxResults": 50}
    if project_key:
        params["projectKeyOrId"] = project_key
    data = client.get("/rest/agile/1.0/board", params=params)
    return data.get("values", [])


def get_board_info(client: JiraClient, board_id: int) -> dict:
    """Return full details for a specific board, including its type (kanban, scrum, etc)."""
    data = client.get(f"/rest/agile/1.0/board/{board_id}")
    return data


def is_kanban_board(client: JiraClient, board_id: int) -> bool:
    """Check if the given board is a Kanban board (vs Scrum, etc)."""
    try:
        board = get_board_info(client, board_id)
        board_type = board.get("type", "").lower()
        return board_type == "kanban"
    except Exception:
        # If we can't determine the type, assume it's not Kanban
        # This allows the error handling downstream to provide context
        return False


def get_board_backlog(
    client: JiraClient,
    board_id: int,
    max_results: int = 50,
) -> list[dict]:
    """Return issues currently in the backlog for the given board."""
    data = client.get(
        f"/rest/agile/1.0/board/{board_id}/backlog",
        params={"maxResults": max_results},
    )
    return data.get("issues", [])


def get_board_sprints(
    client: JiraClient,
    board_id: int,
    state: str | None = None,
) -> list[dict]:
    """
    Return sprints for the given board.

    For Kanban boards (which don't have sprints), returns an empty list.

    :param state: Comma-separated sprint states to include.
                  Valid values: active, future, closed.
                  Defaults to all states if not provided.
    """
    params: dict = {"maxResults": 50}
    if state:
        params["state"] = state
    try:
        data = client.get(f"/rest/agile/1.0/board/{board_id}/sprint", params=params)
        return data.get("values", [])
    except Exception as e:
        # Kanban boards return 400 when querying the sprint endpoint
        # Return empty list rather than raising, allowing downstream to handle gracefully
        import httpx

        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 400:
            # This is likely a Kanban board; return empty sprints
            return []
        # Re-raise for other errors
        raise


def get_active_sprint(client: JiraClient, board_id: int) -> dict | None:
    """Return the currently active sprint for the board, or None if no sprint is active."""
    sprints = get_board_sprints(client, board_id, state="active")
    return sprints[0] if sprints else None


def resolve_sprint(client: JiraClient, board_id: int, sprint_ref: str) -> dict:
    """
    Resolve a sprint reference (numeric ID or name substring) to a sprint dict.

    Numeric strings are treated as sprint IDs and used directly.
    Non-numeric strings are matched case-insensitively against sprint names
    across active and future sprints (closed sprints are also included as a
    fallback so that historical sprint names still resolve).

    Raises ValueError with a helpful message when no sprint is found.
    """
    if sprint_ref.isdigit():
        sprint_id = int(sprint_ref)
        data = client.get(f"/rest/agile/1.0/sprint/{sprint_id}")
        return data

    # Name-based lookup: search active+future first, then all
    for state in ("active,future", "active,future,closed"):
        sprints = get_board_sprints(client, board_id, state=state)
        ref_lower = sprint_ref.lower()
        matches = [s for s in sprints if ref_lower in s.get("name", "").lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(f"'{s['name']}'" for s in matches)
            raise ValueError(
                f"Sprint reference '{sprint_ref}' matched multiple sprints: {names}. "
                "Use a more specific name or the numeric sprint ID."
            )

    sprints_all = get_board_sprints(client, board_id)
    available = ", ".join(f"'{s['name']}'" for s in sprints_all) or "(none)"
    raise ValueError(f"No sprint found matching '{sprint_ref}'. Available sprints: {available}")


def get_sprint_issues(
    client: JiraClient,
    board_id: int,
    sprint_id: int,
    max_results: int = 50,
) -> list[dict]:
    """Return issues in the given sprint."""
    data = client.get(
        f"/rest/agile/1.0/board/{board_id}/sprint/{sprint_id}/issue",
        params={"maxResults": max_results},
    )
    return data.get("issues", [])


def move_to_sprint(client: JiraClient, sprint_id: int, issue_keys: list[str]) -> None:
    """Move one or more issues into the specified sprint."""
    client.post(
        f"/rest/agile/1.0/sprint/{sprint_id}/issue",
        payload={"issues": issue_keys},
    )


def move_to_kanban_board(client: JiraClient, board_id: int, issue_keys: list[str]) -> None:
    """Move one or more issues to a Kanban board (out of backlog zone)."""
    client.post(
        f"/rest/agile/1.0/board/{board_id}/issue",
        payload={"issues": issue_keys},
    )


def move_to_backlog(client: JiraClient, issue_keys: list[str]) -> None:
    """Move one or more issues to the board backlog (removes them from any sprint or Kanban board)."""
    client.post(
        "/rest/agile/1.0/backlog/issue",
        payload={"issues": issue_keys},
    )
