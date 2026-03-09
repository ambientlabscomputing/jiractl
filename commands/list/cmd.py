"""
jiractl list — tabular listing of Jira issues.

  jiractl list --project TCRM
  jiractl list --project TCRM --type Epic
  jiractl list --epic TCRM-1
  jiractl list --mine
  jiractl list --project TCRM --status "In Progress"
  jiractl list --project TCRM --format json
  jiractl list --mine --format bash
"""
import click

from jira_api.client import JiraClient
from jira_api.search import (
    get_epic_children,
    get_project_epics,
    get_project_issues,
    get_my_issues,
)
from commands.ui import console, format_option, print_issues


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
@format_option()
@click.pass_context
def list_issues(ctx, project, epic_key, issue_type, status, assignee, text, mine, epics_only, limit, output_format):
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
      jiractl list --project TCRM --format json
      jiractl list --mine --format bash
    """
    cfg = ctx.obj["config"]

    if not project and not epic_key and not mine:
        # Default: list all projects one line each
        if not cfg.allowed_projects:
            if output_format == "json":
                print("[]")
            elif output_format == "bash":
                print("# No allowed_projects configured.")
            else:
                console.print("[yellow]No allowed_projects configured.[/yellow]")
            return
        if output_format == "json":
            import json
            print(json.dumps([{"project": p, "aliases": cfg.synonyms.get(p, [])} for p in cfg.allowed_projects], indent=2))
        elif output_format == "bash":
            print("PROJECT\tALIASES")
            for p in cfg.allowed_projects:
                print(f"{p}\t{','.join(cfg.synonyms.get(p, []))}")
        else:
            console.print("\n[bold]Configured projects:[/bold]")
            for p in cfg.allowed_projects:
                synonyms = cfg.synonyms.get(p, [])
                syn_str = f"  (aliases: {', '.join(synonyms)})" if synonyms else ""
                console.print(f"  [cyan]{p}[/cyan]{syn_str}")
            console.print("\n[dim]Use --project PROJ to list issues, or --mine to see your issues.[/dim]")
        return

    use_status = console.status if output_format == "table" else _noop_status

    with JiraClient(cfg) as client:
        if epic_key:
            with use_status(f"Fetching children of {epic_key}..."):
                issues = get_epic_children(client, epic_key, max_results=limit)
            title = f"Children of {epic_key}"

        elif mine:
            with use_status("Fetching your issues..."):
                issues = get_my_issues(client, project_key=project, status=status, max_results=limit)
            title = "My Issues"

        elif epics_only:
            proj = (cfg.resolve_project(project) or project.upper()) if project else None
            if not proj:
                raise click.UsageError("--epics-only requires --project.")
            with use_status(f"Fetching epics in {proj}..."):
                issues = get_project_epics(client, proj, max_results=limit)
            title = f"Epics in {proj}"

        else:
            proj = (cfg.resolve_project(project) or project.upper()) if project else None
            if not proj:
                raise click.UsageError("Provide --project or --epic or --mine.")
            with use_status(f"Fetching issues in {proj}..."):
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
        if output_format == "json":
            print("[]")
        elif output_format == "bash":
            print("# No issues found.")
        else:
            console.print("[yellow]No issues found matching your criteria.[/yellow]")
        return

    print_issues(issues, title=title, fmt=output_format)


class _noop_status:
    def __init__(self, *args, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
