"""
jiractl backlog — backlog grooming: move issues in and out of sprints.

  jiractl backlog list -p TCRM                        # issues in the backlog
  jiractl backlog sprint -p TCRM                      # issues in the active sprint
  jiractl backlog sprint -p TCRM --sprint "Sprint 3"  # issues in a named sprint
  jiractl backlog sprints -p TCRM                     # list sprints for the board
  jiractl backlog add TCRM-1 TCRM-2                   # move issues to active sprint
  jiractl backlog add TCRM-1 --sprint "Sprint 3"
  jiractl backlog remove TCRM-1 TCRM-2                # move issues to backlog
"""

import json

import click
from rich import box
from rich.table import Table

from jiractl.commands._client import make_client
from jiractl.commands.ui import (
    PRIORITY_STYLE,
    STATUS_STYLE,
    console,
    fmt_date,
    format_option,
)
from jiractl.jira_api.agile import (
    get_active_sprint,
    get_board_backlog,
    get_board_sprints,
    get_sprint_issues,
    move_to_backlog,
    move_to_sprint,
    resolve_sprint,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _noop_status:
    """No-op context manager — replaces console.status() in bash/json mode."""

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _resolve_board(ctx, project_ref: str | None, board_override: int | None) -> tuple[int, str]:
    """
    Return (board_id, resolved_project_key).

    Resolution order:
      1. Explicit --board INT flag (skips project lookup entirely).
      2. --project flag → cfg.board_ids[project_key].
    Raises ClickException with a helpful message when the board cannot be resolved.
    """
    cfg = ctx.obj["config"]

    if board_override:
        return board_override, project_ref or "?"

    if not project_ref:
        raise click.ClickException(
            "Specify a project with -p/--project PROJECT (e.g. -p TCRM). "
            "The board ID is looked up from your config's board_ids map."
        )

    # Allow synonym resolution (e.g. "tilly" → "TCRM")
    resolved = cfg.resolve_project(project_ref) or project_ref.upper()
    board_id = cfg.board_ids.get(resolved)
    if not board_id:
        configured = ", ".join(cfg.board_ids.keys()) or "(none)"
        raise click.ClickException(
            f"No board ID configured for project '{resolved}'. "
            f"Configured projects: {configured}.\n"
            f"Add it to your config:\n"
            f"  board_ids:\n    {resolved}: <board_id>"
        )
    return board_id, resolved


def _flat_issue(issue: dict) -> dict:
    """Flatten a Jira Agile issue dict to a simple key/value mapping."""
    fields = issue.get("fields", {})
    return {
        "key": issue.get("key", ""),
        "type": (fields.get("issuetype") or {}).get("name", ""),
        "summary": fields.get("summary", ""),
        "status": (fields.get("status") or {}).get("name", ""),
        "priority": (fields.get("priority") or {}).get("name", ""),
        "assignee": ((fields.get("assignee") or {}).get("displayName", "Unassigned")),
    }


def _print_issues_table(issues: list[dict], title: str, output_format: str) -> None:
    """Render a list of Agile issues in table / bash / json format."""
    flat = [_flat_issue(i) for i in issues]

    if output_format == "json":
        print(json.dumps(flat, indent=2))
        return

    if output_format == "bash":
        print("KEY\tTYPE\tSTATUS\tPRIORITY\tASSIGNEE\tSUMMARY")
        for row in flat:
            print(
                f"{row['key']}\t{row['type']}\t{row['status']}\t{row['priority']}\t{row['assignee']}\t{row['summary']}"
            )
        return

    # Rich table
    table = Table(
        title=title,
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
    )
    table.add_column("Key", style="cyan bold", no_wrap=True)
    table.add_column("Type", style="dim", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Priority", no_wrap=True)
    table.add_column("Assignee", no_wrap=True)
    table.add_column("Summary")

    for row in flat:
        status_style = STATUS_STYLE.get(row["status"], "white")
        priority_style = PRIORITY_STYLE.get(row["priority"], "white")
        table.add_row(
            row["key"],
            row["type"],
            f"[{status_style}]{row['status']}[/{status_style}]",
            f"[{priority_style}]{row['priority']}[/{priority_style}]",
            row["assignee"],
            row["summary"],
        )

    if not flat:
        console.print(f"[dim]{title}: no issues found.[/dim]")
        return

    console.print(table)


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group("backlog")
def backlog():
    """Backlog grooming: view and move issues between backlog and sprints."""


# ---------------------------------------------------------------------------
# backlog list
# ---------------------------------------------------------------------------


@backlog.command("list")
@click.option("-p", "--project", "project_ref", default=None, help="Project key or alias (e.g. TCRM, tilly).")
@click.option("--board", "board_id", type=int, default=None, help="Board ID (overrides project lookup).")
@click.option("-n", "--limit", default=50, show_default=True, help="Max results to return.")
@format_option()
@click.pass_context
def backlog_list(ctx, project_ref, board_id, limit, output_format):
    """
    List issues currently in the backlog.

    \b
    Examples:
      jiractl backlog list -p TCRM
      jiractl backlog list -p tilly
      jiractl backlog list -p TCRM -n 100 --format json
    """
    board_id, project_key = _resolve_board(ctx, project_ref, board_id)
    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:
        with use_status(f"Fetching backlog for {project_key}..."):
            issues = get_board_backlog(client, board_id, max_results=limit)

    _print_issues_table(issues, title=f"Backlog — {project_key}", output_format=output_format)


# ---------------------------------------------------------------------------
# backlog sprint
# ---------------------------------------------------------------------------


@backlog.command("sprint")
@click.option("-p", "--project", "project_ref", default=None, help="Project key or alias (e.g. TCRM, tilly).")
@click.option("--board", "board_id", type=int, default=None, help="Board ID (overrides project lookup).")
@click.option(
    "--sprint",
    "sprint_ref",
    default=None,
    help="Sprint name (or numeric ID). Defaults to the active sprint.",
)
@click.option("-n", "--limit", default=50, show_default=True, help="Max results to return.")
@format_option()
@click.pass_context
def backlog_sprint(ctx, project_ref, board_id, sprint_ref, limit, output_format):
    """
    List issues in a sprint (defaults to the active sprint).

    \b
    Examples:
      jiractl backlog sprint -p TCRM
      jiractl backlog sprint -p TCRM --sprint "Sprint 3"
      jiractl backlog sprint -p TCRM --sprint 17
      jiractl backlog sprint -p TCRM --format json
    """
    board_id, project_key = _resolve_board(ctx, project_ref, board_id)
    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:
        if sprint_ref:
            with use_status(f"Resolving sprint '{sprint_ref}'..."):
                try:
                    sprint = resolve_sprint(client, board_id, sprint_ref)
                except ValueError as e:
                    raise click.ClickException(str(e)) from e
        else:
            with use_status(f"Finding active sprint for {project_key}..."):
                sprint = get_active_sprint(client, board_id)
            if sprint is None:
                if output_format == "json":
                    print("[]")
                elif output_format == "bash":
                    print("# No active sprint.")
                else:
                    console.print(f"[yellow]No active sprint found for {project_key}.[/yellow]")
                return

        sprint_id = sprint["id"]
        sprint_name = sprint.get("name", str(sprint_id))

        with use_status(f"Fetching issues for sprint '{sprint_name}'..."):
            issues = get_sprint_issues(client, board_id, sprint_id, max_results=limit)

    _print_issues_table(issues, title=f"{project_key} — {sprint_name}", output_format=output_format)


# ---------------------------------------------------------------------------
# backlog sprints
# ---------------------------------------------------------------------------


@backlog.command("sprints")
@click.option("-p", "--project", "project_ref", default=None, help="Project key or alias (e.g. TCRM, tilly).")
@click.option("--board", "board_id", type=int, default=None, help="Board ID (overrides project lookup).")
@click.option(
    "--state",
    default="active,future",
    show_default=True,
    help="Sprint state filter: active, future, closed (comma-separated).",
)
@format_option()
@click.pass_context
def backlog_sprints(ctx, project_ref, board_id, state, output_format):
    """
    List sprints for the board.

    \b
    Examples:
      jiractl backlog sprints -p TCRM
      jiractl backlog sprints -p TCRM --state active
      jiractl backlog sprints -p TCRM --state active,future,closed --format json
    """
    board_id, project_key = _resolve_board(ctx, project_ref, board_id)
    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:
        with use_status(f"Fetching sprints for {project_key}..."):
            sprints = get_board_sprints(client, board_id, state=state)

    if output_format == "json":
        flat = [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "state": s.get("state"),
                "startDate": s.get("startDate"),
                "endDate": s.get("endDate"),
            }
            for s in sprints
        ]
        print(json.dumps(flat, indent=2))
        return

    if output_format == "bash":
        print("ID\tNAME\tSTATE\tSTART\tEND")
        for s in sprints:
            print(
                f"{s.get('id', '')}\t{s.get('name', '')}\t{s.get('state', '')}\t"
                f"{fmt_date(s.get('startDate'))}\t{fmt_date(s.get('endDate'))}"
            )
        return

    if not sprints:
        console.print(f"[dim]No sprints found for {project_key} (state={state}).[/dim]")
        return

    table = Table(
        title=f"Sprints — {project_key}",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
    )
    table.add_column("ID", style="cyan bold", no_wrap=True)
    table.add_column("Name")
    table.add_column("State", no_wrap=True)
    table.add_column("Start", no_wrap=True)
    table.add_column("End", no_wrap=True)

    STATE_STYLE = {"active": "green", "future": "yellow", "closed": "dim"}
    for s in sprints:
        st = s.get("state", "")
        style = STATE_STYLE.get(st, "white")
        table.add_row(
            str(s.get("id", "")),
            s.get("name", ""),
            f"[{style}]{st}[/{style}]",
            fmt_date(s.get("startDate")),
            fmt_date(s.get("endDate")),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# backlog add (move to sprint)
# ---------------------------------------------------------------------------


@backlog.command("add")
@click.argument("issue_keys", nargs=-1, required=True)
@click.option(
    "-p", "--project", "project_ref", default=None, help="Project key or alias. Derived from issue keys if omitted."
)
@click.option("--board", "board_id", type=int, default=None, help="Board ID (overrides project lookup).")
@click.option(
    "--sprint",
    "sprint_ref",
    default=None,
    help="Sprint name or numeric ID. Defaults to the active sprint.",
)
@click.pass_context
def backlog_add(ctx, issue_keys, project_ref, board_id, sprint_ref):
    """
    Move one or more issues into a sprint (removes them from the backlog).

    The project is derived from the issue key prefix (e.g. TCRM-1 → TCRM)
    unless overridden with -p/--project. Defaults to the active sprint.

    \b
    Examples:
      jiractl backlog add TCRM-1 TCRM-2
      jiractl backlog add TCRM-5 --sprint "Sprint 3"
      jiractl backlog add TCRM-7 --sprint 17
    """
    # Derive project from the first issue key when not explicitly given
    if not project_ref and not board_id:
        first_key = issue_keys[0]
        # Issue keys look like PROJ-123 — everything before the last "-" is the project
        project_ref = first_key.rsplit("-", 1)[0]

    board_id, project_key = _resolve_board(ctx, project_ref, board_id)

    with make_client(ctx) as client:
        if sprint_ref:
            with console.status(f"Resolving sprint '{sprint_ref}'..."):
                try:
                    sprint = resolve_sprint(client, board_id, sprint_ref)
                except ValueError as e:
                    raise click.ClickException(str(e)) from e
        else:
            with console.status("Finding active sprint..."):
                sprint = get_active_sprint(client, board_id)
            if sprint is None:
                raise click.ClickException("No active sprint found. Use --sprint NAME_OR_ID to specify one explicitly.")

        sprint_id = sprint["id"]
        sprint_name = sprint.get("name", str(sprint_id))

        keys = list(issue_keys)
        with console.status(f"Moving {len(keys)} issue(s) to '{sprint_name}'..."):
            move_to_sprint(client, sprint_id, keys)

    n = len(keys)
    console.print(f"[green]✓[/green] Moved {n} issue{'s' if n != 1 else ''} to sprint [bold]{sprint_name}[/bold]")


# ---------------------------------------------------------------------------
# backlog remove (move to backlog)
# ---------------------------------------------------------------------------


@backlog.command("remove")
@click.argument("issue_keys", nargs=-1, required=True)
@click.pass_context
def backlog_remove(ctx, issue_keys):
    """
    Move one or more issues from a sprint back to the backlog.

    \b
    Examples:
      jiractl backlog remove PROJ-1
      jiractl backlog remove PROJ-1 PROJ-2 PROJ-3
    """
    keys = list(issue_keys)
    with make_client(ctx) as client:
        with console.status(f"Moving {len(keys)} issue(s) to backlog..."):
            move_to_backlog(client, keys)

    n = len(keys)
    console.print(f"[green]✓[/green] Moved {n} issue{'s' if n != 1 else ''} to the backlog")
