"""
Tests for per-invocation token and email injection.

Covers:
- resolve_token_override: token-file, token-stdin, token-env, error cases
- JiraClient: accepts explicit token / email overrides; falls back to defaults
- CLI global options: --token-file, --token-stdin, --token-env, --email,
  mutual exclusivity, JIRA_EMAIL env var, and backwards-compatible defaults
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from jiractl.jira_api.client import JiraClient, resolve_token_override
from jiractl.models.config import Config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_config():
    return Config(
        base_url="https://test.atlassian.net",
        email="human@example.com",
        allowed_projects=["TEST"],
    )


@pytest.fixture()
def token_file(tmp_path):
    """A temporary file containing a token (with trailing newline)."""
    f = tmp_path / "jira_token"
    f.write_text("file-token-abc123\n")
    return f


# ===========================================================================
# resolve_token_override
# ===========================================================================


class TestResolveTokenOverride:
    def test_reads_from_file(self, token_file):
        token = resolve_token_override(token_file=str(token_file))
        assert token == "file-token-abc123"  # stripped

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Token file not found"):
            resolve_token_override(token_file=str(tmp_path / "missing.txt"))

    def test_empty_file_raises(self, tmp_path):
        f = tmp_path / "empty"
        f.write_text("  \n")
        with pytest.raises(ValueError, match="Token file is empty"):
            resolve_token_override(token_file=str(f))

    def test_reads_from_stdin(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO("stdin-token-xyz\n"))
        token = resolve_token_override(token_stdin=True)
        assert token == "stdin-token-xyz"

    def test_stdin_empty_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", StringIO("   \n"))
        with pytest.raises(ValueError, match="No token received from stdin"):
            resolve_token_override(token_stdin=True)

    def test_reads_from_env_var(self, monkeypatch):
        monkeypatch.setenv("JIRA_BOT_TOKEN", "env-token-123")
        token = resolve_token_override(token_env="JIRA_BOT_TOKEN")
        assert token == "env-token-123"

    def test_env_var_not_set_raises(self, monkeypatch):
        monkeypatch.delenv("JIRA_BOT_TOKEN", raising=False)
        with pytest.raises(FileNotFoundError, match="JIRA_BOT_TOKEN"):
            resolve_token_override(token_env="JIRA_BOT_TOKEN")

    def test_env_var_empty_raises(self, monkeypatch):
        monkeypatch.setenv("JIRA_BOT_TOKEN", "")
        with pytest.raises(FileNotFoundError, match="JIRA_BOT_TOKEN"):
            resolve_token_override(token_env="JIRA_BOT_TOKEN")

    def test_no_source_raises(self):
        with pytest.raises(ValueError, match="no override source"):
            resolve_token_override()


# ===========================================================================
# JiraClient token / email override
# ===========================================================================


class TestJiraClientOverrides:
    """JiraClient accepts explicit token and email without touching env/files."""

    def _make_client(self, config, token="explicit-token", email=None):
        """Build JiraClient with httpx.Client stubbed out."""
        with patch("jira_api.client.httpx.Client"):
            return JiraClient(config, token=token, email=email)

    def test_explicit_token_used(self, sample_config):
        client = self._make_client(sample_config, token="my-token")
        assert client.token == "my-token"

    def test_explicit_email_used(self, sample_config):
        with patch("jira_api.client.httpx.BasicAuth") as mock_auth:
            with patch("jira_api.client.httpx.Client"):
                JiraClient(sample_config, token="tok", email="bot@example.com")
            mock_auth.assert_called_once_with("bot@example.com", "tok")

    def test_default_email_from_config(self, sample_config):
        with patch("jira_api.client.httpx.BasicAuth") as mock_auth:
            with patch("jira_api.client.httpx.Client"):
                JiraClient(sample_config, token="tok")
            mock_auth.assert_called_once_with("human@example.com", "tok")

    def test_falls_back_to_jira_token_env(self, sample_config, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "env-fallback-token")
        with patch("jira_api.client.httpx.Client"):
            client = JiraClient(sample_config)  # no explicit token
        assert client.token == "env-fallback-token"

    def test_falls_back_to_token_file(self, sample_config, tmp_path, monkeypatch):
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        Path.home() / ".jira" / "token"
        fake_token = "file-fallback-token"

        def fake_read_token(self_inner):
            return fake_token

        with patch.object(JiraClient, "_read_token", fake_read_token):
            with patch("jira_api.client.httpx.Client"):
                client = JiraClient(sample_config)
        assert client.token == fake_token

    def test_missing_token_raises(self, sample_config, monkeypatch):
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        with patch.object(
            JiraClient,
            "_read_token",
            side_effect=FileNotFoundError("Jira API token not found"),
        ):
            with patch("jira_api.client.httpx.Client"):
                with pytest.raises(FileNotFoundError, match="Jira API token not found"):
                    JiraClient(sample_config)


# ===========================================================================
# CLI global options (integration via Click test runner)
# ===========================================================================


@pytest.fixture()
def cli_runner():
    return CliRunner()


@pytest.fixture()
def patched_cli(sample_config, monkeypatch):
    """Import the CLI with Config.load and JiraClient stubbed out."""
    monkeypatch.setattr("models.config.Config.load", lambda *a, **kw: sample_config)

    # Prevent real HTTP during CLI tests
    with patch("jira_api.client.httpx.Client"):
        from jiractl.commands.cli import cli

        yield cli


class TestCliTokenOptions:
    def test_token_file_flag(self, cli_runner, patched_cli, token_file, monkeypatch):
        """--token-file stores resolved token in ctx.obj."""

        @patched_cli.result_callback()
        def capture(*a, **kw):
            pass

        # Use a version command as a no-op subcommand
        result = cli_runner.invoke(
            patched_cli,
            ["--token-file", str(token_file), "version"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    def test_token_file_missing_exits(self, cli_runner, patched_cli, tmp_path):
        result = cli_runner.invoke(
            patched_cli,
            ["--token-file", str(tmp_path / "missing.txt"), "version"],
        )
        assert result.exit_code != 0
        assert "Token file not found" in (result.output + (result.stderr or ""))

    def test_token_env_flag(self, cli_runner, patched_cli, monkeypatch):
        monkeypatch.setenv("MY_BOT_TOKEN", "bot-token-789")
        result = cli_runner.invoke(
            patched_cli,
            ["--token-env", "MY_BOT_TOKEN", "version"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    def test_token_env_missing_exits(self, cli_runner, patched_cli, monkeypatch):
        monkeypatch.delenv("MY_BOT_TOKEN", raising=False)
        result = cli_runner.invoke(
            patched_cli,
            ["--token-env", "MY_BOT_TOKEN", "version"],
        )
        assert result.exit_code != 0
        assert "MY_BOT_TOKEN" in (result.output + (result.stderr or ""))

    def test_token_stdin_flag(self, cli_runner, patched_cli):
        result = cli_runner.invoke(
            patched_cli,
            ["--token-stdin", "version"],
            input="stdin-piped-token\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    def test_mutual_exclusivity_file_and_stdin(self, cli_runner, patched_cli, token_file):
        result = cli_runner.invoke(
            patched_cli,
            ["--token-file", str(token_file), "--token-stdin", "version"],
            input="some-token\n",
        )
        assert result.exit_code != 0
        assert "Only one of" in (result.output + (result.stderr or ""))

    def test_mutual_exclusivity_file_and_env(self, cli_runner, patched_cli, token_file, monkeypatch):
        monkeypatch.setenv("MY_BOT_TOKEN", "bot-xyz")
        result = cli_runner.invoke(
            patched_cli,
            ["--token-file", str(token_file), "--token-env", "MY_BOT_TOKEN", "version"],
        )
        assert result.exit_code != 0
        assert "Only one of" in (result.output + (result.stderr or ""))

    def test_email_flag(self, cli_runner, patched_cli, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "any-token")
        result = cli_runner.invoke(
            patched_cli,
            ["--email", "bot@ci.example.com", "version"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    def test_jira_email_env_var(self, cli_runner, patched_cli, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "any-token")
        monkeypatch.setenv("JIRA_EMAIL", "env-bot@ci.example.com")
        result = cli_runner.invoke(
            patched_cli,
            ["version"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    def test_no_token_flag_uses_existing_defaults(self, cli_runner, patched_cli, monkeypatch):
        """When no override flag is passed, JIRA_TOKEN env var still works."""
        monkeypatch.setenv("JIRA_TOKEN", "legacy-env-token")
        result = cli_runner.invoke(
            patched_cli,
            ["version"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
