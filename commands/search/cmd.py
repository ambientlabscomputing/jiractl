"""
jiractl search — search Jira issues with raw JQL or a query builder.

  jiractl search "project = TCRM AND status = 'In Progress'"
  jiractl search --project TCRM --type Story --status "In Progress"
  jiractl search --text "booking payment" --project TCRM
  jiractl search --project TCRM --format json
  jiractl search --assignee me --format bash
"""

import click
from rich.syntax import Syntax

from commands._client import make_client
from commands.ui import console, format_option, print_issues
from jira_api.search import search_all


def _build_jql(
    project: str | None,
    issue_type: str | None,
    status: str | None,
    assignee: str | None,
    text: str | None,
    label: str | None,
    updated_after: str | None,
) -> str:
    """Build a JQL string from structured filter options."""
    parts: list[str] = []
    if project:
        parts.append(f'project = "{project}"')
    if issue_type:
        parts.append(f'issuetype = "{issue_type}"')
    if status:
        parts.append(f'status = "{status}"')
    if assignee:
        if assignee.lower() == "me":
            parts.append("assignee = currentUser()")
        else:
            parts.append(f'assignee = "{assignee}"')
    if label:
        parts.append(f'labels = "{label}"')
    if updated_after:
        parts.append(f'updated >= "{updated_after}"')
    if text:
        parts.append(f'text ~ "{text}"')
    return " AND ".join(parts or ["project is not EMPTY"]) + " ORDER BY updated DESC"


@click.command("search")
@click.argument("jql_query", required=False, default=None)
@click.option("-p", "--project", default=None, help="Filter by project key.")
@click.option("-t", "--type", "issue_type", default=None, help="Filter by issue type.")
@click.option("-s", "--status", default=None, help="Filter by status.")
@click.option(
    "-a", "--assignee", default=None, help="Filter by assignee ('me' = current user)."
)
@click.option("--text", default=None, help="Full-text search.")
@click.option("--label", default=None, help="Filter by label.")
@click.option(
    "--since", default=None, help="Updated after this date e.g. '2026-01-01'."
)
@click.option("-n", "--limit", default=50, show_default=True, help="Max results.")
@click.option(
    "--show-jql", is_flag=True, default=False, help="Print the JQL used before running."
)
@format_option()
@click.pass_context
def search(
    ctx,
    jql_query,
    project,
    issue_type,
    status,
    assignee,
    text,
    label,
    since,
    limit,
    show_jql,
    output_format,
):
    """
    Search Jira issues with raw JQL or a structured query builder.

    Pass a raw JQL string as an argument, or use flags to build a query.
    Flags are combined with AND and added to a raw JQL argument if both provided.

    \b
    Examples:
      jiractl search "project = TCRM AND status = 'In Progress'"
      jiractl search --project TCRM --type Epic
      jiractl search --text "booking" --project TCRM --status "To Do"
      jiractl search --assignee me --status "In Progress"
      jiractl search --project TCRM --since 2026-01-01
      jiractl search --project TCRM --format json
      jiractl search --assignee me --format bash
    """
    cfg = ctx.obj["config"]

    # Resolve project synonym
    if project:
        project = cfg.resolve_project(project) or project.upper()

    if jql_query and not any(
        [project, issue_type, status, assignee, text, label, since]
    ):
        final_jql = jql_query.strip()
    elif jql_query:
        structured = _build_jql(
            project, issue_type, status, assignee, text, label, since
        )
        structured_no_order = structured.rsplit(" ORDER BY ", 1)[0]
        final_jql = (
            f"({jql_query.strip()}) AND ({structured_no_order}) ORDER BY updated DESC"
        )
    else:
        final_jql = _build_jql(
            project, issue_type, status, assignee, text, label, since
        )

    if show_jql and output_format == "table":
        console.print(Syntax(final_jql, "sql", theme="monokai", word_wrap=True))
    elif show_jql:
        print(f"-- JQL: {final_jql}")

    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:
        with use_status("Searching..."):
            issues = search_all(client, final_jql, page_size=min(limit, 100))
            issues = issues[:limit]

    if not issues:
        if output_format == "json":
            print("[]")
        elif output_format == "bash":
            print("# No results.")
        else:
            console.print("[yellow]No results.[/yellow]")
        return

    print_issues(
        issues,
        title=f"Search results ({len(issues)} found)",
        fmt=output_format,
        include_project=True,
    )


class _noop_status:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
