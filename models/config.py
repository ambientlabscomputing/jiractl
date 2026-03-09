import os
from pathlib import Path
from pydantic import BaseModel
import yaml


class Config(BaseModel):
    base_url: str
    email: str
    allowed_projects: list[str]
    synonyms: dict[str, list[str]] = {}
    # issue_types populated by `jiractl config populate`
    # Maps project key -> list of issue type names available in that project
    issue_types: dict[str, list[str]] = {}

    @classmethod
    def load(cls, config_path: str | None = None) -> "Config":
        """
        Load config from a YAML file.
        Tries paths in order: provided path, current directory, ~/.jira/config.yaml
        """
        if config_path is None:
            # Try current directory first, then home directory
            candidates = [
                Path("jiractl.config.yaml"),
                Path.home() / ".jira" / "config.yaml",
            ]
            config_path = None
            for candidate in candidates:
                if candidate.exists():
                    config_path = candidate
                    break

            if config_path is None:
                raise FileNotFoundError(
                    "No config.yaml found. Tried: jiractl.config.yaml, ~/.jira/config.yaml"
                )
        else:
            config_path = Path(config_path)

        with open(config_path) as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def resolve_project(self, name: str) -> str | None:
        """
        Resolve a friendly project name to its key.
        Checks: exact match in allowed_projects, then synonym matching.
        Returns the project key or None if not found.
        """
        # Exact match
        if name in self.allowed_projects:
            return name

        # Synonym match
        for project_key, synonyms in self.synonyms.items():
            if name in synonyms:
                return project_key

        return None

    def save(self, config_path: Path | None = None) -> Path:
        """
        Write the config back to a YAML file.
        Uses config_path if given, otherwise jiractl.config.yaml in cwd.
        Returns the path written to.
        """
        if config_path is None:
            config_path = Path("jiractl.config.yaml")
        data = self.model_dump(exclude_none=True)
        # Don't write empty issue_types / synonyms dicts
        if not data.get("issue_types"):
            data.pop("issue_types", None)
        if not data.get("synonyms"):
            data.pop("synonyms", None)
        with open(config_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        return config_path