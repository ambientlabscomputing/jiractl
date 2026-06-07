"""
tests/test_bug_report.py — Unit tests for the --report-bug feature.

Covers:
  - _TeeStream: forwards writes to original and buffers them.
  - _redact: scrubs token, email, Authorization, Bearer, Basic patterns.
  - _build_adf: produces a valid ADF document with the expected sections.
  - BugRecorder: re-raises the original exception after __exit__.
"""

from __future__ import annotations

import collections
import io
from typing import Any

import pytest

from jiractl.commands.bug_report import (
    BugRecorder,
    _build_adf,
    _redact,
    _TeeStream,
)
from jiractl.models.config import BugReportConfig, Config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg() -> Config:
    return Config(
        base_url="https://test.atlassian.net",
        email="dev@example.com",
        allowed_projects=["TEST"],
        bug_report=BugReportConfig(project="DEV", issue_type="Bug", enabled=True),
    )


# ---------------------------------------------------------------------------
# _TeeStream tests
# ---------------------------------------------------------------------------


class TestTeeStream:
    def test_forwards_writes_to_original(self) -> None:
        buf: collections.deque = collections.deque(maxlen=200)
        sink = io.StringIO()
        tee = _TeeStream(sink, buf)

        tee.write("hello ")
        tee.write("world\n")

        assert sink.getvalue() == "hello world\n"

    def test_buffers_written_chunks(self) -> None:
        buf: collections.deque = collections.deque(maxlen=200)
        sink = io.StringIO()
        tee = _TeeStream(sink, buf)

        tee.write("first\n")
        tee.write("second\n")

        assert list(buf) == ["first\n", "second\n"]

    def test_returns_char_count(self) -> None:
        buf: collections.deque = collections.deque(maxlen=200)
        sink = io.StringIO()
        tee = _TeeStream(sink, buf)

        result = tee.write("abc")
        assert result == 3

    def test_respects_maxlen(self) -> None:
        buf: collections.deque = collections.deque(maxlen=3)
        sink = io.StringIO()
        tee = _TeeStream(sink, buf)

        for i in range(5):
            tee.write(f"line{i}\n")

        assert len(buf) == 3
        assert list(buf) == ["line2\n", "line3\n", "line4\n"]

    def test_delegates_unknown_attrs_to_original(self) -> None:
        buf: collections.deque = collections.deque(maxlen=10)
        sink = io.StringIO()
        tee = _TeeStream(sink, buf)

        # StringIO has a `getvalue` method; it should be accessible via __getattr__
        assert tee.getvalue() == ""

    def test_flush_delegates(self) -> None:
        buf: collections.deque = collections.deque(maxlen=10)
        sink = io.StringIO()
        tee = _TeeStream(sink, buf)
        # flush should not raise
        tee.flush()


# ---------------------------------------------------------------------------
# _redact tests
# ---------------------------------------------------------------------------


