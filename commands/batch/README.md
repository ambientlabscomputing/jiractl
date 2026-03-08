# `jiractl batch` Command

This command is for batch loading data.

## Subcommands

- `transform`: turn a generic CSV into properly formatted stories.csv and epics.csv files by searching column names
- `validate`: validate stories.csv epics.csv files
- `upload`: Create jira tickets and epics from the stories.csv and epics.csv files

## Examples

Transform generic file into properly formatted files

```bash
jiractl batch transform <input-file(s)>  -o, --output-dir <output-directory> ## defaults to ./
```

Validate generated files

```bash
jiractl batch validate <input-dir>
```

Upload files

```bash
jiractl batch upload <input-dir>
```

All in one

```bash
jiractl batch upload <file(s)> --transform
```
