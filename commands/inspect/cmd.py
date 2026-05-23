"""
jiractl inspect — explore project metadata and available fields.

  jiractl inspect project PROJ                         # project info + issue types + statuses
  jiractl inspect fields  PROJ                         # all fields across all issue types
  jiractl inspect fields  PROJ --issue-type Story      # fields for a specific issue type
  jiractl inspect fields  PROJ --issue-type Story --custom-only  # only custom fields
"""

import click
from rich import box
from rich.panel import Panel
from rich.table import Table

from commands._client import make_client
from commands.ui import console, format_option
from jira_api.search import (
    get_fields_for_issue_type,
    get_project_issue_types,
    get_project_meta,
    get_project_statuses,
)

# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group("inspect")
def inspect():
    """Explore project metadata: issue types, statuses, and available fields."""


# ---------------------------------------------------------------------------
# inspect project
# ---------------------------------------------------------------------------


@inspect.command("project")
@click.argument("project_key")
@format_option()
@click.pass_context
def inspect_project(ctx, project_key, output_format):
    """
    Show project metadata: name, lead, type, and issue types with their statuses.

    \b
    Examples:
      jiractl inspect project TCRM
      jiractl inspect project TCRM --format json
    """
    ctx.obj["config"]
    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:
        with use_status(f"Fetching project {project_key}..."):
            meta = get_project_meta(client, project_key)
        with use_status(f"Fetching statuses for {project_key}..."):
            statuses = get_project_statuses(client, project_key)

    if output_format == "json":
        import json

        print(json.dumps({"project": meta, "issueTypeStatuses": statuses}, indent=2))
        return

    if output_format == "bash":
        print(f"KEY\t{meta.get('key', '')}")
        print(f"NAME\t{meta.get('name', '')}")
        print(f"TYPE\t{meta.get('projectTypeKey', '')}")
        lead = meta.get("lead", {})
        print(f"LEAD\t{lead.get('displayName', '')}")
        for it in statuses:
            for st in it.get("statuses", []):
                print(f"STATUS\t{it['name']}\t{st['name']}")
        return

    # --- table ---
    lead = meta.get("lead", {})
    desc = meta.get("description") or ""

    info_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    info_table.add_column("Key", style="dim")
    info_table.add_column("Value", style="bold")
    info_table.add_row("Key", meta.get("key", ""))
    info_table.add_row("Name", meta.get("name", ""))
    info_table.add_row("Type", meta.get("projectTypeKey", ""))
    info_table.add_row("Lead", lead.get("displayName", "—"))
    if desc:
        info_table.add_row("Description", desc[:120] + ("…" if len(desc) > 120 else ""))

    console.print(
        Panel(
            info_table, title=f"[cyan]{project_key}[/cyan] Project", border_style="cyan"
        )
    )

    # Issue types + statuses
    for issue_type in statuses:
        type_name = issue_type.get("name", "?")
        subtask = issue_type.get("subtask", False)
        suffix = " [dim](subtask)[/dim]" if subtask else ""
        st_table = Table(
            title=f"[bold]{type_name}[/bold]{suffix}",
            box=box.ROUNDED,
            border_style="dim",
            show_lines=False,
        )
        st_table.add_column("Status", style="bold")
        st_table.add_column("Category", style="dim")
        for st in issue_type.get("statuses", []):
            cat = st.get("statusCategory", {}).get("name", "")
            st_table.add_row(st.get("name", ""), cat)
        console.print(st_table)


# ---------------------------------------------------------------------------
# inspect fields
# ---------------------------------------------------------------------------


@inspect.command("fields")
@click.argument("project_key")
@click.option(
    "--issue-type",
    "issue_type_name",
    default=None,
    metavar="NAME",
    help="Filter to one issue type (e.g. Story, Bug, Epic). Defaults to first issue type found.",
)
@click.option(
    "--custom-only",
    is_flag=True,
    default=False,
    help="Only show custom fields (useful for finding customfield_XXXXX IDs).",
)
@format_option()
@click.pass_context
def inspect_fields(ctx, project_key, issue_type_name, custom_only, output_format):
    """
    Show all fields available for a project's issue type.

    Displays the field ID (use this in --raw-data), the human-readable name,
    the data type, and whether the field is required.

    \b
    Examples:
      jiractl inspect fields TCRM
      jiractl inspect fields TCRM --issue-type Story
      jiractl inspect fields TCRM --issue-type Bug --custom-only
      jiractl inspect fields TCRM --format json
    """
    ctx.obj["config"]
    use_status = console.status if output_format == "table" else _noop_status

    with make_client(ctx) as client:
        with use_status(f"Fetching issue types for {project_key}..."):
            issue_types = get_project_issue_types(client, project_key)

        if not issue_types:
            raise click.ClickException(
                f"No issue types found for project '{project_key}'."
            )

        # Resolve which issue type to inspect
        if issue_type_name:
            needle = issue_type_name.lower()
            matched = [it for it in issue_types if it["name"].lower() == needle]
            if not matched:
                available = ", ".join(it["name"] for it in issue_types)
                raise click.ClickException(
                    f"Issue type '{issue_type_name}' not found in {project_key}.\n"
                    f"Available: {available}"
                )
            target = matched[0]
        else:
            # Default to the first non-subtask type, or just the first
            target = next(
                (it for it in issue_types if not it.get("subtask")), issue_types[0]
            )

        with use_status(f"Fetching fields for {project_key} / {target['name']}..."):
            fields = get_fields_for_issue_type(client, project_key, target["id"])

    if custom_only:
        fields = [
            f
            for f in fields
            if f.get("schema", {}).get("custom")
            or f.get("fieldId", "").startswith("customfield_")
        ]

    if output_format == "json":
        import json

        print(
            json.dumps(
                {
                    "project": project_key,
                    "issueType": target["name"],
                    "fields": fields,
                },
                indent=2,
            )
        )
        return

    if output_format == "bash":
        for f in fields:
            fid = f.get("fieldId") or f.get("key", "")
            name = f.get("name", "")
            ftype = f.get("schema", {}).get("type", "")
            required = "required" if f.get("required") else ""
            print(f"{fid}\t{name}\t{ftype}\t{required}")
        return

    # --- table ---
    table = Table(
        title=f"[dim]Fields for[/dim] [cyan]{project_key}[/cyan] / [bold]{target['name']}[/bold]"
        + (" [dim](custom only)[/dim]" if custom_only else ""),
        box=box.ROUNDED,
        border_style="dim",
        show_lines=False,
    )
    table.add_column("Field ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Req?", justify="center")
    table.add_column("Operations", style="dim")

    for f in sorted(
        fields, key=lambda x: (not x.get("required", False), x.get("name", "").lower())
    ):
        fid = f.get("fieldId") or f.get("key", "")
        name = f.get("name", "")
        schema = f.get("schema", {})
        ftype = schema.get("type", "")
        if schema.get("items"):
            ftype = f"{ftype}[{schema['items']}]"
        req = "[red]✓[/red]" if f.get("required") else ""
        ops = ", ".join(f.get("operations", []))
        table.add_row(fid, name, ftype, req, ops)

    console.print(table)
    console.print(
        "\n[dim]Tip:[/dim] Use the [cyan]Field ID[/cyan] column values in "
        "[cyan]jiractl edit --raw-data[/cyan], e.g.:\n"
        '  [dim]jiractl edit ISSUE-1 --raw-data \'{"fields":{"customfield_10014":"EPIC-1"}}\'[/dim]'
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _noop_status:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass
