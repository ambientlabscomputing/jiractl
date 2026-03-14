import click
from rich.console import Console
from rich.table import Table

from jira_api.client import JiraClient
from jira_api.issues import get_project_issue_types

console = Console()


@click.group()
def config_group():
    """Manage jiractl configuration."""


@config_group.command("populate")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be written without saving.",
)
@click.pass_context
def populate(ctx, dry_run: bool):
    """
    Query Jira and populate issue types per project in jiractl.config.yaml.

    Connects to Jira using current credentials and discovers which issue types
    (e.g. Epic, Story, Task, Bug) are available in each allowed project, then
    writes the results back to jiractl.config.yaml under the `issue_types` key.
    """
    cfg = ctx.obj["config"]

    if not cfg.allowed_projects:
        console.print(
            "[yellow]No allowed_projects defined in config. Nothing to populate.[/yellow]"
        )
        return

    issue_types_map: dict[str, list[str]] = {}

    with JiraClient(cfg) as client:
        with console.status("Querying Jira for project issue types..."):
            for project_key in cfg.allowed_projects:
                try:
                    types = get_project_issue_types(client, project_key)
                    names: list[str] = [t["name"] for t in types]
                    issue_types_map[project_key] = names
                    console.print(
                        f"  [green]✓[/green] {project_key}: {', '.join(names)}"
                    )
                except Exception as e:
                    console.print(f"  [red]✗[/red] {project_key}: {e}")

    if not issue_types_map:
        console.print("[red]No issue types discovered. Config not updated.[/red]")
        return

    # Show summary table
    table = Table(title="Discovered Issue Types")
    table.add_column("Project", style="cyan")
    table.add_column("Issue Types", style="white")
    for proj, type_names in issue_types_map.items():
        table.add_row(proj, ", ".join(type_names))
    console.print(table)

    if dry_run:
        console.print("\n[yellow]Dry run — config not saved.[/yellow]")
        return

    # Merge into existing config and save
    cfg_dict = cfg.model_dump()
    cfg_dict["issue_types"] = issue_types_map
    from models.config import Config

    updated = Config(**cfg_dict)
    path = updated.save()
    console.print(f"\n[green]✓[/green] Config saved to [bold]{path}[/bold]")
