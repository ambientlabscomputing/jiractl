import os
from pathlib import Path
import httpx
from rich.console import Console
from models.config import Config


console = Console()


class JiraClient:
    """HTTP client for interacting with Jira Cloud REST API v3"""

    def __init__(self, config: Config):
        self.config = config
        self.token = self._read_token()
        
        # Create httpx client with basic auth
        auth = httpx.BasicAuth(config.email, self.token)
        self.client = httpx.Client(
            base_url=config.base_url,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

    def _read_token(self) -> str:
        """Read Jira API token from ~/.jira/token or JIRA_TOKEN env var"""
        # Try environment variable first
        token = os.getenv("JIRA_TOKEN")
        if token:
            return token

        # Try file
        token_file = Path.home() / ".jira" / "token"
        if token_file.exists():
            return token_file.read_text().strip()

        raise FileNotFoundError(
            "Jira API token not found. Set JIRA_TOKEN env var or create ~/.jira/token"
        )

    def get(self, path: str, params: dict = None) -> dict:
        """GET request to Jira API"""
        url = path if path.startswith("http") else f"/rest/api/3{path}"
        response = self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, payload: dict) -> dict:
        """POST request to Jira API"""
        url = path if path.startswith("http") else f"/rest/api/3{path}"
        response = self.client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def put(self, path: str, payload: dict) -> dict:
        """PUT request to Jira API"""
        url = path if path.startswith("http") else f"/rest/api/3{path}"
        response = self.client.put(url, json=payload)
        response.raise_for_status()
        return response.json()

    def close(self):
        """Close the HTTP client"""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
