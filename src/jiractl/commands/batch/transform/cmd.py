from pathlib import Path

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

from jiractl.models.config import Config

console = Console()

# Canonical column names we're looking for
CANONICAL_COLUMNS = {
    "issue_type": ["issue type", "type"],
    "summary": ["summary", "title", "name"],
    "description": ["description", "desc"],
    "epic_name": ["epic name", "epic"],
    "epic_link": ["epic link", "epic"],
}


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """
    Detect which columns map to our canonical names.
    Returns a dict: canonical_name -> actual_column_name (or None if not found)
    """
    detected = {}
    df_columns_lower = {col.lower(): col for col in df.columns}

    for canonical, aliases in CANONICAL_COLUMNS.items():
        found = None
        for alias in aliases:
            if alias in df_columns_lower:
                found = df_columns_lower[alias]
                break
        detected[canonical] = found

    return detected


def get_project_key(input_filename: str, config: Config, project_flag: str | None) -> str:
    """
    Determine the project key from flag, filename, or user input.
    """
    # 1. Use flag if provided
    if project_flag:
        resolved = config.resolve_project(project_flag)
        if resolved:
            return resolved
        # Try as direct key
        if project_flag in config.allowed_projects:
            return project_flag
        raise ValueError(f"Project '{project_flag}' not found in config.allowed_projects or synonyms")

    # 2. Try to infer from filename
    filename_lower = Path(input_filename).stem.lower()
    for project_key, synonyms in config.synonyms.items():
        for synonym in synonyms:
            if synonym.lower() in filename_lower:
                return project_key

    # 3. Prompt user
    console.print("\nCould not determine project from filename. Available projects:")
    for i, proj in enumerate(config.allowed_projects, 1):
        console.print(f"  {i}. {proj}")

    choice = click.prompt("Select project", type=int, default=1)
    if 1 <= choice <= len(config.allowed_projects):
        return config.allowed_projects[choice - 1]

    raise ValueError("Invalid project selection")


def run_transform(
    input_files: tuple[str],
    output_dir: str,
    config: Config,
    project: str | None = None,
) -> Path:
    """
    Core transform logic — converts input CSV(s) into epics.csv and stories.csv.
    Returns the output directory path.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_epics = []
    all_stories = []

    for input_file in input_files:
        click.echo(f"Processing {input_file}...")

        # Find the first non-empty row to use as header
        skip_rows = 0
        with open(input_file) as f:
            for i, line in enumerate(f):
                if line.strip() and not all(c in "," for c in line.strip()):
                    skip_rows = i
                    break

        df = pd.read_csv(input_file, skiprows=skip_rows)
        df = df.dropna(how="all")
        df = df.loc[:, (df != "").any(axis=0)]
        df.columns = [str(col).strip() for col in df.columns]
        df = df.reset_index(drop=True)

        if df.empty:
            click.secho(f"  Warning: {input_file} is empty after cleaning", fg="yellow")
            continue

        cols = detect_columns(df)

        if not cols["issue_type"]:
            raise ValueError(f"{input_file}: Could not find 'issue type' column. Found: {list(df.columns)}")
        if not cols["summary"]:
            raise ValueError(f"{input_file}: Could not find 'summary' column. Found: {list(df.columns)}")
        if not cols["description"]:
            raise ValueError(f"{input_file}: Could not find 'description' column. Found: {list(df.columns)}")

        project_key = get_project_key(input_file, config, project)

        for _idx, row in df.iterrows():
            issue_type = str(row[cols["issue_type"]]).strip().lower()
            summary = str(row[cols["summary"]]).strip()
            description = str(row[cols["description"]]).strip() if pd.notna(row[cols["description"]]) else ""

            if issue_type == "epic":
                epic_name = str(row[cols["epic_name"]]).strip() if cols["epic_name"] else summary
                all_epics.append(
                    {
                        "Project Key": project_key,
                        "Epic Name": epic_name,
                        "Summary": summary,
                        "Description": description,
                    }
                )

            elif issue_type == "story":
                epic_link = (
                    str(row[cols["epic_link"]]).strip()
                    if cols["epic_link"] and pd.notna(row[cols["epic_link"]])
                    else ""
                )
                all_stories.append(
                    {
                        "Project Key": project_key,
                        "Summary": summary,
                        "Description": description,
                        "Epic Link": epic_link,
                    }
                )

    epics_df = pd.DataFrame(all_epics)
    stories_df = pd.DataFrame(all_stories)

    epics_path = output_path / "epics.csv"
    stories_path = output_path / "stories.csv"

    epics_df.to_csv(epics_path, index=False)
    stories_df.to_csv(stories_path, index=False)

    # Print summary
    console.print()
    table = Table(title="Transform Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")
    table.add_row("Epics", str(len(epics_df)))
    table.add_row("Stories", str(len(stories_df)))
    console.print(table)
    console.print(f"\n[green]✓[/green] Epics written to {epics_path}")
    console.print(f"[green]✓[/green] Stories written to {stories_path}")

    return output_path


@click.command()
@click.argument("input_files", nargs=-1, type=click.Path(exists=True), required=True)
@click.option(
    "-o",
    "--output-dir",
    type=click.Path(),
    default="./",
    help="Output directory (defaults to current dir)",
)
@click.option(
    "-p",
    "--project",
    type=str,
    default=None,
    help="Project key or synonym (auto-detected from filename if not provided)",
)
@click.pass_context
def transform(
    ctx: click.Context,
    input_files: tuple[str],
    output_dir: str,
    project: str | None,
):
    """Transform generic CSV files into epics.csv and stories.csv"""
    config: Config = ctx.obj["config"]
    run_transform(input_files, output_dir, config, project)
