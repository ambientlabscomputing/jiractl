"""
jiractl version — print the installed package version.
"""

import click


@click.command("version")
def version():
    """Print the jiractl version."""
    try:
        from importlib.metadata import version as _meta_version

        ver = _meta_version("jiractl")
    except Exception:
        from jiractl.commands._version import __version__

        ver = __version__

    click.echo(f"jiractl v{ver}")
