"""
jiractl to-prompt — output a copy-paste AI coding prompt for a Jira ticket.

  jiractl to-prompt TCRM-147
  jiractl to-prompt TCRM-146          # epic: uses itself as context
  jiractl to-prompt DEV-1             # no parent: omits Context section
  jiractl to-prompt TCRM-147 | pbcopy
"""

import json as _json

import click

from jiractl.commands._client import make_client
from jiractl.commands.ui import flatten_issue
from jiractl.jira_api.search import get_epic_children, get_issue


def _dump(obj) -> str:
    return _json.dumps(obj, indent=2, ensure_ascii=False)


@click.command("to-prompt")
@click.argument("issue_key")
@click.pass_context
def to_prompt(ctx, issue_key):
    """
    Output a structured markdown prompt for an AI coding agent.

    Fetches the ticket, its parent epic (if any), and the epic's children,
    then prints a markdown block suitable for pasting into an agent session.

    \b
    Examples:
      jiractl to-prompt TCRM-147
      jiractl to-prompt TCRM-147 | pbcopy
      jiractl to-prompt TCRM-146        # works on epics too
    """
    key = issue_key.upper()

    with make_client(ctx) as client:
        issue = get_issue(client, key)

        fields = issue.get("fields", {})
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        parent_ref = fields.get("parent")

        if issue_type == "Epic":
            # Issue is itself an epic — use it as the context
            epic = issue
            epic_children = get_epic_children(client, key)
            target = issue
        elif parent_ref:
            parent_key = parent_ref["key"]
            epic = get_issue(client, parent_key)
            epic_children = get_epic_children(client, parent_key)
            target = issue
        else:
            epic = None
            epic_children = []
            target = issue

    flat_target = flatten_issue(target, include_description=True)

    lines = [
        f"# {key}",
        "",
        "Task To Implement:",
        "",
        "```json",
        _dump({"issue": flat_target}),
        "```",
    ]

    if epic is not None:
        flat_epic = flatten_issue(epic, include_description=True)
        flat_children = [flatten_issue(c) for c in epic_children]

        lines += [
            "",
            "Context:",
            "",
            "Epic",
            "",
            "```json",
            _dump({"issue": flat_epic, "children": flat_children}),
            "```",
        ]

    print("\n".join(lines))
