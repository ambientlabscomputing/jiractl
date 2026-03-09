import click
from pathlib import Path
import tempfile
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from models.config import Config
from models.epic import Epic
from models.ticket import Story
from jira_api.client import JiraClient
from jira_api.issues import create_epic, create_story
from commands.batch.transform.cmd import transform as transform_cmd
from commands.batch.validate.cmd import validate_epics, validate_stories


console = Console()


def load_csv_files(input_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load epics.csv and stories.csv from directory"""
    epics_file = input_dir / "epics.csv"
    stories_file = input_dir / "stories.csv"

    if not epics_file.exists():
        raise click.ClickException(f"epics.csv not found in {input_dir}")
    if not stories_file.exists():
        raise click.ClickException(f"stories.csv not found in {input_dir}")

    epics_df = pd.read_csv(epics_file)
    stories_df = pd.read_csv(stories_file)
    return epics_df, stories_df


@click.command()
@click.argument("input_dir", type=click.Path(exists=True))
@click.option("--transform", is_flag=True, help="Transform input files first")
@click.option("--dry-run", is_flag=True, help="Show what would be created without hitting Jira")
@click.option(
    "-p",
    "--project",
    type=str,
    default=None,
    help="Project key (overrides detected project)",
)
@click.pass_context
def upload(
    ctx: click.Context,
    input_dir: str,
    transform: bool,
    dry_run: bool,
    project: str,
):
    """Upload stories and epics to Jira"""
    config: Config = ctx.obj["config"]
    input_path = Path(input_dir)

    # If --transform, run transform first into a temp directory
    if transform:
        with tempfile.TemporaryDirectory() as tmpdir:
            console.print("[cyan]Running transform...[/cyan]")
            # Use click invoke to run transform command
            transform_ctx = ctx.obj
            transform_cmd.invoke(
                click.Context(
                    transform_cmd,
                    obj={"config": config},
                ),
                input_files=(input_dir,),
                output_dir=tmpdir,
                project=project,
            )
            input_path = Path(tmpdir)

    # Load and validate files
    console.print("[cyan]Validating files...[/cyan]")
    epics_df, stories_df = load_csv_files(input_path)
    valid_epics, epic_errors = validate_epics(epics_df, config)
    valid_stories, story_errors = validate_stories(stories_df, config, valid_epics)

    if epic_errors or story_errors:
        console.print(
            f"[red]Validation failed: {len(epic_errors) + len(story_errors)} errors[/red]"
        )
        ctx.exit(1)

    console.print(f"[green]✓ Validation passed ({len(valid_epics)} epics, {len(valid_stories)} stories)[/green]")

    if dry_run:
        console.print("\n[yellow]DRY RUN MODE[/yellow]")
        console.print("Would create the following issues:\n")

        table = Table(title="Issues to Create")
        table.add_column("Type", style="cyan")
        table.add_column("Key", style="green")
        table.add_column("Summary")
        table.add_column("Project", style="magenta")

        # Show epics
        for epic in valid_epics:
            table.add_row("Epic", f"[TBD]", epic.summary, epic.project_key)

        # Show stories
        for story in valid_stories:
            table.add_row("Story", f"[TBD]", story.summary, story.project_key)

        console.print(table)
        console.print("\n[yellow]No issues created (dry-run mode)[/yellow]")
        return

    # Actually upload
    console.print("\n[cyan]Uploading to Jira...[/cyan]")

    with JiraClient(config) as client:
        created_issues = []
        epic_key_map = {}  # epic_name -> jira_key

        # Create epics first
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task_id = progress.add_task("Creating epics...", total=len(valid_epics))

            for epic in valid_epics:
                try:
                    jira_key = create_epic(
                        client,
                        epic.project_key,
                        epic.epic_name,
                        epic.summary,
                        epic.description,
                    )
                    epic_key_map[epic.epic_name] = jira_key
                    created_issues.append(
                        {
                            "type": "Epic",
                            "key": jira_key,
                            "summary": epic.summary,
                            "project": epic.project_key,
                        }
                    )
                    progress.update(task_id, advance=1)
                except Exception as e:
                    console.print(
                        f"[red]✗ Failed to create epic '{epic.summary}': {e}[/red]"
                    )
                    progress.update(task_id, advance=1)

        # Create stories
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task_id = progress.add_task("Creating stories...", total=len(valid_stories))

            for story in valid_stories:
                try:
                    # Resolve epic link to jira key
                    epic_jira_key = epic_key_map.get(story.epic_link)
                    if not epic_jira_key:
                        console.print(
                            f"[red]✗ Story '{story.summary}': Epic '{story.epic_link}' not created[/red]"
                        )
                        progress.update(task_id, advance=1)
                        continue

                    jira_key = create_story(
                        client,
                        story.project_key,
                        story.summary,
                        story.description,
                        epic_jira_key,
                    )
                    created_issues.append(
                        {
                            "type": "Story",
                            "key": jira_key,
                            "summary": story.summary,
                            "project": story.project_key,
                        }
                    )
                    progress.update(task_id, advance=1)
                except Exception as e:
                    console.print(
                        f"[red]✗ Failed to create story '{story.summary}': {e}[/red]"
                    )
                    progress.update(task_id, advance=1)

    # Print summary
    console.print("\n")
    summary_table = Table(title="Upload Summary")
    summary_table.add_column("Type", style="cyan")
    summary_table.add_column("Key", style="green")
    summary_table.add_column("Summary")
    summary_table.add_column("Project", style="magenta")

    for issue in created_issues:
        summary_table.add_row(
            issue["type"],
            issue["key"],
            issue["summary"],
            issue["project"],
        )

    console.print(summary_table)

    console.print(f"\n[green]✓ Created {len(created_issues)} issues[/green]")
    if config.base_url:
        console.print(f"View in Jira: {config.base_url}/browse")

