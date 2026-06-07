"""
jiractl export — export Jira issues to CSV (non-completed by default).

  jiractl export --project TCRM
  jiractl export --project TCRM --output issues.csv
  jiractl export --project TCRM --type Story
  jiractl export --project TCRM --assignee me
  jiractl export --project TCRM --include-description
  jiractl export --project TCRM --status 'To Do,In Progress'
"""

import csv
import sys

import click

from jiractl.commands._client import make_client
from jiractl.commands.ui import console, flatten_issue
from jiractl.jira_api.search import search_all

# Statuses that count as "completed" — excluded by default
# Keywords — an issue is considered "completed" if its status *contains*
# any of these (case-insensitive), e.g. "Done / Released" matches "done".
_DONE_KEYWORDS = ("done", "closed", "resolved", "cancelled", "won't do")

# CSV column order
_CSV_COLUMNS = [
    "key",
    "project",
    "type",
    "summary",
    "status",
    "priority",
    "assignee",
    "reporter",
    "parent",
    "labels",
    "created",
    "updated",
    "url",
]
_CSV_COLUMNS_WITH_DESC = _CSV_COLUMNS + ["description"]


def _is_completed(issue: dict) -> bool:
    """Return True if the issue's status contains a done-like keyword."""
    status = (issue.get("fields", {}).get("status", {}).get("name") or "").lower()
    return any(kw in status for kw in _DONE_KEYWORDS)


def _build_jql(
    project: str | None,
    issue_type: str | None,
    assignee: str | None,
    statuses: list[str] | None = None,
) -> str:
    """Build JQL for fetching issues."""
    parts: list[str] = []

    if project:
        parts.append(f'project = "{project}"')
    if issue_type:
        parts.append(f'issuetype = "{issue_type}"')
    if assignee:
        if assignee.lower() == "me":
            parts.append("assignee = currentUser()")
        else:
            parts.append(f'assignee = "{assignee}"')
    if statuses:
        quoted = ", ".join(f'"{s}"' for s in statuses)
        parts.append(f"status in ({quoted})")

    return " AND ".join(parts or ["project is not EMPTY"]) + " ORDER BY updated DESC"


@click.command("export")
@click.option("-p", "--project", default=None, help="Filter by project key.")
@click.option(
    "-t",
    "--type",
    "issue_type",
    default=None,
    help="Filter by issue type (Epic, Story, Task, Bug, …).",
)
@click.option("-a", "--assignee", default=None, help="Filter by assignee display name or 'me'.")
@click.option(
    "-s",
    "--status",
    "status_filter",
    default=None,
    help="Filter by status (single or comma-separated list). Defaults to excluding completed statuses.",
)
@click.option(
    "-o",
    "--output",
    "output_file",
    default=None,
    help="Write CSV to this file path (default: stdout).",
)
@click.option(
    "--include-description",
    is_flag=True,
    default=False,
    help="Include the issue description column.",
)
@click.pass_context
def export(ctx, project, issue_type, assignee, status_filter, output_file, include_description):
    """
    Export all non-completed Jira issues to CSV.

    Issues with status Done, Closed, Resolved, Cancelled, or Won't Do are
    excluded by default. Use --status to filter to specific statuses.
    Use --project, --type, and --assignee to narrow results.

    \b
    Examples:
      jiractl export --project TCRM
      jiractl export --project TCRM --output backlog.csv
      jiractl export --project TCRM --type Story --assignee me
      jiractl export --project TCRM --include-description
      jiractl export --project TCRM --status 'To Do,In Progress'
      jiractl export --project TCRM --status Done
    """
    cfg = ctx.obj["config"]

    if project:
        project = cfg.resolve_project(project) or project.upper()

    statuses = [s.strip() for s in status_filter.split(",")] if status_filter else None
    jql = _build_jql(project, issue_type, assignee, statuses)

    with make_client(ctx) as client:
        with console.status("Fetching issues..."):
            issues = search_all(client, jql)

    # When no explicit status filter is given, exclude completed issues client-side
    # (handles compound statuses like "Done / Released" that need substring matching)
    if not statuses:
        issues = [i for i in issues if not _is_completed(i)]

    if not issues:
        console.print("[yellow]No issues found.[/yellow]")
        return

    columns = _CSV_COLUMNS_WITH_DESC if include_description else _CSV_COLUMNS

    def _write(writer_dest):
        writer = csv.DictWriter(writer_dest, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for issue in issues:
            row = flatten_issue(issue, include_description=include_description)
            writer.writerow(row)

    if output_file:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            _write(f)
        console.print(f"[green]✓[/green] Exported {len(issues)} issues to [bold]{output_file}[/bold]")
    else:
        _write(sys.stdout)
