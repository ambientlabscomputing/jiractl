"""
jira_api/mutations.py — all write operations against the Jira REST API v3.

Covers:
  - Editing issue fields (summary, description, priority, assignee, labels)
  - Deleting issues
  - Fetching and applying status transitions
  - Adding comments (with optional AI-agent attribution banner)
  - Looking up the current user (for "assign to me")
"""
from __future__ import annotations

from datetime import datetime, timezone

from jira_api.client import JiraClient


# ---------------------------------------------------------------------------
# ADF helpers
# ---------------------------------------------------------------------------

def _text_node(text: str, bold: bool = False) -> dict:
    node: dict = {"type": "text", "text": text}
    if bold:
        node["marks"] = [{"type": "strong"}]
    return node


def _paragraph(*text_nodes: dict) -> dict:
    return {"type": "paragraph", "content": list(text_nodes)}


def _adf_doc(*block_nodes: dict) -> dict:
    return {"type": "doc", "version": 1, "content": list(block_nodes)}


def _plain_text_adf(text: str) -> dict:
    """Wrap plain text in a minimal ADF document."""
    if not text:
        return _adf_doc()
    return _adf_doc(_paragraph(_text_node(text)))


def _ai_banner_adf(body: str, agent_name: str) -> dict:
    """
    Build an ADF document that starts with a clearly-marked AI attribution
    blockquote, followed by the actual comment body.

    Renders in Jira like:

      > 🤖 AI Agent · Claude · 2026-03-08 14:32 UTC

      <body text>
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    banner_text = f"🤖 AI Agent · {agent_name} · {ts}"

    banner = {
        "type": "blockquote",
        "content": [
            _paragraph(_text_node(banner_text, bold=True))
        ],
    }

    # Body: split on newlines to produce separate paragraphs
    body_paragraphs = [
        _paragraph(_text_node(line)) if line.strip() else _paragraph(_text_node(" "))
        for line in body.splitlines()
    ] if body.strip() else [_paragraph(_text_node(body))]

    return _adf_doc(banner, *body_paragraphs)


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------

def get_myself(client: JiraClient) -> dict:
    """Return the Jira account dict for the authenticated user."""
    return client.get("/myself")


def find_user(client: JiraClient, query: str) -> list[dict]:
    """
    Search for users by display name, email, or account ID.
    Returns a list of user dicts: {accountId, displayName, emailAddress}.
    """
    return client.get("/user/search", params={"query": query, "maxResults": 10})


def resolve_assignee_id(client: JiraClient, value: str) -> str:
    """
    Resolve an assignee string to a Jira accountId.
    - "me"  → current user's accountId
    - anything else → first match from /user/search
    """
    if value.lower() == "me":
        return get_myself(client)["accountId"]
    results = find_user(client, value)
    if not results:
        raise ValueError(f"No Jira user found matching '{value}'")
    if len(results) > 1:
        names = ", ".join(f"{u['displayName']} <{u.get('emailAddress','')}>" for u in results)
        raise ValueError(
            f"Ambiguous assignee '{value}' — {len(results)} matches: {names}.\n"
            "Use a more specific name/email or pass the accountId directly."
        )
    return results[0]["accountId"]


# ---------------------------------------------------------------------------
# Edit issue fields
# ---------------------------------------------------------------------------

def edit_issue(
    client: JiraClient,
    issue_key: str,
    *,
    summary: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> None:
    """
    Update one or more fields on an existing Jira issue via PUT /issue/{key}.

    All arguments are keyword-only. Only the provided (non-None) fields are sent.
    Label changes are merged with the current label set.
    """
    if not any([summary, description, priority, assignee, add_labels, remove_labels]):
        raise ValueError("At least one field must be provided to edit.")

    fields: dict = {}

    if summary is not None:
        fields["summary"] = summary

    if description is not None:
        fields["description"] = _plain_text_adf(description)

    if priority is not None:
        fields["priority"] = {"name": priority}

    if assignee is not None:
        account_id = resolve_assignee_id(client, assignee)
        fields["assignee"] = {"accountId": account_id}

    if add_labels or remove_labels:
        # Fetch current labels first
        current = client.get(f"/issue/{issue_key}", params={"fields": "labels"})
        current_labels: set[str] = set(current.get("fields", {}).get("labels") or [])
        current_labels.update(add_labels or [])
        current_labels -= set(remove_labels or [])
        fields["labels"] = sorted(current_labels)

    client.put(f"/issue/{issue_key}", {"fields": fields})


# ---------------------------------------------------------------------------
# Delete issue
# ---------------------------------------------------------------------------

def delete_issue(client: JiraClient, issue_key: str, delete_subtasks: bool = False) -> None:
    """
    Permanently delete a Jira issue.
    Set delete_subtasks=True to also delete any linked sub-tasks.
    """
    params = ""
    if delete_subtasks:
        params = "?deleteSubtasks=true"
    client.delete(f"/issue/{issue_key}{params}")


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

def get_transitions(client: JiraClient, issue_key: str) -> list[dict]:
    """
    Return available transitions for an issue.
    Each dict: {id, name, to: {name: str}}.
    """
    data = client.get(f"/issue/{issue_key}/transitions")
    return data.get("transitions", [])


def transition_issue(client: JiraClient, issue_key: str, transition_id: str) -> None:
    """Apply a transition by its ID to move an issue to a new status."""
    client.post(f"/issue/{issue_key}/transitions", {"transition": {"id": transition_id}})


def find_transition(
    client: JiraClient, issue_key: str, target_status: str
) -> dict:
    """
    Find the transition whose destination status name matches target_status
    (case-insensitive). Raises ValueError if no match.
    """
    transitions = get_transitions(client, issue_key)
    needle = target_status.lower()
    matches = [t for t in transitions if t.get("to", {}).get("name", "").lower() == needle]
    if not matches:
        available = [t["to"]["name"] for t in transitions]
        raise ValueError(
            f"No transition to '{target_status}' available for {issue_key}.\n"
            f"Available statuses: {', '.join(available)}"
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

def add_comment(
    client: JiraClient,
    issue_key: str,
    body: str,
    agent_name: str | None = None,
) -> dict:
    """
    Add a comment to a Jira issue.

    If agent_name is provided the comment is prefixed with an AI attribution
    blockquote so reviewers can easily identify AI-generated content.
    """
    if agent_name:
        adf_body = _ai_banner_adf(body, agent_name)
    else:
        adf_body = _plain_text_adf(body)

    return client.post(f"/issue/{issue_key}/comment", {"body": adf_body})
