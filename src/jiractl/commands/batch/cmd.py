import click

from jiractl.commands.batch.transform.cmd import transform
from jiractl.commands.batch.upload.cmd import upload
from jiractl.commands.batch.validate.cmd import validate


@click.group()
@click.pass_context
def batch(ctx: click.Context):
    """Batch loading data: transform, validate, and upload"""
    pass


batch.add_command(transform)
batch.add_command(validate)
batch.add_command(upload)
