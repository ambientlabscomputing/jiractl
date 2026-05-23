import sys

import click

from commands.bug_report import _RECORDER_ACTIVE_KEY, BugRecorder, BugReportGroup
from models.config import Config


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
@click.pass_context
def cli(ctx: click.Context, report_bug: bool):
    """jiractl - Internal Jira CLI for batch loading data"""
    if ctx.obj is None:
        ctx.obj = {}
    try:
        ctx.obj["config"] = Config.load()
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)

    if report_bug and not ctx.obj.get(_RECORDER_ACTIVE_KEY):
        ctx.obj[_RECORDER_ACTIVE_KEY] = True
        ctx.with_resource(BugRecorder(ctx.obj["config"], sys.argv[1:]))


# Import commands after defining cli to avoid circular imports
from commands.batch.cmd import batch  # noqa: E402
from commands.comment.cmd import comment  # noqa: E402
from commands.config.cmd import config_group  # noqa: E402
from commands.create.cmd import create  # noqa: E402
from commands.delete.cmd import delete  # noqa: E402
from commands.describe.cmd import describe  # noqa: E402
from commands.edit.cmd import edit  # noqa: E402
from commands.export.cmd import export  # noqa: E402
from commands.inspect.cmd import inspect  # noqa: E402
from commands.list.cmd import list_issues  # noqa: E402
from commands.search.cmd import search  # noqa: E402
from commands.status.cmd import status  # noqa: E402
from commands.version import version  # noqa: E402

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
cli.add_command(version)


if __name__ == "__main__":
    cli()
