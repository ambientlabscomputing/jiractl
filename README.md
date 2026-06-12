# jiractl

An internal CLI for managing Jira issues, running batch uploads, and scripting common workflows against the Jira Cloud REST API v3.

**Python ≥ 3.13 · Click · Rich · httpx · Pydantic**

Latest Version: `v1.1.0`

---

## Installation

```bash
pip install -e .
```

This registers the `jiractl` entry point so the command is available globally in your active environment.

---

## Authentication

`jiractl` uses HTTP Basic auth (email + API token).

1. Generate a token at **Atlassian Account → Security → API tokens**.
2. Store it in `~/.jira/token` (plain text, one line), **or** export it as an environment variable:

```bash
export JIRA_TOKEN=your_token_here
```

The environment variable takes precedence over the file.

---

## Configuration

On startup `jiractl` looks for a config file in this order:

1. `./jiractl.config.yaml` (project-local)
2. `~/.jira/config.yaml` (user-global)

**Minimal config:**

```yaml
base_url: https://your-org.atlassian.net
email: you@example.com
allowed_projects:
  - PROJ
```

**Full config options:**

| Field | Type | Description |
|---|---|---|
| `base_url` | string | Your Jira Cloud base URL |
| `email` | string | Email address for Basic auth |
| `allowed_projects` | list[str] | Project keys the tool is permitted to write to |
| `synonyms` | dict[str, list[str]] | Friendly aliases for project keys (e.g. `PROJ: [myproject, proj]`) |
| `issue_types` | dict[str, list[str]] | Issue types per project — auto-populated by `jiractl config populate` |

**Bootstrap issue types from Jira:**

```bash
jiractl config populate          # writes issue_types into your config
jiractl config populate --dry-run  # preview without writing
```

---

## Output Formats

Every command that returns data supports `--format`:

| Value | Output |
|---|---|
| `table` | Rich-rendered terminal table (default) |
| `json` | JSON on stdout — pipe-friendly |
| `bash` | Tab-separated key-value pairs — script-friendly |

```bash
jiractl list --project PROJ --format json | jq '.[] | .key'
jiractl describe PROJ-1 --format bash
```

---

## Commands

### `list` — Browse issues

```bash
jiractl list                              # show configured projects
jiractl list -p PROJ                      # all issues in a project
jiractl list -p PROJ -t Story -s "In Progress"
jiractl list --mine                       # issues assigned to you
jiractl list -p PROJ --epics-only
jiractl list -p PROJ --text "login flow" -n 20
```

**Flags:** `-p/--project`, `-t/--type`, `-s/--status`, `--assignee`, `--text`, `--mine`, `--epics-only`, `--epic`, `-n/--limit` (default 50)

---

### `describe` — Issue detail

```bash
jiractl describe PROJ-1
jiractl describe PROJ-1 --children       # epic + child issues
jiractl describe --epic PROJ-1           # alias for the above
jiractl describe PROJ-1 --comments
```

---

### `search` — JQL or query-builder

```bash
jiractl search 'project = PROJ AND label = "backend"'
jiractl search -p PROJ -t Bug -s "To Do" --since 2026-01-01
jiractl search -p PROJ --text "auth" --show-jql    # print generated JQL first
```

Structured flags and raw JQL can be combined — flags are ANDed into the query.

**Flags:** `[JQL]`, `-p`, `-t`, `-s`, `-a/--assignee`, `--text`, `--label`, `--since DATE`, `-n/--limit`, `--show-jql`

---

### `create` — Create issues

```bash
jiractl create epic -p PROJ -s "New epic"
jiractl create ticket -p PROJ -e PROJ-42 -s "Subtask" -t Task
jiractl create ticket -p PROJ -s "Quick bug" -t Bug --dry-run
```

Prompts for any required field not supplied as a flag. Shows a preview panel before creating.

---

### `edit` — Update issue fields

```bash
jiractl edit PROJ-1 --summary "New title"
jiractl edit PROJ-1 --priority High --assignee me
jiractl edit PROJ-1 --add-label backend --remove-label wont-fix
jiractl edit PROJ-1 --parent PROJ-10           # reparent a ticket
jiractl edit PROJ-1 --dry-run                  # preview without applying
```

All changes are applied atomically in a single API request.

**Escape hatch — custom fields via `--raw-data`:**

```bash
# First, discover the custom field ID
jiractl inspect fields PROJ --issue-type Story --custom-only

# Then apply it directly
jiractl edit PROJ-1 --raw-data '{"fields":{"customfield_10014":"PROJ-42"}}'
```

`--raw-data` accepts any JSON object and deep-merges it into the Jira PUT request body, so any field the API supports can be set.

---

### `status` — View or transition status

```bash
jiractl status PROJ-1                    # current status
jiractl status PROJ-1 --list             # available transitions
jiractl status PROJ-1 "In Review"        # apply transition
```

---

### `comment` — Add comments

```bash
jiractl comment PROJ-1 "Looks good, merging."

# AI-attributed comment (prepends a timestamped blockquote banner)
jiractl comment PROJ-1 "Analysis complete." --agent "Claude"
```

---

### `inspect` — Explore project metadata

Use this before writing `--raw-data` payloads or scripting against unfamiliar projects.

```bash
# Project overview: issue types + available statuses
jiractl inspect project PROJ

# All fields for a given issue type
jiractl inspect fields PROJ --issue-type Story

# Only custom fields (to find customfield_XXXXX IDs)
jiractl inspect fields PROJ --issue-type Bug --custom-only

# Machine-readable output
jiractl inspect fields PROJ --format json
```

---

### `export` — Export issues to CSV

```bash
jiractl export -p PROJ                          # stdout
jiractl export -p PROJ -o issues.csv            # file
jiractl export -p PROJ -t Story --include-done  # include resolved issues
jiractl export -p PROJ --include-description    # add description column
```

---

### `delete` — Delete an issue

```bash
jiractl delete PROJ-1                    # prompts for confirmation
jiractl delete PROJ-1 --yes              # skip prompt (required in scripts)
jiractl delete PROJ-1 --yes --subtasks   # also delete sub-tasks
```

---

### `batch` — Batch CSV pipeline

Automates the full workflow of importing a spreadsheet of epics and stories into Jira. See [`commands/batch/README.md`](commands/batch/README.md) for detailed documentation.

```bash
# 1. Transform a raw CSV into the canonical format
jiractl batch transform data.csv -o ./out/ -p PROJ

# 2. Validate the output before uploading
jiractl batch validate ./out/

# 3. Upload to Jira (idempotent — safe to re-run after partial failures)
jiractl batch upload ./out/
jiractl batch upload ./out/ --dry-run    # preview without creating
jiractl batch upload ./out/ --transform  # transform + upload in one step
```

Upload state is tracked in `upload_state.json` inside the input directory. Already-created items are skipped on re-runs; pass `--reset` to start fresh.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=. --cov-report=term-missing
```

Tests use `pytest-httpx` to mock Jira API responses — no real Jira instance required.

