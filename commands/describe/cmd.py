"""
jiractl describe — rich display of a Jira issue or epic with its children.

  jiractl describe TCRM-1               # describe a single issue
  jiractl describe TCRM-1 --children    # describe epic + list all child tickets
  jiractl describe --epic TCRM-1        # alias for --children on an epic
"""
import textwrap
from datetime import datetime

import click
from rich.columns import Columns
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich import box

from jira_api.client import JiraClient
from jira_api.search import adf_to_text, get_issue, get_epic_children

console = Console()

# Status → colour mapping
STATUS_STYLE = {
    "To Do": "white",
    "In Progress": "yellow",
    "In Review": "blue",
    "Done": "green",
    "Closed": "dim green",
    "Blocked": "red",
}

PRIORITY_STYLE = {
    "Highest": "red",
    "High": "orange1",
    "Medium": "yellow",
    "Low": "cyan",
    "Lowest": "dim cyan",
}


def _status_style(name: str) -> str:
    return STATUS_STYLE.get(name, "white")


def _priority_style(name: str) -> str:
    return PRIORITY_STYLE.get(name, "white")


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso[:10]


def _display_name(user: dict | None) -> str:
    if not user:
        return "Unassigned"
    return user.get("displayName") or user.get("emailAddress") or "Unknown"


def _render_issue_panel(issue: dict, show_comments: bool = False) -> None:
    """Render a rich panel for a single Jira issue."""
    fields = issue.get("fields", {})
    key = issue.get("key", "?")
    summary = fields.get("summary", "(no summary)")
    issue_type = fields.get("issuetype", {}).get("name", "Issue")
    status = fields.get("status", {}).get("name", "Unknown")
    priority = (fields.get("priority") or {}).get("name", "—")
    assignee = _display_name(fields.get("assignee"))
    reporter = _display_name(fields.get("reporter"))
    created = _fmt_date(fields.get("created"))
    updated = _fmt_date(fields.get("updated"))
    labels = ", ".join(fields.get("labels") or []) or "—"
    parent = fields.get("parent")
    parent_str = parent["key"] if parent else "—"
    description_raw = adf_to_text(fields.get("description"))

    # Meta grid
    meta = Table.grid(pad_edge=False, expand=False)
    meta.add_column(style="dim", min_width=12)
    meta.add_column()
    rows = [
        ("Type", f"[bold]{issue_type}[/bold]"),
        ("Status", f"[{_status_style(status)}]{status}[/{_status_style(status)}]"),
        ("Priority", f"[{_priority_style(priority)}]{priority}[/{_priority_style(priority)}]"),
        ("Assignee", assignee),
        ("Reporter", reporter),
        ("Parent", parent_str),
        ("Labels", labels),
        ("Created", created),
        ("Updated", updated),
    ]
    for k, v in rows:
        meta.add_row(k, v)

    # Description panel
    desc_text = description_raw.strip() if description_raw.strip() else "[dim]No description provided.[/dim]"
    wrapped = textwrap.fill(desc_text, width=72) if len(desc_text) < 2000 else desc_text[:2000] + "…"

    body = f"{wrapped}\n\n"
    body_renderable = f"{wrapped}"

    # Comments
    if show_comments:
        comments = (fields.get("comment") or {}).get("comments", [])
        if comments:
            comment_lines = []
            for c in comments[-5:]:  # show last 5 comments
                author = _display_name(c.get("author"))
                date = _fmt_date(c.get("created"))
                body_text = adf_to_text(c.get("body")).strip()[:300]
                comment_lines.append(f"[dim]{author} · {date}[/dim]\n{body_text}")
            body_renderable = body_renderable + "\n\n[bold]Comments[/bold]\n" + "\n\n".join(comment_lines)

    console.print(
        Panel(
            Columns([meta, Panel(body_renderable, border_style="dim", padding=(0, 1))]),
            title=f"[bold cyan]{key}[/bold cyan]  [bold]{summary}[/bold]",
            border_style="cyan",
            subtitle=f"[dim]{issue.get('self', '')}[/dim]",
        )
    )


def _render_children_table(children: list[dict], epic_key: str) -> None:
    """Render a table of child issues for an epic."""
    if not children:
        console.print(f"[dim]No child issues found for {epic_key}.[/dim]")
        return

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        row_styles=["", "dim"],
    )
    table.add_column("Key", style="bold cyan", no_wrap=True, min_width=10)
    table.add_column("Type", no_wrap=True, min_width=8)
    table.add_column("Summary", min_width=40)
    table.add_column("Status", no_wrap=True, min_width=12)
    table.add_column("Priority", no_wrap=True, min_width=8)
    table.add_column("Assignee", min_width=14)

    for issue in children:
        f = issue.get("fields", {})
        key = issue.get("key", "?")
        itype = f.get("issuetype", {}).get("name", "?")
        summary = (f.get("summary") or "")[:70]
        status = f.get("status", {}).get("name", "?")
        priority = (f.get("priority") or {}).get("name", "—")
        assignee = _display_name(f.get("assignee"))

        s_style = _status_style(status)
        p_style = _priority_style(priority)

        table.add_row(
            key,
            itype,
            summary,
            f"[{s_style}]{status}[/{s_style}]",
            f"[{p_style}]{priority}[/{p_style}]",
            assignee,
        )

    console.print(table)
    console.print(f"[dim]{len(children)} issue(s) listed[/dim]")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

@click.command("describe")
@click.argument("issue_key", required=False, default=None)
@click.option("--epic", "epic_key", default=None, help="Describe an epic and list all child issues.")
@click.option("--children", is_flag=True, default=False, help="Also fetch and list child issues (auto-set when issue is an Epic).")
@click.option("--comments", is_flag=True, default=False, help="Show recent comments on the issue.")
@click.pass_context
def describe(ctx, issue_key, epic_key, children, comments):
    """
    Display a detailed view of a Jira issue.

    Pass an issue key directly, or use --epic to describe an epic and list
    all of its child stories/tasks.

    \b
    Examples:
      jiractl describe TCRM-1
      jiractl describe TCRM-1 --children
      jiractl describe TCRM-1 --comments
      jiractl describe --epic TCRM-1
    """
    cfg = ctx.obj["config"]

    # Resolve the target key
    target_key = epic_key or issue_key
    if not target_key:
        raise click.UsageError("Provide an issue key (e.g. TCRM-1) or use --epic TCRM-1")

    with JiraClient(cfg) as client:
        with console.status(f"Fetching {target_key}..."):
            issue = get_issue(client, target_key)

        _render_issue_panel(issue, show_comments=comments)

        # Show children if: --children flag, --epic flag, or issue type is Epic
        is_epic = (issue.get("fields", {}).get("issuetype", {}).get("name", "").lower() == "epic")
        if epic_key or children or is_epic:
            with console.status(f"Fetching child issues of {target_key}..."):
                child_issues = get_epic_children(client, target_key)
            console.print(f"\n[bold]Child Issues[/bold] of [cyan]{target_key}[/cyan] ({len(child_issues)} found)\n")
            _render_children_table(child_issues, target_key)
