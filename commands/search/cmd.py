"""
jiractl search — search Jira issues with raw JQL or a query builder.

  jiractl search "project = TCRM AND status = 'In Progress'"
  jiractl search --project TCRM --type Story --status "In Progress"
  jiractl search --text "booking payment" --project TCRM
"""
import click
from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich import box

from jira_api.client import JiraClient
from jira_api.search import search_all, adf_to_text
from commands.describe.cmd import _display_name, _fmt_date, _status_style, _priority_style

console = Console()


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
    return " AND ".join(parts or ['project is not EMPTY']) + " ORDER BY updated DESC"


def _render_table(issues: list[dict], title: str) -> None:
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        row_styles=["", "dim"],
        expand=False,
    )
    table.add_column("Key", style="bold cyan", no_wrap=True, min_width=10)
    table.add_column("Project", no_wrap=True, min_width=6)
    table.add_column("Type", no_wrap=True, min_width=8)
    table.add_column("Summary", min_width=44)
    table.add_column("Status", no_wrap=True, min_width=12)
    table.add_column("Priority", no_wrap=True, min_width=8)
    table.add_column("Assignee", min_width=14)
    table.add_column("Updated", no_wrap=True, min_width=10)

    for issue in issues:
        f = issue.get("fields", {})
        key = issue.get("key", "?")
        proj = f.get("project", {}).get("key", "?")
        itype = f.get("issuetype", {}).get("name", "?")
        summary = (f.get("summary") or "")[:60]
        status = f.get("status", {}).get("name", "?")
        priority = (f.get("priority") or {}).get("name", "—")
        assignee = _display_name(f.get("assignee"))
        updated = _fmt_date(f.get("updated"))

        s = _status_style(status)
        p = _priority_style(priority)

        table.add_row(
            key, proj, itype, summary,
            f"[{s}]{status}[/{s}]",
            f"[{p}]{priority}[/{p}]",
            assignee, updated,
        )

    console.print(table)
    console.print(f"[dim]{len(issues)} result(s)[/dim]")


@click.command("search")
@click.argument("jql_query", required=False, default=None)
@click.option("-p", "--project", default=None, help="Filter by project key.")
@click.option("-t", "--type", "issue_type", default=None, help="Filter by issue type.")
@click.option("-s", "--status", default=None, help="Filter by status.")
@click.option("-a", "--assignee", default=None, help="Filter by assignee ('me' = current user).")
@click.option("--text", default=None, help="Full-text search.")
@click.option("--label", default=None, help="Filter by label.")
@click.option("--since", default=None, help="Updated after this date e.g. '2026-01-01'.")
@click.option("-n", "--limit", default=50, show_default=True, help="Max results.")
@click.option("--show-jql", is_flag=True, default=False, help="Print the JQL used before running.")
@click.pass_context
def search(ctx, jql_query, project, issue_type, status, assignee, text, label, since, limit, show_jql):
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
    """
    cfg = ctx.obj["config"]

    # Resolve project synonym
    if project:
        project = cfg.resolve_project(project) or project.upper()

    if jql_query and not any([project, issue_type, status, assignee, text, label, since]):
        # Pure raw JQL mode
        final_jql = jql_query.strip()
    elif jql_query:
        # Combine raw JQL with structured filters by wrapping in AND
        structured = _build_jql(project, issue_type, status, assignee, text, label, since)
        # Remove the ORDER BY from structured and append raw
        structured_no_order = structured.rsplit(" ORDER BY ", 1)[0]
        final_jql = f"({jql_query.strip()}) AND ({structured_no_order}) ORDER BY updated DESC"
    else:
        final_jql = _build_jql(project, issue_type, status, assignee, text, label, since)

    if show_jql:
        console.print(Syntax(final_jql, "sql", theme="monokai", word_wrap=True))

    with JiraClient(cfg) as client:
        with console.status("Searching..."):
            issues = search_all(client, final_jql, page_size=min(limit, 100))
            issues = issues[:limit]

    if not issues:
        console.print("[yellow]No results.[/yellow]")
        return

    _render_table(issues, title=f"Search results ({len(issues)} found)")
