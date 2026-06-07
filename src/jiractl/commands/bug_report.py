"""
commands/bug_report.py — Context-manager bug recorder for --report-bug.

When the root CLI is invoked with --report-bug, a BugRecorder is installed
via Click's ctx.with_resource().  It:

  1. Tees sys.stdout / sys.stderr so the user still sees live output while
     we keep a rolling buffer of the last ~200 write-calls.
  2. Captures any exception traceback from the subcommand.
  3. After the command finishes (success or failure), prompts the user for
     a short title and description.
  4. Redacts sensitive data (token, email, Authorization headers).
  5. Builds an ADF document, shows a Rich preview, and on confirmation
     POSTs a new Bug ticket to the configured project via JiraClient.
  6. Returns False from __exit__ so the original exception always propagates.
"""

from __future__ import annotations

import collections
import os
import platform
import sys
import time
import traceback as _traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Literal

import click
from rich.panel import Panel

from jiractl.commands._version import __version__
from jiractl.commands.ui import console

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_REDACT_PATTERNS: list[tuple[str, str]] = [
    # env-var assignment style
    (r"(?i)JIRA_TOKEN\s*=\s*\S+", "JIRA_TOKEN=[REDACTED]"),
    # HTTP header style
    (r"(?i)Authorization:\s*\S+(?:\s+\S+)?", "Authorization: [REDACTED]"),
    # Bare Bearer / Basic tokens
    (r"(?i)Bearer\s+\S+", "Bearer [REDACTED]"),
    (r"(?i)Basic\s+\S+", "Basic [REDACTED]"),
]


def _redact(text: str, email: str | None = None, token: str | None = None) -> str:
    """Scrub sensitive values from *text* in-place using regex patterns."""
    import re

    for pattern, replacement in _REDACT_PATTERNS:
        text = re.sub(pattern, replacement, text)
    if email:
        text = text.replace(email, "[EMAIL]")
    if token and len(token) >= 8:  # only redact plausible token strings
        text = text.replace(token, "[TOKEN]")
    return text


def _load_token() -> str:
    """Return the Jira token used by JiraClient (env-var or file)."""
    token = os.environ.get("JIRA_TOKEN", "")
    if not token:
        token_path = Path.home() / ".jira" / "token"
        if token_path.exists():
            token = token_path.read_text().strip()
    return token


# ---------------------------------------------------------------------------
# Tee stream
# ---------------------------------------------------------------------------


class _TeeStream:
    """
    Wraps a stream: forwards every write() to the original stream and also
    appends the text to *buf* (a collections.deque with a maxlen limit).
    Delegates all other attribute access to the underlying stream.
    """

    def __init__(self, original, buf: collections.deque) -> None:
        self._original = original
        self._buf = buf

    def write(self, text: str) -> int:
        self._buf.append(text)
        return self._original.write(text)

    def flush(self) -> None:
        self._original.flush()

    def fileno(self) -> int:
        return self._original.fileno()

    def __getattr__(self, name: str):  # noqa: ANN001
        return getattr(self._original, name)


# ---------------------------------------------------------------------------
# Metadata collection
# ---------------------------------------------------------------------------


def _collect_metadata(argv: str, cfg, duration: float) -> dict:
    return {
        "jiractl_version": __version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "argv": argv,
        "cwd": str(Path.cwd()),
        "base_url": cfg.base_url if cfg else "unknown",
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "duration_s": f"{duration:.2f}s",
    }


# ---------------------------------------------------------------------------
# ADF builders
# ---------------------------------------------------------------------------


def _adf_heading(level: int, text: str) -> dict:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": text}],
    }


def _adf_code_block(content: str, language: str = "text") -> dict:
    return {
        "type": "codeBlock",
        "attrs": {"language": language},
        "content": [{"type": "text", "text": content or "(empty)"}],
    }


def _adf_paragraph(text: str) -> dict:
    return {
        "type": "paragraph",
        "content": [{"type": "text", "text": text}],
    }


def _build_adf(
    user_description: str,
    metadata: dict,
    stdout_text: str,
    stderr_text: str,
    traceback_text: str | None,
) -> dict:
    """
    Build an ADF document for the bug ticket description.
    Sections: Reporter's Description / Invocation / Environment /
              stdout tail / stderr tail / Traceback.
    """
    # Jira has a per-field character limit; truncate large blobs.
    _LIMIT = 8_000

    nodes: list[dict] = []

    # Reporter's description
    nodes.append(_adf_heading(2, "Reporter's Description"))
    if user_description.strip():
        for line in user_description.splitlines():
            nodes.append(_adf_paragraph(line) if line.strip() else _adf_paragraph(" "))
    else:
        nodes.append(_adf_paragraph("(no description provided)"))

    # Invocation
    nodes.append(_adf_heading(2, "Invocation"))
    nodes.append(_adf_code_block(metadata.get("argv", "")))

    # Environment
    nodes.append(_adf_heading(2, "Environment"))
    env_lines = "\n".join(f"{k}: {v}" for k, v in metadata.items() if k != "argv")
    nodes.append(_adf_code_block(env_lines))

    # stdout tail
    if stdout_text.strip():
        nodes.append(_adf_heading(2, "stdout (last captured lines)"))
        nodes.append(_adf_code_block(stdout_text[-_LIMIT:]))

    # stderr tail
    if stderr_text.strip():
        nodes.append(_adf_heading(2, "stderr (last captured lines)"))
        nodes.append(_adf_code_block(stderr_text[-_LIMIT:]))

    # Traceback
    if traceback_text:
        nodes.append(_adf_heading(2, "Traceback"))
        nodes.append(_adf_code_block(traceback_text[-_LIMIT:]))

    return {"type": "doc", "version": 1, "content": nodes}


# ---------------------------------------------------------------------------
# Reporter orchestration
# ---------------------------------------------------------------------------


def _run_reporter(
    cfg,
    argv: list[str],
    stdout_lines: list[str],
    stderr_lines: list[str],
    traceback_text: str | None,
    duration: float,
    token: str | None = None,
    email: str | None = None,
) -> None:
    """
    Prompt the user, build the ADF report, preview it, and optionally post
    a bug ticket to Jira.  All errors during reporting are displayed but
    never mask the original command exception.
    """
    if cfg is None or not cfg.bug_report.enabled:
        return

    # Lazy import to avoid circular dependencies at module load time
    from jira_api.client import JiraClient
    from jira_api.issues import create_bug

    had_error = traceback_text is not None
    rule_color = "red" if had_error else "cyan"
    status_label = "Failed" if had_error else "Completed"

    console.print()
    console.rule(f"[bold {rule_color}]Bug Reporter — Command {status_label}[/]")

    # Gather secrets for redaction
    # Prefer the override values (from CLI flags); fall back to config / env.
    email = email or cfg.email
    token = token or _load_token()

    raw_argv = " ".join(argv)
    safe_argv = _redact(raw_argv, email=email, token=token)
    safe_stdout = _redact("".join(stdout_lines), email=email, token=token)
    safe_stderr = _redact("".join(stderr_lines), email=email, token=token)
    safe_traceback = _redact(traceback_text, email=email, token=token) if traceback_text else None

    metadata = _collect_metadata(safe_argv, cfg, duration)

    # Derive a default summary from the last line of the traceback
    default_summary = "Bug report from jiractl"
    if safe_traceback:
        lines = [ln for ln in safe_traceback.strip().splitlines() if ln.strip()]
        if lines:
            default_summary = lines[-1][:120]

    # Prompt for title + description
    try:
        user_summary = click.prompt(
            "\nShort bug summary (ticket title)",
            default=default_summary,
        )
        user_description = click.prompt(
            "Brief description (what you saw / expected vs actual)",
            default="",
        )
    except (click.exceptions.Abort, EOFError, KeyboardInterrupt):
        console.print("[dim]Bug report cancelled.[/]")
        return

    adf_doc = _build_adf(
        user_description=user_description,
        metadata=metadata,
        stdout_text=safe_stdout,
        stderr_text=safe_stderr,
        traceback_text=safe_traceback,
    )

    # Rich preview panel
    section_labels = ["Invocation", "Environment"]
    if safe_stdout.strip():
        section_labels.append("stdout")
    if safe_stderr.strip():
        section_labels.append("stderr")
    if safe_traceback:
        section_labels.append("Traceback")

    preview_lines = [
        f"[bold]Title:[/]       {user_summary}",
        f"[bold]Project:[/]     {cfg.bug_report.project}",
        f"[bold]Type:[/]        {cfg.bug_report.issue_type}",
        f"[bold]Description:[/] {user_description or '(none)'}",
        "",
        f"[dim]Report sections: {' · '.join(section_labels)}[/]",
    ]
    console.print(
        Panel(
            "\n".join(preview_lines),
            title="[bold]Bug Ticket Preview[/]",
            border_style="yellow",
        )
    )

    # Confirm before posting
    try:
        if not click.confirm("File this bug ticket?", default=False):
            console.print("[dim]Bug report not filed.[/]")
            return
    except (click.exceptions.Abort, EOFError, KeyboardInterrupt):
        console.print("[dim]Bug report cancelled.[/]")
        return

    # Post to Jira
    try:
        with JiraClient(cfg, token=token or None, email=email or None) as client:
            key = create_bug(
                client=client,
                project_key=cfg.bug_report.project,
                summary=user_summary,
                adf_description=adf_doc,
                issue_type=cfg.bug_report.issue_type,
            )
        browse_url = f"{cfg.base_url.rstrip('/')}/browse/{key}"
        console.print(f"[green]✓ Bug filed:[/] {browse_url}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to file bug ticket:[/] {exc}")


