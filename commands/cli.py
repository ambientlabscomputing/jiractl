import click
from models.config import Config


@click.group()
@click.pass_context
def cli(ctx: click.Context):
    """jiractl - Internal Jira CLI for batch loading data"""
    if ctx.obj is None:
        ctx.obj = {}
    try:
        ctx.obj["config"] = Config.load()
    except FileNotFoundError as e:
        click.secho(f"Error: {e}", fg="red", err=True)
        ctx.exit(1)


# Import commands after defining cli to avoid circular imports
from commands.batch.cmd import batch
from commands.config.cmd import config_group
from commands.create.cmd import create
from commands.describe.cmd import describe
from commands.list.cmd import list_issues
from commands.search.cmd import search

cli.add_command(batch)
cli.add_command(config_group, name="config")
cli.add_command(create)
cli.add_command(describe)
cli.add_command(list_issues, name="list")
cli.add_command(search)


if __name__ == "__main__":
    cli()
