"""
jiractl status — view or change the status of a Jira issue.

  jiractl status TCRM-1                   # show current status
  jiractl status TCRM-1 --list            # list all available transitions
  jiractl status TCRM-1 "In Progress"     # move to target status
  jiractl status TCRM-1 Done              # quotes optional for single words
  jiractl status TCRM-1 "In Progress" --format json
"""

import click
from rich import box
from rich.table import Table

from commands._client import make_client
from commands.ui import console, format_option, status_style
from jira_api.mutations import find_transition, get_transitions, transition_issue
from jira_api.search import get_issue


@click.command("status")
@click.argument("issue_key")
@click.argument("target_status", required=False, default=None)
@click.option(
    "--list",
    "list_transitions",
    is_flag=True,
    default=False,
    help="List all available transitions / reachable statuses.",
)
@format_option()
@click.pass_context
def status(ctx, issue_key, target_status, list_transitions, output_format):
    """
    View or change the status of a Jira issue.

    Without TARGET_STATUS: display the current status.
    With --list: show every transition available from the current state.
    With TARGET_STATUS: apply the matching transition.

    \b
    Examples:
      jiractl status TCRM-1
      jiractl status TCRM-1 --list
      jiractl status TCRM-1 "In Progress"
      jiractl status TCRM-1 Done
      jiractl status TCRM-1 --list --format json
      jiractl status TCRM-1 "Done" --format bash
    """
    ctx.obj["config"]
    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:

        # ── List available transitions ─────────────────────────────────────
        if list_transitions:
            with use_status(f"Fetching transitions for {issue_key}..."):
                transitions = get_transitions(client, issue_key)
                issue = get_issue(client, issue_key)

            current = issue.get("fields", {}).get("status", {}).get("name", "?")

            if output_format == "json":
                import json

                print(
                    json.dumps(
                        {
                            "issue": issue_key,
                            "current_status": current,
                            "transitions": [
                                {"id": t["id"], "name": t["to"]["name"]}
                                for t in transitions
                            ],
                        },
                        indent=2,
                    )
                )
            elif output_format == "bash":
                print(f"CURRENT\t{current}")
                print("ID\tTO_STATUS")
                for t in transitions:
                    print(f"{t['id']}\t{t['to']['name']}")
            else:
                ss = status_style(current)
                console.print(
                    f"\nCurrent status of [cyan]{issue_key}[/cyan]: "
                    f"[{ss}]{current}[/{ss}]\n"
                )
                table = Table(
                    title="Available Transitions",
                    box=box.ROUNDED,
                    border_style="dim",
                    header_style="bold cyan",
                )
                table.add_column("ID", style="dim", no_wrap=True, min_width=4)
                table.add_column("Move to Status", min_width=20)
                for t in transitions:
                    dest = t["to"]["name"]
                    ds = status_style(dest)
                    table.add_row(t["id"], f"[{ds}]{dest}[/{ds}]")
                console.print(table)
            return

        # ── Show current status ────────────────────────────────────────────
        if not target_status:
            with use_status(f"Fetching {issue_key}..."):
                issue = get_issue(client, issue_key)

            current = issue.get("fields", {}).get("status", {}).get("name", "?")
            summary = issue.get("fields", {}).get("summary", "")

            if output_format == "json":
                import json

                print(
                    json.dumps(
                        {"issue": issue_key, "status": current, "summary": summary},
                        indent=2,
                    )
                )
            elif output_format == "bash":
                print(f"STATUS\t{issue_key}\t{current}")
            else:
                ss = status_style(current)
                console.print(
                    f"[cyan]{issue_key}[/cyan]  {summary}\n"
                    f"Status: [{ss}]{current}[/{ss}]\n"
                    f"[dim]Use --list to see available transitions.[/dim]"
                )
            return

        # ── Apply a transition ─────────────────────────────────────────────
        with use_status(f"Looking up transitions for {issue_key}..."):
            transition = find_transition(client, issue_key, target_status)

        with use_status(f"Transitioning {issue_key} → {target_status}..."):
            transition_issue(client, issue_key, transition["id"])

        if output_format == "json":
            import json

            print(
                json.dumps(
                    {
                        "issue": issue_key,
                        "transitioned": True,
                        "to": target_status,
                        "transition_id": transition["id"],
                    },
                    indent=2,
                )
            )
        elif output_format == "bash":
            print(f"TRANSITIONED\t{issue_key}\t{target_status}")
        else:
            ss = status_style(target_status)
            console.print(
                f"[green]✓[/green] [cyan]{issue_key}[/cyan] "
                f"→ [{ss}]{target_status}[/{ss}]"
            )


class _noop_status:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass
