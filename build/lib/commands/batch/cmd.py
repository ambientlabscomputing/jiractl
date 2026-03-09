import click


@click.group()
@click.pass_context
def batch(ctx: click.Context):
    """Batch loading data: transform, validate, and upload"""
    pass


# Import subcommands
from commands.batch.transform.cmd import transform
from commands.batch.validate.cmd import validate
from commands.batch.upload.cmd import upload

batch.add_command(transform)
batch.add_command(validate)
batch.add_command(upload)
