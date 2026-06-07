"""
jiractl delete — permanently delete a Jira issue.

  jiractl delete TCRM-1
  jiractl delete TCRM-1 --yes            # skip confirmation prompt
  jiractl delete TCRM-1 --subtasks       # also delete sub-tasks
"""

import click

from jiractl.commands._client import make_client
from jiractl.commands.ui import console, format_option
from jiractl.jira_api.mutations import delete_issue


@click.command("delete")
@click.argument("issue_key")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.option("--subtasks", is_flag=True, default=False, help="Also delete linked sub-tasks.")
@format_option()
@click.pass_context
def delete(ctx, issue_key, yes, subtasks, output_format):
    """
    Permanently delete a Jira issue.

    Deletion is irreversible.  You will be asked to confirm unless --yes is
    passed (useful for scripting and agentic workflows).

    \b
    Examples:
      jiractl delete TCRM-99
      jiractl delete TCRM-99 --yes
      jiractl delete TCRM-99 --subtasks --yes
      jiractl delete TCRM-99 --format json
    """
    if not yes:
        subtask_note = "  This will also delete all sub-tasks.\n" if subtasks else ""
        if output_format != "table":
            # Non-interactive path: require --yes for machine formats
            raise click.UsageError(f"Pass --yes to confirm deletion of {issue_key} in non-interactive mode.")
        click.confirm(
            f"\n  {subtask_note}  Delete [bold]{issue_key}[/bold] — are you sure?",
            abort=True,
        )

    ctx.obj["config"]

    with make_client(ctx) as client:
        delete_issue(client, issue_key, delete_subtasks=subtasks)

    if output_format == "json":
        import json

        print(json.dumps({"issue": issue_key, "deleted": True, "subtasks": subtasks}, indent=2))
    elif output_format == "bash":
        print(f"DELETED\t{issue_key}")
    else:
        console.print(f"[red]✗[/red] Deleted [cyan]{issue_key}[/cyan]" + (" (+ subtasks)" if subtasks else ""))
