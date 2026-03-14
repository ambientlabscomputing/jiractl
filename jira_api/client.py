import os
import time
import httpx
from pathlib import Path
from rich.console import Console
from models.config import Config


console = Console()

# Retry settings
_MAX_RETRIES = 4
_RETRY_BACKOFF_BASE = 1.0   # seconds; doubles each attempt: 1, 2, 4, 8
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _request_with_retry(fn, *args, **kwargs) -> httpx.Response:
    """
    Call an httpx request function, retrying on transient errors.
    Respects Retry-After header on 429 responses.
    """
    for attempt in range(_MAX_RETRIES):
        response: httpx.Response = fn(*args, **kwargs)

        if response.status_code not in _RETRYABLE_STATUS:
            response.raise_for_status()
            return response

        if attempt == _MAX_RETRIES - 1:
            response.raise_for_status()

        # Determine wait time
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            wait = float(retry_after)
        else:
            wait = _RETRY_BACKOFF_BASE * (2 ** attempt)

        console.print(
            f"[yellow]⚠ HTTP {response.status_code} — retrying in {wait:.1f}s "
            f"(attempt {attempt + 1}/{_MAX_RETRIES})[/yellow]"
        )
        time.sleep(wait)

    # Should not reach here
    response.raise_for_status()
    return response  # type: ignore


class JiraClient:
    """HTTP client for interacting with Jira Cloud REST API v3"""

    def __init__(self, config: Config):
        self.config = config
        self.token = self._read_token()

        auth = httpx.BasicAuth(config.email, self.token)
        self.client = httpx.Client(
            base_url=config.base_url,
            auth=auth,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

    def _read_token(self) -> str:
        """Read Jira API token from ~/.jira/token or JIRA_TOKEN env var"""
        token = os.getenv("JIRA_TOKEN")
        if token:
            return token

        token_file = Path.home() / ".jira" / "token"
        if token_file.exists():
            return token_file.read_text().strip()

        raise FileNotFoundError(
            "Jira API token not found. Set JIRA_TOKEN env var or create ~/.jira/token"
        )

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"/rest/api/3{path}"

    def get(self, path: str, params: dict = None) -> dict:
        """GET request with automatic retry"""
        response = _request_with_retry(self.client.get, self._url(path), params=params)
        return response.json()

    def post(self, path: str, payload: dict) -> dict | None:
        """POST request with automatic retry. Returns None for 204 No Content responses."""
        response = _request_with_retry(self.client.post, self._url(path), json=payload)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def put(self, path: str, payload: dict) -> dict | None:
        """PUT request with automatic retry. Returns None for 204 No Content responses."""
        response = _request_with_retry(self.client.put, self._url(path), json=payload)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def delete(self, path: str) -> None:
        """DELETE request with automatic retry. Returns None (Jira returns 204 No Content)."""
        _request_with_retry(self.client.delete, self._url(path))

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

