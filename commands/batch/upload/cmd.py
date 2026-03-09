import json
import click
from pathlib import Path
import tempfile
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from models.config import Config
from jira_api.client import JiraClient
from jira_api.issues import create_epic, create_story
from commands.batch.transform.cmd import run_transform
from commands.batch.validate.cmd import validate_epics, validate_stories


console = Console()

STATE_FILE = "upload_state.json"


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------

def _state_path(input_dir: Path) -> Path:
    return input_dir / STATE_FILE


def _load_state(input_dir: Path) -> dict:
    """Load existing upload state, or return a fresh empty state."""
    path = _state_path(input_dir)
    if path.exists():
        return json.loads(path.read_text())
    return {"epics": {}, "stories": {}, "failures": []}


def _save_state(input_dir: Path, state: dict) -> None:
    """Persist state to disk immediately (called after every successful creation)."""
    _state_path(input_dir).write_text(json.dumps(state, indent=2))


def _story_key(story) -> str:
    """Stable identifier for a story used in the state file."""
    return f"{story.project_key}|{story.epic_link}|{story.summary}"


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
@click.option("--reset", is_flag=True, help="Ignore saved state and start from scratch (re-creates everything)")
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
    reset: bool,
    project: str,
):
    """Upload stories and epics to Jira"""
    config: Config = ctx.obj["config"]
    input_path = Path(input_dir)

    # Wipe state file if --reset requested
    if reset:
        state_file = _state_path(input_path)
        if state_file.exists():
            state_file.unlink()
            console.print("[yellow]State file cleared — starting from scratch[/yellow]")

    # If --transform, run transform first into a temp directory
    tmpdir_obj = None
    if transform:
        console.print("[cyan]Running transform...[/cyan]")
        tmpdir_obj = tempfile.TemporaryDirectory()
        input_path = run_transform(
            input_files=(input_dir,),
            output_dir=tmpdir_obj.name,
            config=config,
            project=project,
        )

    try:
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
            existing_state = _load_state(input_path)
            console.print("\n[yellow]DRY RUN MODE[/yellow]")
            if existing_state["epics"] or existing_state["stories"]:
                console.print(
                    f"[dim]Existing state: {len(existing_state['epics'])} epics, "
                    f"{len(existing_state['stories'])} stories already created "
                    f"(would be skipped)[/dim]"
                )
            console.print("Would create the following issues:\n")

            table = Table(title="Issues to Create")
            table.add_column("Type", style="cyan")
            table.add_column("Key", style="green")
            table.add_column("Summary")
            table.add_column("Project", style="magenta")
            table.add_column("Action", style="dim")

            for epic in valid_epics:
                if epic.epic_name in existing_state["epics"]:
                    table.add_row("Epic", existing_state["epics"][epic.epic_name], epic.summary, epic.project_key, "skip")
                else:
                    table.add_row("Epic", "[TBD]", epic.summary, epic.project_key, "create")
            for story in valid_stories:
                sk = _story_key(story)
                if sk in existing_state["stories"]:
                    table.add_row("Story", existing_state["stories"][sk], story.summary, story.project_key, "skip")
                else:
                    table.add_row("Story", "[TBD]", story.summary, story.project_key, "create")

            console.print(table)
            console.print("\n[yellow]No issues created (dry-run mode)[/yellow]")
            return

        # Actually upload
        console.print("\n[cyan]Uploading to Jira...[/cyan]")

        # Load any existing state (enables idempotent re-runs)
        state = _load_state(input_path)
        if state["epics"] or state["stories"]:
            console.print(
                f"[yellow]Resuming: {len(state['epics'])} epics and "
                f"{len(state['stories'])} stories already created[/yellow]"
            )

        with JiraClient(config) as client:
            created_issues = []
            failures = []
            # Seed epic_key_map from state so stories can link to previously created epics
            epic_key_map: dict[str, str] = dict(state["epics"])

            # ---- Epics ----
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task_id = progress.add_task("Creating epics...", total=len(valid_epics))
                for epic in valid_epics:
                    progress.update(task_id, advance=1)
                    if epic.epic_name in state["epics"]:
                        # Already created on a previous run — skip
                        console.print(
                            f"[dim]↩ Skipping epic '{epic.epic_name}' "
                            f"(already {state['epics'][epic.epic_name]})[/dim]"
                        )
                        continue
                    try:
                        jira_key = create_epic(
                            client,
                            epic.project_key,
                            epic.epic_name,
                            epic.summary,
                            epic.description,
                        )
                        epic_key_map[epic.epic_name] = jira_key
                        state["epics"][epic.epic_name] = jira_key
                        _save_state(input_path, state)  # persist immediately
                        created_issues.append(
                            {"type": "Epic", "key": jira_key, "summary": epic.summary, "project": epic.project_key}
                        )
                    except Exception as e:
                        msg = str(e)
                        console.print(f"[red]✗ Epic '{epic.summary}': {msg}[/red]")
                        failures.append({"type": "Epic", "summary": epic.summary, "error": msg})

            # ---- Stories ----
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task_id = progress.add_task("Creating stories...", total=len(valid_stories))
                for story in valid_stories:
                    progress.update(task_id, advance=1)
                    sk = _story_key(story)

                    if sk in state["stories"]:
                        # Already created — skip
                        console.print(
                            f"[dim]↩ Skipping story '{story.summary}' "
                            f"(already {state['stories'][sk]})[/dim]"
                        )
                        continue

                    epic_jira_key = epic_key_map.get(story.epic_link)
                    if not epic_jira_key:
                        msg = f"Epic '{story.epic_link}' was not created — cannot link story"
                        console.print(f"[red]✗ Story '{story.summary}': {msg}[/red]")
                        failures.append({"type": "Story", "summary": story.summary, "error": msg})
                        continue

                    try:
                        jira_key = create_story(
                            client,
                            story.project_key,
                            story.summary,
                            story.description,
                            epic_jira_key,
                        )
                        state["stories"][sk] = jira_key
                        _save_state(input_path, state)  # persist immediately
                        created_issues.append(
                            {"type": "Story", "key": jira_key, "summary": story.summary, "project": story.project_key}
                        )
                    except Exception as e:
                        msg = str(e)
                        console.print(f"[red]✗ Story '{story.summary}': {msg}[/red]")
                        failures.append({"type": "Story", "summary": story.summary, "error": msg})

            # Persist failures to state for reference
            state["failures"] = failures
            _save_state(input_path, state)

        # ---- Summary ----
        console.print("\n")
        summary_table = Table(title="Upload Summary")
        summary_table.add_column("Type", style="cyan")
        summary_table.add_column("Key", style="green")
        summary_table.add_column("Summary")
        summary_table.add_column("Project", style="magenta")
        for issue in created_issues:
            summary_table.add_row(issue["type"], issue["key"], issue["summary"], issue["project"])
        console.print(summary_table)

        total_created = len(created_issues)
        total_skipped = len(state["epics"]) + len(state["stories"]) - total_created
        console.print(f"\n[green]✓ Created {total_created} issues[/green]", end="")
        if total_skipped:
            console.print(f"  [dim]({total_skipped} already existed, skipped)[/dim]", end="")
        console.print()

        if failures:
            console.print(f"\n[red]✗ {len(failures)} failures — re-run to retry them[/red]")
            for f in failures:
                console.print(f"  [red]• {f['type']}: {f['summary']}[/red]")
            console.print(f"\n[dim]State saved to {_state_path(input_path)}[/dim]")
        else:
            console.print(f"[dim]State saved to {_state_path(input_path)}[/dim]")
            if config.base_url:
                console.print(f"View in Jira: {config.base_url}/browse")

    finally:
        if tmpdir_obj is not None:
            tmpdir_obj.cleanup()