class TestRedact:
    def test_scrubs_jira_token_env_pattern(self) -> None:
        text = "export JIRA_TOKEN=supersecret123"
        result = _redact(text)
        assert "supersecret123" not in result
        assert "[REDACTED]" in result

    def test_scrubs_authorization_header(self) -> None:
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload"
        result = _redact(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "[REDACTED]" in result

    def test_scrubs_bearer_token(self) -> None:
        text = "Sending request with Bearer abc123tokenvalue"
        result = _redact(text)
        assert "abc123tokenvalue" not in result

    def test_scrubs_basic_token(self) -> None:
        text = "Basic dXNlcjpwYXNzd29yZA=="
        result = _redact(text)
        assert "dXNlcjpwYXNzd29yZA==" not in result

    def test_scrubs_email(self) -> None:
        result = _redact("logged in as dev@example.com", email="dev@example.com")
        assert "dev@example.com" not in result
        assert "[EMAIL]" in result

    def test_scrubs_token_value(self) -> None:
        result = _redact("using token secrettoken99", token="secrettoken99")
        assert "secrettoken99" not in result
        assert "[TOKEN]" in result

    def test_ignores_short_tokens(self) -> None:
        # Tokens shorter than 8 chars are not redacted (too likely to be coincidental)
        result = _redact("value is abc", token="abc")
        assert "abc" in result

    def test_case_insensitive_patterns(self) -> None:
        text = "AUTHORIZATION: BEARER MyToken123456789"
        result = _redact(text)
        assert "MyToken123456789" not in result

    def test_leaves_unrelated_text_intact(self) -> None:
        text = "jiractl list --project TEST --format table"
        result = _redact(text, email="other@example.com", token="unrelated_token_xyz")
        assert result == text


# ---------------------------------------------------------------------------
# _build_adf tests
# ---------------------------------------------------------------------------


class TestBuildAdf:
    def _make_adf(self, **kwargs) -> dict:
        defaults: dict[str, Any] = dict(
            user_description="Something broke",
            metadata={
                "jiractl_version": "0.7.1",
                "python_version": "3.12.0",
                "platform": "macOS",
                "argv": "jiractl --report-bug list --project TEST",
                "cwd": "/home/user/project",
                "base_url": "https://test.atlassian.net",
                "timestamp_utc": "2026-05-22T10:00:00+00:00",
                "duration_s": "1.23s",
            },
            stdout_text="",
            stderr_text="",
            traceback_text=None,
        )
        defaults.update(kwargs)
        return _build_adf(**defaults)

    def test_returns_adf_doc_root(self) -> None:
        adf = self._make_adf()
        assert adf["type"] == "doc"
        assert adf["version"] == 1
        assert isinstance(adf["content"], list)

    def test_contains_invocation_section(self) -> None:
        adf = self._make_adf()
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert "Invocation" in headings

    def test_contains_environment_section(self) -> None:
        adf = self._make_adf()
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert "Environment" in headings

    def test_contains_reporters_description_section(self) -> None:
        adf = self._make_adf()
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert "Reporter's Description" in headings

    def test_traceback_section_present_when_provided(self) -> None:
        adf = self._make_adf(traceback_text="Traceback (most recent call last):\n  ...\nValueError: oops")
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert "Traceback" in headings

    def test_traceback_section_absent_when_none(self) -> None:
        adf = self._make_adf(traceback_text=None)
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert "Traceback" not in headings

    def test_stdout_section_present_when_non_empty(self) -> None:
        adf = self._make_adf(stdout_text="some output line\n")
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert any("stdout" in h for h in headings)

    def test_stdout_section_absent_when_empty(self) -> None:
        adf = self._make_adf(stdout_text="")
        headings = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "heading"]
        assert not any("stdout" in h for h in headings)

    def test_code_blocks_have_correct_type(self) -> None:
        adf = self._make_adf()
        code_blocks = [n for n in adf["content"] if n["type"] == "codeBlock"]
        assert len(code_blocks) >= 2  # at least Invocation + Environment
        for block in code_blocks:
            assert "attrs" in block
            assert "language" in block["attrs"]
            assert isinstance(block["content"], list)

    def test_argv_appears_in_code_block(self) -> None:
        argv = "jiractl --report-bug describe TCRM-99"
        adf = self._make_adf(
            metadata={
                "argv": argv,
                "jiractl_version": "0.7.1",
                "python_version": "3.12",
                "platform": "macOS",
                "cwd": "/tmp",
                "base_url": "https://test.atlassian.net",
                "timestamp_utc": "2026-05-22T10:00:00+00:00",
                "duration_s": "0.50s",
            }
        )
        # The argv code block should contain the argv value
        code_texts = [node["content"][0]["text"] for node in adf["content"] if node["type"] == "codeBlock"]
        assert any(argv in t for t in code_texts)


# ---------------------------------------------------------------------------
# BugRecorder exception propagation
# ---------------------------------------------------------------------------


class TestBugRecorder:
    def test_reraises_exception(self, cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """BugRecorder must not suppress exceptions."""
        monkeypatch.setattr(
            "commands.bug_report._run_reporter",
            lambda **_kwargs: None,
        )

        with pytest.raises(ValueError, match="original error"):
            with BugRecorder(cfg, ["jiractl", "list"]):
                raise ValueError("original error")

    def test_no_exception_path(self, cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """BugRecorder exits cleanly when no exception is raised."""
        reporter_calls: list[dict] = []

        def fake_reporter(**kwargs) -> None:
            reporter_calls.append(kwargs)

        monkeypatch.setattr("commands.bug_report._run_reporter", fake_reporter)

        with BugRecorder(cfg, ["jiractl", "version"]):
            pass  # no exception

        assert len(reporter_calls) == 1
        assert reporter_calls[0]["traceback_text"] is None

    def test_restores_streams_on_exception(self, cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
        """sys.stdout and sys.stderr must be restored even when an exception occurs."""
        import sys

        monkeypatch.setattr("commands.bug_report._run_reporter", lambda **_: None)

        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        with pytest.raises(RuntimeError):
            with BugRecorder(cfg, []):
                raise RuntimeError("boom")

        assert sys.stdout is orig_stdout
        assert sys.stderr is orig_stderr