# ---------------------------------------------------------------------------
# BugRecorder context manager
# ---------------------------------------------------------------------------


class BugRecorder:
    """
    Context manager installed by the --report-bug flag via ctx.with_resource().

    On entry:  replaces sys.stdout / sys.stderr with _TeeStream wrappers that
               forward writes to the originals while buffering up to 200 chunks.
    On exit:   restores streams, collects exception info (if any), and runs
               the interactive reporter.  Always returns False so the original
               exception propagates normally through Click's error handling.
    """

    def __init__(
        self,
        cfg,
        argv: list[str],
        token: str | None = None,
        email: str | None = None,
    ) -> None:
        self._cfg = cfg
        self._argv = argv
        self._token = token
        self._email = email
        self._stdout_buf: collections.deque = collections.deque(maxlen=200)
        self._stderr_buf: collections.deque = collections.deque(maxlen=200)
        self._orig_stdout: IO[str] | None = None
        self._orig_stderr: IO[str] | None = None
        self._start_time: float = 0.0

    def __enter__(self) -> BugRecorder:
        self._start_time = time.monotonic()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _TeeStream(self._orig_stdout, self._stdout_buf)
        sys.stderr = _TeeStream(self._orig_stderr, self._stderr_buf)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> Literal[False]:  # noqa: ANN001
        # Restore streams immediately so prompts display correctly.
        assert self._orig_stdout is not None
        assert self._orig_stderr is not None
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr

        duration = time.monotonic() - self._start_time

        traceback_text: str | None = None
        if exc_val is not None:
            traceback_text = "".join(_traceback.format_exception(exc_type, exc_val, exc_tb))

        _run_reporter(
            cfg=self._cfg,
            argv=self._argv,
            stdout_lines=list(self._stdout_buf),
            stderr_lines=list(self._stderr_buf),
            traceback_text=traceback_text,
            duration=duration,
            token=self._token,
            email=self._email,
        )

        return False  # Never suppress the original exception


# ---------------------------------------------------------------------------
# Decorator injection helpers (used by BugReportGroup)
# ---------------------------------------------------------------------------

# Sentinel key stored on the root ctx.obj to prevent double-firing when both
# the root group and a subcommand have --report-bug set simultaneously.
_RECORDER_ACTIVE_KEY = "_bug_recorder_active"

_REPORT_BUG_HELP = (
    "Capture this invocation (argv, output, traceback) and file a bug "
    "ticket to the configured DEV project at the end of the command."
)


def _report_bug_callback(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    """
    Option callback installed on every subcommand by BugReportGroup.
    Installs a BugRecorder when --report-bug is set, using a sentinel on the
    root context object to prevent double-firing.
    """
    if not value:
        return
    root = ctx.find_root()
    root_obj: dict = root.obj if isinstance(root.obj, dict) else {}
    if root_obj.get(_RECORDER_ACTIVE_KEY):
        return
    root_obj[_RECORDER_ACTIVE_KEY] = True
    cfg = root_obj.get("config")
    ctx.with_resource(
        BugRecorder(
            cfg,
            sys.argv[1:],
            token=root_obj.get("token"),
            email=root_obj.get("email"),
        )
    )


def _inject_report_bug(cmd: click.BaseCommand) -> None:
    """
    Add --report-bug to *cmd* and, recursively, to every subcommand of *cmd*.
    Safe to call multiple times — skips commands that already have the option.
    """
    existing = {p.name for p in getattr(cmd, "params", [])}
    if "report_bug" not in existing:
        opt = click.Option(
            ["--report-bug"],
            is_flag=True,
            default=False,
            is_eager=True,
            expose_value=False,
            callback=_report_bug_callback,
            help=_REPORT_BUG_HELP,
        )
        cmd.params.append(opt)
    if isinstance(cmd, click.Group):
        for sub in cmd.commands.values():
            _inject_report_bug(sub)


class BugReportGroup(click.Group):
    """
    A Click Group that automatically injects --report-bug into every command
    (and their subcommands, recursively) when registered via add_command().

    Usage in cli.py:
        @click.group(cls=BugReportGroup)
        ...
        def cli(ctx, report_bug):
            ...
    """

    def add_command(self, cmd: click.BaseCommand, name: str | None = None) -> None:
        _inject_report_bug(cmd)
        super().add_command(cmd, name)
