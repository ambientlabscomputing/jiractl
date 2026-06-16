"""
jiractl create — create Jira issues interactively or via flags.

  jiractl create epic   --project TCRM --summary "My Epic"
  jiractl create ticket --project TCRM --epic TCRM-1 --summary "My Story"
"""

import click
from rich.console import Console
from rich.panel import Panel

from jiractl.commands._client import make_client
from jiractl.jira_api.issues import create_epic, create_story, resolve_issue_type_name

console = Console()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _pick_project(config, project_flag: str | None) -> str:
    """Resolve project key from flag, prompt otherwise."""
    if project_flag:
        key = config.resolve_project(project_flag) or project_flag.upper()
        if key not in config.allowed_projects:
            console.print(f"[yellow]Warning: '{key}' is not in allowed_projects[/yellow]")
        return key
    choices = config.allowed_projects
    console.print("Available projects: " + ", ".join(f"[cyan]{p}[/cyan]" for p in choices))
    val = click.prompt("Project key")
    return (config.resolve_project(val) or val).upper()


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group()
def create():
    """Create Jira issues (epics, tickets)."""


# ---------------------------------------------------------------------------
# create epic
# ---------------------------------------------------------------------------


@create.command("epic")
@click.option("-p", "--project", default=None, help="Project key (e.g. TCRM)")
@click.option("-s", "--summary", default=None, help="Epic summary / title")
@click.option(
    "-d",
    "--description",
    default="",
    help="Epic description (plain text)",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@click.pass_context
def create_epic_cmd(ctx, project, summary, description, dry_run):
    """
    Create a single Epic in Jira.

    Prompts for any required fields not supplied via flags.

    \b
    Examples:
      jiractl create epic --project TCRM --summary "Provider Management"
      jiractl create epic -p TCRM -s "Payments" -d "Handles all payment flows"
    """
    cfg = ctx.obj["config"]
    project_key = _pick_project(cfg, project)

    if not summary:
        summary = click.prompt("Epic summary")

    if not description:
        description = click.prompt("Description (optional)", default="", show_default=False)

    console.print(
        Panel(
            f"[bold]{summary}[/bold]\n\n{description or '[dim]No description[/dim]'}",
            title=f"[cyan]{project_key}[/cyan] · Epic",
            border_style="cyan",
        )
    )

    if dry_run:
        console.print("[yellow]Dry run — not creating.[/yellow]")
        return

    with make_client(ctx) as client:
        with console.status("Creating epic..."):
            key = create_epic(
                client,
                project_key=project_key,
                epic_name=summary,
                summary=summary,
                description=description,
            )

    url = f"{cfg.base_url}/browse/{key}"
    console.print(f"[green]✓[/green] Created epic [bold cyan]{key}[/bold cyan]  {url}")


# ---------------------------------------------------------------------------
# create ticket
# ---------------------------------------------------------------------------


@create.command("ticket")
@click.option("-p", "--project", default=None, help="Project key (e.g. TCRM)")
@click.option("-e", "--epic", "epic_key", default=None, help="Parent epic key (e.g. TCRM-1)")
@click.option("-s", "--summary", default=None, help="Ticket summary")
@click.option("-d", "--description", default="", help="Ticket description (plain text)")
@click.option(
    "-t",
    "--type",
    "issue_type",
    default="Story",
    show_default=True,
    help="Issue type (Story, Task, Bug, …)",
)
@click.option("--dry-run", is_flag=True, help="Preview without creating.")
@click.pass_context
def create_ticket_cmd(ctx, project, epic_key, summary, description, issue_type, dry_run):
    """
    Create a Story/Task/Bug in Jira, optionally linked to an Epic.

    Prompts for any required fields not supplied via flags.

    \b
    Examples:
      jiractl create ticket --project TCRM --epic TCRM-1 --summary "Booking UI"
      jiractl create ticket -p TCRM -e TCRM-1 -s "Payments" -t Bug
    """
    cfg = ctx.obj["config"]
    project_key = _pick_project(cfg, project)

    if not epic_key:
        epic_key = click.prompt("Parent epic key (leave blank to skip)", default="", show_default=False) or None

    if not summary:
        summary = click.prompt("Ticket summary")

    if not description:
        description = click.prompt("Description (optional)", default="", show_default=False)

    parent_line = f"[dim]Parent:[/dim] {epic_key}" if epic_key else "[dim]No parent epic[/dim]"
    console.print(
        Panel(
            f"[bold]{summary}[/bold]\n{parent_line}\n\n{description or '[dim]No description[/dim]'}",
            title=f"[cyan]{project_key}[/cyan] · {issue_type}",
            border_style="cyan",
        )
    )

    if dry_run:
        console.print("[yellow]Dry run — not creating.[/yellow]")
        return

    with make_client(ctx) as client:
        with console.status(f"Creating {issue_type}..."):
            if epic_key:
                key = create_story(
                    client,
                    project_key=project_key,
                    summary=summary,
                    description=description,
                    epic_key=epic_key,
                )
            else:
                # No parent — create as standalone using whichever type resolves
                resolved_type = resolve_issue_type_name(client, project_key, issue_type)
                from jiractl.jira_api.issues import _description_as_adf

                payload = {
                    "fields": {
                        "project": {"key": project_key},
                        "issuetype": {"name": resolved_type},
                        "summary": summary,
                        "description": _description_as_adf(description),
                    }
                }
                result = client.post("/issue", payload)
                key = result["key"]

    url = f"{cfg.base_url}/browse/{key}"
    console.print(f"[green]✓[/green] Created {issue_type} [bold cyan]{key}[/bold cyan]  {url}")
