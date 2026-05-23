"""
Centralized JiraClient construction for CLI commands.

All subcommands should instantiate JiraClient via make_client(ctx) rather than
directly, so that global auth overrides (--token-file, --token-stdin,
--token-env, --email / JIRA_EMAIL) are honoured automatically.
"""

import click

from jira_api.client import JiraClient


def make_client(ctx: click.Context) -> JiraClient:
    """
    Build a JiraClient from the current Click context.

    Picks up any token / email overrides stored in ctx.obj by the root CLI
    group (set via --token-file, --token-stdin, --token-env, --email, or the
    JIRA_EMAIL env var).  Falls back to the standard JiraClient defaults
    (JIRA_TOKEN env var → ~/.jira/token file) when no override is present.
    """
    cfg = ctx.obj["config"]
    token = ctx.obj.get("token")  # None → JiraClient will read its own default
    email = ctx.obj.get("email")  # None → JiraClient will use config.email
    return JiraClient(cfg, token=token, email=email)
