"""
commands/ui.py — centralised rendering for jiractl.

Provides format-agnostic output for lists of Jira issues and single-issue
detail views.  Commands import helpers from here instead of duplicating
Rich/print logic.

Supported formats (--format):
  table  — Rich coloured table (default, human-friendly terminal)
  bash   — Tab-separated values (TSV), machine/script-friendly
  json   — JSON array / object, pipe-friendly
"""

from __future__ import annotations

import json as _json
import textwrap
from datetime import datetime

import click
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from jiractl.jira_api.search import adf_to_text

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

console = Console()

OUTPUT_FORMATS = ("table", "bash", "json")

STATUS_STYLE: dict[str, str] = {
    "To Do": "white",
    "In Progress": "yellow",
    "In Review": "blue",
    "Done": "green",
    "Closed": "dim green",
    "Blocked": "red",
}

PRIORITY_STYLE: dict[str, str] = {
    "Highest": "red",
    "High": "orange1",
    "Medium": "yellow",
    "Low": "cyan",
    "Lowest": "dim cyan",
}


# ---------------------------------------------------------------------------
# Click decorator factory
# ---------------------------------------------------------------------------


def format_option():
    """Reusable Click decorator that adds a --format option to any command."""
    return click.option(
        "--format",
        "output_format",
        type=click.Choice(OUTPUT_FORMATS, case_sensitive=False),
        default="table",
        show_default=True,
        help="Output format: table (rich), bash (TSV), or json.",
    )


# ---------------------------------------------------------------------------
# Field helpers (shared across all formats)
# ---------------------------------------------------------------------------


def fmt_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso[:10]


def display_name(user: dict | None) -> str:
    if not user:
        return "Unassigned"
    return user.get("displayName") or user.get("emailAddress") or "Unknown"


def status_style(name: str) -> str:
    return STATUS_STYLE.get(name, "white")


def priority_style(name: str) -> str:
    return PRIORITY_STYLE.get(name, "white")


def flatten_issue(issue: dict, include_description: bool = False) -> dict:
    """
    Flatten a raw Jira issue dict into a simple key→value dict suitable
    for JSON export or TSV output.
    """
    f = issue.get("fields", {})
    parent = f.get("parent")
    out: dict = {
        "key": issue.get("key", ""),
        "project": f.get("project", {}).get("key", ""),
        "type": f.get("issuetype", {}).get("name", ""),
        "summary": f.get("summary") or "",
        "status": f.get("status", {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "assignee": display_name(f.get("assignee")),
        "reporter": display_name(f.get("reporter")),
        "parent": parent["key"] if parent else "",
        "labels": ", ".join(f.get("labels") or []),
        "created": fmt_date(f.get("created")),
        "updated": fmt_date(f.get("updated")),
        "url": issue.get("self", ""),
    }
    if include_description:
        out["description"] = adf_to_text(f.get("description")).strip()
    return out


# ---------------------------------------------------------------------------
# Format: json
# ---------------------------------------------------------------------------


def _print_json_issues(issues: list[dict]) -> None:
    rows = [flatten_issue(i) for i in issues]
    print(_json.dumps(rows, indent=2, ensure_ascii=False))


def _print_json_issue_detail(
    issue: dict,
    children: list[dict] | None,
    show_comments: bool,
) -> None:
    flat = flatten_issue(issue, include_description=True)
    if show_comments:
        comments_raw = (issue.get("fields", {}).get("comment") or {}).get("comments", [])
        flat["comments"] = [
            {
                "author": display_name(c.get("author")),
                "created": fmt_date(c.get("created")),
                "body": adf_to_text(c.get("body")).strip(),
            }
            for c in comments_raw
        ]
    payload: dict = {"issue": flat}
    if children is not None:
        payload["children"] = [flatten_issue(c) for c in children]
    print(_json.dumps(payload, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Format: bash (TSV)
# ---------------------------------------------------------------------------

# Column spec for the two layouts (no-project / with-project)
_COLS_BASE = ("key", "type", "summary", "status", "priority", "assignee", "updated")
_COLS_WITH_PROJECT = (
    "key",
    "project",
    "type",
    "summary",
    "status",
    "priority",
    "assignee",
    "updated",
)


def _print_tsv_issues(issues: list[dict], include_project: bool = False) -> None:
    cols = _COLS_WITH_PROJECT if include_project else _COLS_BASE
    print("\t".join(c.upper() for c in cols))
    for issue in issues:
        flat = flatten_issue(issue)
        print("\t".join(flat.get(c, "") for c in cols))


def _print_tsv_detail(issue: dict) -> None:
    cols = (
        "key",
        "project",
        "type",
        "summary",
        "status",
        "priority",
        "assignee",
        "reporter",
        "parent",
        "labels",
        "created",
        "updated",
    )
    flat = flatten_issue(issue, include_description=True)
    print("\t".join(c.upper() for c in cols))
    print("\t".join(flat.get(c, "") for c in cols))
    desc = flat.get("description", "")
    if desc:
        print(f"\nDESCRIPTION\n{desc}")


# ---------------------------------------------------------------------------
# Format: table (Rich)
# ---------------------------------------------------------------------------


def _rich_issues_table(
    issues: list[dict],
    title: str,
    include_project: bool = False,
) -> Table:
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
    if include_project:
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
        summary = (f.get("summary") or "")[:64]
        st = f.get("status", {}).get("name", "?")
        pri = (f.get("priority") or {}).get("name", "—")
        asgn = display_name(f.get("assignee"))
        upd = fmt_date(f.get("updated"))
        ss = status_style(st)
        ps = priority_style(pri)

        row = [key]
        if include_project:
            row.append(proj)
        row += [
            itype,
            summary[:60],
            f"[{ss}]{st}[/{ss}]",
            f"[{ps}]{pri}[/{ps}]",
            asgn,
            upd,
        ]
        table.add_row(*row)
    return table


def _rich_children_table(children: list[dict], parent_key: str) -> Table:
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
        st = f.get("status", {}).get("name", "?")
        pri = (f.get("priority") or {}).get("name", "—")
        asgn = display_name(f.get("assignee"))
        ss = status_style(st)
        ps = priority_style(pri)
        table.add_row(
            key,
            itype,
            summary,
            f"[{ss}]{st}[/{ss}]",
            f"[{ps}]{pri}[/{ps}]",
            asgn,
        )
    return table


def _rich_issue_panel(issue: dict, show_comments: bool = False) -> None:
    f = issue.get("fields", {})
    key = issue.get("key", "?")
    summary = f.get("summary", "(no summary)")
    itype = f.get("issuetype", {}).get("name", "Issue")
    st = f.get("status", {}).get("name", "Unknown")
    pri = (f.get("priority") or {}).get("name", "—")
    asgn = display_name(f.get("assignee"))
    reporter = display_name(f.get("reporter"))
    created = fmt_date(f.get("created"))
    updated = fmt_date(f.get("updated"))
    labels = ", ".join(f.get("labels") or []) or "—"
    parent = f.get("parent")
    parent_str = parent["key"] if parent else "—"
    description_raw = adf_to_text(f.get("description"))

    meta = Table.grid(pad_edge=False, expand=False)
    meta.add_column(style="dim", min_width=12)
    meta.add_column()
    ss = status_style(st)
    ps = priority_style(pri)
    for label, value in [
        ("Type", f"[bold]{itype}[/bold]"),
        ("Status", f"[{ss}]{st}[/{ss}]"),
        ("Priority", f"[{ps}]{pri}[/{ps}]"),
        ("Assignee", asgn),
        ("Reporter", reporter),
        ("Parent", parent_str),
        ("Labels", labels),
        ("Created", created),
        ("Updated", updated),
    ]:
        meta.add_row(label, value)

    desc_text = description_raw.strip() if description_raw.strip() else "[dim]No description provided.[/dim]"
    body = textwrap.fill(desc_text, width=72) if len(desc_text) < 2000 else desc_text[:2000] + "…"

    if show_comments:
        comments = (f.get("comment") or {}).get("comments", [])
        if comments:
            lines = []
            for c in comments[-5:]:
                author = display_name(c.get("author"))
                date = fmt_date(c.get("created"))
                body_text = adf_to_text(c.get("body")).strip()[:300]
                lines.append(f"[dim]{author} · {date}[/dim]\n{body_text}")
            body += "\n\n[bold]Comments[/bold]\n" + "\n\n".join(lines)

    console.print(
        Panel(
            Columns([meta, Panel(body, border_style="dim", padding=(0, 1))]),
            title=f"[bold cyan]{key}[/bold cyan]  [bold]{summary}[/bold]",
            border_style="cyan",
            subtitle=f"[dim]{issue.get('self', '')}[/dim]",
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def print_issues(
    issues: list[dict],
    title: str,
    fmt: str,
    include_project: bool = False,
) -> None:
    """
    Render a list of Jira issues in the requested format.

    Args:
      issues:          Raw Jira issue dicts.
      title:           Table title (used in 'table' format only).
      fmt:             One of 'table', 'bash', 'json'.
      include_project: When True, include a Project column (useful for cross-project searches).
    """
    if fmt == "json":
        _print_json_issues(issues)
    elif fmt == "bash":
        _print_tsv_issues(issues, include_project=include_project)
    else:
        console.print(_rich_issues_table(issues, title=title, include_project=include_project))
        console.print(f"[dim]{len(issues)} issue(s)[/dim]")


def print_issue_detail(
    issue: dict,
    fmt: str,
    *,
    show_comments: bool = False,
    children: list[dict] | None = None,
) -> None:
    """
    Render a single issue detail (and optionally its children) in the requested format.

    Args:
      issue:         Raw Jira issue dict.
      fmt:           One of 'table', 'bash', 'json'.
      show_comments: Include comment thread in the output.
      children:      Optional list of child issue dicts.  When None, the children
                     section is omitted.  Pass [] to show "0 children found".
    """
    if fmt == "json":
        _print_json_issue_detail(issue, children, show_comments)
    elif fmt == "bash":
        _print_tsv_detail(issue)
        if children is not None:
            if children:
                _print_tsv_issues(children)
            else:
                print(f"NO_CHILDREN\t{issue.get('key', '')}")
    else:
        # Rich panel
        _rich_issue_panel(issue, show_comments=show_comments)
        if children is not None:
            parent_key = issue.get("key", "?")
            console.print(f"\n[bold]Child Issues[/bold] of [cyan]{parent_key}[/cyan] ({len(children)} found)\n")
            if children:
                console.print(_rich_children_table(children, parent_key))
                console.print(f"[dim]{len(children)} issue(s) listed[/dim]")
            else:
                console.print(f"[dim]No child issues found for {parent_key}.[/dim]")
