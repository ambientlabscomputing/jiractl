from pathlib import Path

import click
import pandas as pd
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from jiractl.models.config import Config
from jiractl.models.epic import Epic
from jiractl.models.ticket import Story

console = Console()


def validate_epics(epics_df: pd.DataFrame, config: Config) -> tuple[list[Epic], list[dict]]:
    """
    Validate epics CSV. Returns (valid_epics, error_list)
    error_list contains dicts with row index and error message
    """
    valid = []
    errors = []

    for idx, row in epics_df.iterrows():
        try:
            epic = Epic(
                epic_name=row["Epic Name"],
                summary=row["Summary"],
                description=row["Description"],
                project_key=row["Project Key"],
            )
            # Validate project key
            if epic.project_key not in config.allowed_projects:
                errors.append(
                    {
                        "row": idx + 2,  # +2 for header and 1-based indexing
                        "error": f"Project key '{epic.project_key}' not in allowed_projects",
                    }
                )
            else:
                valid.append(epic)
        except ValidationError as e:
            errors.append(
                {
                    "row": idx + 2,
                    "error": "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors()),
                }
            )

    return valid, errors


def validate_stories(stories_df: pd.DataFrame, config: Config, epics: list[Epic]) -> tuple[list[Story], list[dict]]:
    """
    Validate stories CSV. Returns (valid_stories, error_list)
    error_list contains dicts with row index and error message
    """
    valid = []
    errors = []
    epic_names = {epic.epic_name for epic in epics}

    for idx, row in stories_df.iterrows():
        try:
            story = Story(
                summary=row["Summary"],
                description=row["Description"],
                epic_link=row["Epic Link"],
                project_key=row["Project Key"],
            )
            # Validate project key
            if story.project_key not in config.allowed_projects:
                errors.append(
                    {
                        "row": idx + 2,
                        "error": f"Project key '{story.project_key}' not in allowed_projects",
                    }
                )
                continue

            # Validate epic link
            if story.epic_link not in epic_names:
                errors.append(
                    {
                        "row": idx + 2,
                        "error": f"Epic link '{story.epic_link}' not found in epics",
                    }
                )
                continue

            valid.append(story)
        except ValidationError as e:
            errors.append(
                {
                    "row": idx + 2,
                    "error": "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors()),
                }
            )

    return valid, errors


@click.command()
@click.argument("input_dir", type=click.Path(exists=True))
@click.pass_context
def validate(ctx: click.Context, input_dir: str):
    """Validate stories.csv and epics.csv files"""
    config: Config = ctx.obj["config"]
    input_path = Path(input_dir)

    epics_file = input_path / "epics.csv"
    stories_file = input_path / "stories.csv"

    if not epics_file.exists():
        raise click.ClickException(f"epics.csv not found in {input_dir}")
    if not stories_file.exists():
        raise click.ClickException(f"stories.csv not found in {input_dir}")

    # Load CSVs
    epics_df = pd.read_csv(epics_file)
    stories_df = pd.read_csv(stories_file)

    # Validate
    valid_epics, epic_errors = validate_epics(epics_df, config)
    valid_stories, story_errors = validate_stories(stories_df, config, valid_epics)

    # Print results
    console.print()

    # Epics table
    epics_table = Table(title="Epics Validation")
    epics_table.add_column("Row", style="cyan")
    epics_table.add_column("Status", style="magenta")
    epics_table.add_column("Message")

    for idx, epic in enumerate(valid_epics):
        epics_table.add_row(
            str(idx + 2),
            "[green]✓[/green]",
            f"{epic.epic_name} ({epic.project_key})",
        )

    for error in epic_errors:
        epics_table.add_row(str(error["row"]), "[red]✗[/red]", f"[red]{error['error']}[/red]")

    console.print(epics_table)

    # Stories table
    stories_table = Table(title="Stories Validation")
    stories_table.add_column("Row", style="cyan")
    stories_table.add_column("Status", style="magenta")
    stories_table.add_column("Message")

    for idx, story in enumerate(valid_stories):
        stories_table.add_row(
            str(idx + 2),
            "[green]✓[/green]",
            f"{story.summary} ({story.epic_link})",
        )

    for error in story_errors:
        stories_table.add_row(str(error["row"]), "[red]✗[/red]", f"[red]{error['error']}[/red]")

    console.print(stories_table)

    # Summary
    console.print()
    summary_table = Table(title="Validation Summary")
    summary_table.add_column("Category", style="cyan")
    summary_table.add_column("Valid", style="green")
    summary_table.add_column("Errors", style="red")
    summary_table.add_row("Epics", str(len(valid_epics)), str(len(epic_errors)))
    summary_table.add_row("Stories", str(len(valid_stories)), str(len(story_errors)))
    console.print(summary_table)

    # Exit code
    if epic_errors or story_errors:
        console.print(f"\n[red]Validation failed: {len(epic_errors) + len(story_errors)} errors[/red]")
        ctx.exit(1)
    else:
        console.print("\n[green]✓ All files valid[/green]")
