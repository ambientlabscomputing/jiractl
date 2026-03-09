"""
jiractl edit — update fields on an existing Jira issue.

  jiractl edit TCRM-1 --summary "New title"
  jiractl edit TCRM-1 --description "Updated description"
  jiractl edit TCRM-1 --priority High
  jiractl edit TCRM-1 --assignee me
  jiractl edit TCRM-1 --assignee "jane@example.com"
  jiractl edit TCRM-1 --add-label backend --remove-label frontend
  jiractl edit TCRM-1 --summary "New title" --priority High   # multiple at once
"""
import click
from rich.table import Table
from rich import box

from jira_api.client import JiraClient
from jira_api.mutations import edit_issue
from commands.ui import console, format_option

_PRIORITIES = ("Highest", "High", "Medium", "Low", "Lowest")


@click.command("edit")
@click.argument("issue_key")
@click.option("--summary", default=None, help="New summary / title.")
@click.option("--description", default=None, help="New description (plain text).")
@click.option(
    "--priority",
    default=None,
    type=click.Choice(_PRIORITIES, case_sensitive=False),
    help="New priority level.",
)
@click.option(
    "--assignee",
    default=None,
    help="Assign to display name, email, accountId, or 'me'.",
)
@click.option(
    "--add-label",
    "add_labels",
    multiple=True,
    help="Add a label (repeatable: --add-label foo --add-label bar).",
)
@click.option(
    "--remove-label",
    "remove_labels",
    multiple=True,
    help="Remove a label (repeatable).",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview changes without applying them.")
@format_option()
@click.pass_context
def edit(ctx, issue_key, summary, description, priority, assignee, add_labels, remove_labels, dry_run, output_format):
    """
    Edit fields on an existing Jira issue.

    At least one field flag must be provided.  Multiple flags may be combined
    in a single call — they are applied atomically via a single API request.

    \b
    Examples:
      jiractl edit TCRM-1 --summary "Fix booking flow"
      jiractl edit TCRM-1 --priority High --assignee me
      jiractl edit TCRM-1 --add-label ai-generated --remove-label wont-fix
      jiractl edit TCRM-1 --description "New context" --dry-run
    """
    if not any([summary, description, priority, assignee, add_labels, remove_labels]):
        raise click.UsageError("Provide at least one field to change (--summary, --description, --priority, --assignee, --add-label, --remove-label).")

    changes: dict = {}
    if summary:
        changes["summary"] = summary
    if description:
        changes["description"] = description
    if priority:
        changes["priority"] = priority
    if assignee:
        changes["assignee"] = assignee
    if add_labels:
        changes["add_labels"] = list(add_labels)
    if remove_labels:
        changes["remove_labels"] = list(remove_labels)

    if dry_run:
        if output_format == "json":
            import json
            print(json.dumps({"issue": issue_key, "dry_run": True, "changes": changes}, indent=2))
        elif output_format == "bash":
            for k, v in changes.items():
                print(f"{k}\t{v}")
        else:
            table = Table(title=f"[dim]Dry run — changes for[/dim] [cyan]{issue_key}[/cyan]",
                          box=box.ROUNDED, border_style="dim")
            table.add_column("Field", style="bold")
            table.add_column("New Value")
            for k, v in changes.items():
                table.add_row(k, str(v))
            console.print(table)
            console.print("[dim]No changes applied (--dry-run).[/dim]")
        return

    cfg = ctx.obj["config"]
    use_status = console.status if output_format == "table" else _noop_status

    with JiraClient(cfg) as client:
        with use_status(f"Updating {issue_key}..."):
            edit_issue(
                client,
                issue_key,
                summary=summary or None,
                description=description or None,
                priority=priority or None,
                assignee=assignee or None,
                add_labels=list(add_labels) if add_labels else None,
                remove_labels=list(remove_labels) if remove_labels else None,
            )

    if output_format == "json":
        import json
        print(json.dumps({"issue": issue_key, "updated": True, "changes": changes}, indent=2))
    elif output_format == "bash":
        print(f"UPDATED\t{issue_key}")
        for k, v in changes.items():
            print(f"{k}\t{v}")
    else:
        console.print(f"[green]✓[/green] Updated [cyan]{issue_key}[/cyan]")
        for field, val in changes.items():
            console.print(f"  [dim]{field}[/dim] → {val}")


class _noop_status:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
