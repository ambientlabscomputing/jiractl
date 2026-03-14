"""
jiractl export — export non-completed Jira issues to CSV.

  jiractl export --project TCRM
  jiractl export --project TCRM --output issues.csv
  jiractl export --project TCRM --type Story
  jiractl export --project TCRM --assignee me
  jiractl export --project TCRM --include-description
"""
import csv
import sys

import click

from jira_api.client import JiraClient
from jira_api.search import search_all, adf_to_text
from commands.ui import console, flatten_issue

# Statuses that count as "completed" — excluded by default
_DONE_STATUSES = ("Done", "Closed", "Resolved", "Cancelled", "Won't Do")

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


def _build_jql(
    project: str | None,
    issue_type: str | None,
    assignee: str | None,
) -> str:
    """Build JQL that excludes completed statuses."""
    done = ", ".join(f'"{s}"' for s in _DONE_STATUSES)
    parts = [f"status not in ({done})"]

    if project:
        parts.append(f'project = "{project}"')
    if issue_type:
        parts.append(f'issuetype = "{issue_type}"')
    if assignee:
        if assignee.lower() == "me":
            parts.append("assignee = currentUser()")
        else:
            parts.append(f'assignee = "{assignee}"')

    return " AND ".join(parts) + " ORDER BY updated DESC"


@click.command("export")
@click.option("-p", "--project", default=None, help="Filter by project key.")
@click.option("-t", "--type", "issue_type", default=None, help="Filter by issue type (Epic, Story, Task, Bug, …).")
@click.option("-a", "--assignee", default=None, help="Filter by assignee display name or 'me'.")
@click.option("-o", "--output", "output_file", default=None, help="Write CSV to this file path (default: stdout).")
@click.option("--include-description", is_flag=True, default=False, help="Include the issue description column.")
@click.pass_context
def export(ctx, project, issue_type, assignee, output_file, include_description):
    """
    Export all non-completed Jira issues to CSV.

    Issues with status Done, Closed, Resolved, Cancelled, or Won't Do are
    excluded. Use --project, --type, and --assignee to narrow results.

    \b
    Examples:
      jiractl export --project TCRM
      jiractl export --project TCRM --output backlog.csv
      jiractl export --project TCRM --type Story --assignee me
      jiractl export --project TCRM --include-description
    """
    cfg = ctx.obj["config"]

    if project:
        project = cfg.resolve_project(project) or project.upper()

    jql = _build_jql(project, issue_type, assignee)

    with JiraClient(cfg) as client:
        with console.status("Fetching issues..."):
            issues = search_all(client, jql)

    if not issues:
        console.print("[yellow]No non-completed issues found.[/yellow]")
        return

    columns = _CSV_COLUMNS_WITH_DESC if include_description else _CSV_COLUMNS

    def _write(writer_dest):
        writer = csv.DictWriter(writer_dest, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for issue in issues:
            row = flatten_issue(issue, include_description=include_description)
            if include_description:
                # flatten_issue already populates 'description' when include_description=True
                pass
            writer.writerow(row)

    if output_file:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            _write(f)
        console.print(f"[green]✓[/green] Exported {len(issues)} issues to [bold]{output_file}[/bold]")
    else:
        _write(sys.stdout)
