import sys

import click

from jiractl.commands.bug_report import (
    _RECORDER_ACTIVE_KEY,
    BugRecorder,
    BugReportGroup,
)
from jiractl.jira_api.client import resolve_token_override
from jiractl.models.config import Config


@click.group(cls=BugReportGroup)
@click.option(
    "--report-bug",
    "report_bug",
    is_flag=True,
    default=False,
    help=(
        "Capture this invocation (argv, output, traceback) and file a bug "
        "ticket to the configured DEV project at the end of the command."
    ),
)
@click.option(
    "--token-file",
    "token_file",
    default=None,
    metavar="PATH",
    help="Read the Jira API token from a file (e.g. a CI secret mount).",
)
@click.option(
    "--token-stdin",
    "token_stdin",
    is_flag=True,
    default=False,
    help="Read the Jira API token from stdin (pipe-friendly, leaves no trace in shell history).",
)
@click.option(
    "--token-env",
    "token_env",
    default=None,
    metavar="NAME",
    help="Read the Jira API token from the named environment variable (e.g. JIRA_BOT_TOKEN).",
)
@click.option(
    "--email",
    "email_override",
    default=None,
    metavar="ADDRESS",
    envvar="JIRA_EMAIL",
    help=(
        "Override the email used for Jira authentication "
        "(useful for bot accounts in pipelines). "
        "Also reads from JIRA_EMAIL env var."
    ),
)
@click.option(
    "--config",
    "config_path",
    default=None,
    metavar="PATH",
    envvar="JIRACTL_CONFIG",
    type=click.Path(exists=True, dir_okay=False),
    help=(
        "Path to a jiractl config YAML file. "
        "Defaults to jiractl.config.yaml in the current directory, "
        "then ~/.jira/config.yaml. Also reads from JIRACTL_CONFIG env var."
    ),
)
@click.pass_context
def cli(
    ctx: click.Context,
    report_bug: bool,
    token_file,
    token_stdin,
    token_env,
    email_override,
    config_path,
):
    """jiractl - Internal Jira CLI for batch loading data"""
    if ctx.obj is None:
        ctx.obj = {}
    try:
        ctx.obj["config"] = Config.load(config_path)
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)

    # Validate mutual exclusivity of token override flags
    token_sources = [s for s in [token_file, token_stdin or None, token_env] if s is not None]
    if len(token_sources) > 1:
        raise click.UsageError("Only one of --token-file, --token-stdin, or --token-env may be used at a time.")

    # Resolve explicit token override eagerly (reads file/stdin/env once here)
    if token_file or token_stdin or token_env:
        try:
            ctx.obj["token"] = resolve_token_override(
                token_file=token_file,
                token_stdin=token_stdin,
                token_env=token_env,
            )
        except (FileNotFoundError, ValueError) as e:
            click.secho(f"Error: {e}", fg="red", err=True)
            ctx.exit(1)

    # Store email override (flag already handles JIRA_EMAIL via envvar=)
    if email_override:
        ctx.obj["email"] = email_override

    if report_bug and not ctx.obj.get(_RECORDER_ACTIVE_KEY):
        ctx.obj[_RECORDER_ACTIVE_KEY] = True
        ctx.with_resource(
            BugRecorder(
                ctx.obj["config"],
                sys.argv[1:],
                token=ctx.obj.get("token"),
                email=ctx.obj.get("email"),
            )
        )


# Import commands after defining cli to avoid circular imports
from jiractl.commands.batch.cmd import batch  # noqa: E402
from jiractl.commands.comment.cmd import comment  # noqa: E402
from jiractl.commands.config.cmd import config_group  # noqa: E402
from jiractl.commands.create.cmd import create  # noqa: E402
from jiractl.commands.delete.cmd import delete  # noqa: E402
from jiractl.commands.describe.cmd import describe  # noqa: E402
from jiractl.commands.edit.cmd import edit  # noqa: E402
from jiractl.commands.export.cmd import export  # noqa: E402
from jiractl.commands.inspect.cmd import inspect  # noqa: E402
from jiractl.commands.list.cmd import list_issues  # noqa: E402
from jiractl.commands.prompt.cmd import to_prompt  # noqa: E402
from jiractl.commands.search.cmd import search  # noqa: E402
from jiractl.commands.status.cmd import status  # noqa: E402
from jiractl.commands.version import version  # noqa: E402

cli.add_command(batch)
cli.add_command(comment)
cli.add_command(config_group, name="config")
cli.add_command(create)
cli.add_command(delete)
cli.add_command(describe)
cli.add_command(edit)
cli.add_command(export)
cli.add_command(inspect)
cli.add_command(list_issues, name="list")
cli.add_command(search)
cli.add_command(status)
cli.add_command(to_prompt, name="to-prompt")
cli.add_command(version)


if __name__ == "__main__":
    cli()
