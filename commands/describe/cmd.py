"""
jiractl describe — display a Jira issue or epic with its children.

  jiractl describe TCRM-1                        # describe a single issue
  jiractl describe TCRM-1 --children             # describe epic + list children
  jiractl describe --epic TCRM-1                 # alias for --children on an epic
  jiractl describe TCRM-2 --parent               # describe TCRM-2's parent epic
  jiractl describe TCRM-1 --children --format json
  jiractl describe TCRM-1 --children --format bash
"""

import json as _json
import sys

import click

from commands.ui import console, format_option, print_issue_detail
from jira_api.client import JiraClient
from jira_api.search import get_epic_children, get_issue

# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@click.command("describe")
@click.argument("issue_key", required=False, default=None)
@click.option(
    "--epic",
    "epic_key",
    default=None,
    help="Describe an epic and list all child issues.",
)
@click.option(
    "--children",
    is_flag=True,
    default=False,
    help="Also fetch and list child issues (auto-set when issue is an Epic).",
)
@click.option(
    "--parent",
    "show_parent",
    is_flag=True,
    default=False,
    help="Describe the issue's parent epic instead of the issue itself.",
)
@click.option(
    "--comments", is_flag=True, default=False, help="Show recent comments on the issue."
)
@format_option()
@click.pass_context
def describe(ctx, issue_key, epic_key, children, show_parent, comments, output_format):
    """
    Display a detailed view of a Jira issue.

    Pass an issue key directly, or use --epic to describe an epic and list
    all of its child stories/tasks.  Use --parent to describe the issue's
    parent epic instead.

    \b
    Examples:
      jiractl describe TCRM-1
      jiractl describe TCRM-1 --children
      jiractl describe TCRM-1 --comments
      jiractl describe --epic TCRM-1
      jiractl describe TCRM-2 --parent
      jiractl describe TCRM-1 --children --format json
      jiractl describe TCRM-1 --children --format bash
    """
    cfg = ctx.obj["config"]

    # Resolve the target key
    target_key = epic_key or issue_key
    if not target_key:
        raise click.UsageError(
            "Provide an issue key (e.g. TCRM-1) or use --epic TCRM-1"
        )

    # Suppress status spinners for non-table formats so stdout stays clean
    status_ctx = console.status if output_format == "table" else _noop_status

    with JiraClient(cfg) as client:
        with status_ctx(f"Fetching {target_key}..."):
            issue = get_issue(client, target_key)

        # --parent: resolve and switch the target to the parent epic
        if show_parent:
            parent_key = _resolve_parent_key(issue)
            if parent_key is None:
                _emit_no_parent(issue, output_format)
                return
            with status_ctx(f"Fetching parent {parent_key}..."):
                issue = get_issue(client, parent_key)
            target_key = parent_key

        # Determine whether to load children
        is_epic = (
            issue.get("fields", {}).get("issuetype", {}).get("name", "").lower()
            == "epic"
        )
        want_children = bool(epic_key or children or is_epic)

        child_issues: list[dict] | None = None
        if want_children:
            with status_ctx(f"Fetching child issues of {target_key}..."):
                child_issues = get_epic_children(client, target_key)

    print_issue_detail(
        issue,
        output_format,
        show_comments=comments,
        children=child_issues,
    )


# ---------------------------------------------------------------------------
# Parent helpers
# ---------------------------------------------------------------------------


def _resolve_parent_key(issue: dict) -> str | None:
    """
    Return the parent issue key for *issue*, or None when:
      - the issue is itself an Epic (no meaningful parent epic to display), or
      - no parent field is set on the issue.
    """
    fields = issue.get("fields", {}) or {}
    issue_type = (fields.get("issuetype") or {}).get("name", "").lower()
    if issue_type == "epic":
        return None
    parent = fields.get("parent") or {}
    return parent.get("key") or None


def _emit_no_parent(issue: dict, fmt: str) -> None:
    """Friendly 'no parent' output for each format. Always exits cleanly (code 0)."""
    key = issue.get("key", "?")
    fields = issue.get("fields", {}) or {}
    issue_type = (fields.get("issuetype") or {}).get("name", "")
    is_epic = issue_type.lower() == "epic"

    if is_epic:
        message = f"{key} is an Epic — it has no parent epic to describe."
    else:
        message = f"{key} has no parent epic set."

    if fmt == "json":
        _json.dump(
            {
                "key": key,
                "issue_type": issue_type,
                "parent": None,
                "is_epic": is_epic,
                "message": message,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    elif fmt == "bash":
        print(f"NO_PARENT\t{key}\t{issue_type}")
    else:
        console.print(f"[yellow]{message}[/yellow]")


class _noop_status:
    """Context manager that does nothing — replaces console.status for non-rich formats."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
