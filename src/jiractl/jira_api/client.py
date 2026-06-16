import os
import sys
import time
from pathlib import Path

import httpx
from rich.console import Console

from jiractl.models.config import Config

console = Console()


def resolve_token_override(
    token_file: str | None = None,
    token_stdin: bool = False,
    token_env: str | None = None,
) -> str:
    """
    Resolve a Jira API token from an explicit CLI override source.

    Exactly one of token_file, token_stdin, or token_env should be provided.
    The sources are tried in that order; the first match wins.

    Raises FileNotFoundError / ValueError with an actionable message if the
    source is specified but yields no token.
    """
    if token_file is not None:
        path = Path(token_file)
        if not path.exists():
            raise FileNotFoundError(
                f"Token file not found: {token_file}\nEnsure the path is correct and the file is readable."
            )
        token = path.read_text().strip()
        if not token:
            raise ValueError(f"Token file is empty: {token_file}")
        return token

    if token_stdin:
        token = sys.stdin.read().strip()
        if not token:
            raise ValueError(
                "No token received from stdin. "
                "Pipe the token value before running: echo $TOKEN | jiractl --token-stdin ..."
            )
        return token

    if token_env is not None:
        token = os.environ.get(token_env, "").strip()
        if not token:
            raise FileNotFoundError(
                f"Environment variable '{token_env}' is not set or is empty.\n"
                f"Set it before running: export {token_env}=<your-token>"
            )
        return token

    raise ValueError("resolve_token_override() called with no override source specified.")


# Retry settings
_MAX_RETRIES = 4
_RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each attempt: 1, 2, 4, 8
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
            wait = _RETRY_BACKOFF_BASE * (2**attempt)

        console.print(
            f"[yellow]⚠ HTTP {response.status_code} — retrying in {wait:.1f}s "
            f"(attempt {attempt + 1}/{_MAX_RETRIES})[/yellow]"
        )
        time.sleep(wait)

    # Should not reach here
    response.raise_for_status()
    return response


class JiraClient:
    """HTTP client for interacting with Jira Cloud REST API v3"""

    def __init__(
        self,
        config: Config,
        token: str | None = None,
        email: str | None = None,
    ):
        self.config = config
        self.token = token if token is not None else self._read_token()
        effective_email = email if email is not None else config.email

        auth = httpx.BasicAuth(effective_email, self.token)
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

        raise FileNotFoundError("Jira API token not found. Set JIRA_TOKEN env var or create ~/.jira/token")

    def _url(self, path: str) -> str:
        if path.startswith("http") or path.startswith("/rest/agile/"):
            return path
        return f"/rest/api/3{path}"

    def get(self, path: str, params: dict | None = None) -> dict:
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
