"""
jiractl comment — add a comment to a Jira issue.

  jiractl comment TCRM-1 "I've started working on this."
  jiractl comment TCRM-1 "Analysis complete. See notes below." --agent "Claude"
  jiractl comment TCRM-1 "$(cat report.txt)" --agent "AutoReviewer"

When --agent is provided, the comment is prefixed with an AI attribution
blockquote so humans reviewing the issue can clearly identify AI-generated
content.  The banner includes the agent name and a UTC timestamp:

    > 🤖 AI Agent · Claude · 2026-03-08 14:32 UTC

    <your comment body>

This acts as a content gate — all AI-written comments are visibly marked.
"""

import click

from commands._client import make_client
from commands.ui import console, format_option
from jira_api.mutations import add_comment


@click.command("comment")
@click.argument("issue_key")
@click.argument("body")
@click.option(
    "--agent",
    default=None,
    metavar="NAME",
    help=(
        "Mark this comment as AI-generated. Prepends an attribution banner "
        "with the given agent name and timestamp. Example: --agent 'Claude'."
    ),
)
@format_option()
@click.pass_context
def comment(ctx, issue_key, body, agent, output_format):
    """
    Add a comment to a Jira issue.

    Wrap BODY in quotes or pass it via shell substitution.
    Use --agent NAME to clearly mark AI-generated content.

    \b
    Examples:
      jiractl comment TCRM-1 "Looking into this now."
      jiractl comment TCRM-1 "Analysis done. Root cause: X." --agent Claude
      jiractl comment TCRM-1 "$(cat summary.txt)" --agent AutoBot
      jiractl comment TCRM-1 "Done." --format json
    """
    ctx.obj["config"]

    use_status = console.status if output_format == "table" else _noop_status

    if agent and output_format == "table":
        console.print(f"[dim]🤖 Posting AI-attributed comment as '{agent}'…[/dim]")

    with make_client(ctx) as client:
        with use_status(f"Posting comment on {issue_key}..."):
            result = add_comment(client, issue_key, body, agent_name=agent)

    comment_id = result.get("id", "?")

    if output_format == "json":
        import json

        print(
            json.dumps(
                {
                    "issue": issue_key,
                    "comment_id": comment_id,
                    "agent": agent,
                    "body": body,
                },
                indent=2,
            )
        )
    elif output_format == "bash":
        print(f"COMMENTED\t{issue_key}\t{comment_id}")
    else:
        agent_note = f" [dim](via agent: {agent})[/dim]" if agent else ""
        console.print(
            f"[green]✓[/green] Comment added to [cyan]{issue_key}[/cyan]{agent_note} [dim](id: {comment_id})[/dim]"
        )


class _noop_status:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass
