# jiractl

`jiractl` is our internal Jira CLI where we build a bunch of the logic to save us time into.

Our API token is in ~/.jira/token

`jiractl` should fetch from this file or the env var JIRA_TOKEN

## Stack

- `click`: as our CLI framework
- `pandas`: for data loading, processing and output
- `rich`: for CLI pretty UI
- `pydantic`: for schema declaration and validation
