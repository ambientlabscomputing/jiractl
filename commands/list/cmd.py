"""
jiractl list — tabular listing of Jira issues.

  jiractl list --project TCRM
  jiractl list --project TCRM --type Epic
  jiractl list --epic TCRM-1
  jiractl list --mine
  jiractl list --project TCRM --status "In Progress"
"""
import click
from rich.console import Console
from rich.table import Table
from rich import box

from jira_api.client import JiraClient
from jira_api.search import (
    get_epic_children,
    get_project_epics,
    get_project_issues,
    get_my_issues,
    adf_to_text,
)
from commands.describe.cmd import (
    _display_name,
    _fmt_date,
    _status_style,
    _priority_style,
)

console = Console()


def _issues_table(issues: list[dict], title: str = "Issues") -> Table:
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
    table.add_column("Type", no_wrap=True, min_width=8)
    table.add_column("Summary", min_width=44)
    table.add_column("Status", no_wrap=True, min_width=12)
    table.add_column("Priority", no_wrap=True, min_width=8)
    table.add_column("Assignee", min_width=14)
    table.add_column("Updated", no_wrap=True, min_width=10)

    for issue in issues:
        f = issue.get("fields", {})
        key = issue.get("key", "?")
        itype = f.get("issuetype", {}).get("name", "?")
        summary = (f.get("summary") or "")[:64]
        status = f.get("status", {}).get("name", "?")
        priority = (f.get("priority") or {}).get("name", "—")
        assignee = _display_name(f.get("assignee"))
        updated = _fmt_date(f.get("updated"))

        s = _status_style(status)
        p = _priority_style(priority)

        table.add_row(
            key,
            itype,
            summary,
            f"[{s}]{status}[/{s}]",
            f"[{p}]{priority}[/{p}]",
            assignee,
            updated,
        )

    return table


@click.command("list")
@click.option("-p", "--project", default=None, help="Filter by project key.")
@click.option("--epic", "epic_key", default=None, help="List child issues of an epic.")
@click.option("-t", "--type", "issue_type", default=None, help="Filter by issue type (Epic, Story, Task, Bug, …).")
@click.option("-s", "--status", default=None, help="Filter by status (e.g. 'In Progress').")
@click.option("--assignee", default=None, help="Filter by assignee display name or account ID.")
@click.option("--text", default=None, help="Full-text search within issues.")
@click.option("--mine", is_flag=True, default=False, help="Show only issues assigned to you.")
@click.option("--epics-only", is_flag=True, default=False, help="List only epics in the project.")
@click.option("-n", "--limit", default=50, show_default=True, help="Max results to show.")
@click.pass_context
def list_issues(ctx, project, epic_key, issue_type, status, assignee, text, mine, epics_only, limit):
    """
    List Jira issues with optional filtering.

    \b
    Examples:
      jiractl list --project TCRM
      jiractl list --project TCRM --type Epic
      jiractl list --project TCRM --status "In Progress"
      jiractl list --epic TCRM-1
      jiractl list --mine
      jiractl list --project TCRM --epics-only
    """
    cfg = ctx.obj["config"]

    if not project and not epic_key and not mine:
        # Default: list all projects one line each
        if not cfg.allowed_projects:
            console.print("[yellow]No allowed_projects configured.[/yellow]")
            return
        console.print("\n[bold]Configured projects:[/bold]")
        for p in cfg.allowed_projects:
            synonyms = cfg.synonyms.get(p, [])
            syn_str = f"  (aliases: {', '.join(synonyms)})" if synonyms else ""
            console.print(f"  [cyan]{p}[/cyan]{syn_str}")
        console.print("\n[dim]Use --project PROJ to list issues, or --mine to see your issues.[/dim]")
        return

    with JiraClient(cfg) as client:
        if epic_key:
            with console.status(f"Fetching children of {epic_key}..."):
                issues = get_epic_children(client, epic_key, max_results=limit)
            title = f"Children of {epic_key}"

        elif mine:
            with console.status("Fetching your issues..."):
                issues = get_my_issues(client, project_key=project, status=status, max_results=limit)
            title = "My Issues"

        elif epics_only:
            proj = (cfg.resolve_project(project) or project.upper()) if project else None
            if not proj:
                raise click.UsageError("--epics-only requires --project.")
            with console.status(f"Fetching epics in {proj}..."):
                issues = get_project_epics(client, proj, max_results=limit)
            title = f"Epics in {proj}"

        else:
            proj = (cfg.resolve_project(project) or project.upper()) if project else None
            if not proj:
                raise click.UsageError("Provide --project or --epic or --mine.")
            with console.status(f"Fetching issues in {proj}..."):
                issues = get_project_issues(
                    client,
                    proj,
                    issue_type=issue_type,
                    status=status,
                    assignee=assignee,
                    text=text,
                    max_results=limit,
                )
            type_label = f" [{issue_type}]" if issue_type else ""
            title = f"{proj}{type_label} — {len(issues)} issues"

    if not issues:
        console.print("[yellow]No issues found matching your criteria.[/yellow]")
        return

    console.print(_issues_table(issues, title=title))
    console.print(f"\n[dim]{len(issues)} issue(s) listed.[/dim]")
