"""Run-level behavior: checkpointing, credentials, and isolation of GitHub failures."""

import json

import httpx

from agent.actions.github import DryRunGitHub
from agent.config import Settings
from agent.main import load_offset, run, save_offset
from tests.conftest import FakeClient, finding_json, log_line, response, text_block


def error_line(func="stats"):
    return log_line(
        level="ERROR",
        msg="unhandled error",
        exception={"type": "ZeroDivisionError", "frames": [{"file": "demo_app/main.py", "line": 2, "func": func}]},
    )


def test_replaced_log_file_is_read_from_the_top(settings):
    settings.log_file.write_text(error_line() * 2)
    save_offset(settings, settings.log_file.stat().st_size)
    # A new, *larger* file replaces the old one (e.g. CI regenerates logs every run).
    settings.log_file.write_text(log_line(level="INFO", msg="new file") + error_line() * 5)
    assert load_offset(settings) == 0


def test_appended_log_resumes_from_checkpoint(settings):
    settings.log_file.write_text(error_line())
    size = settings.log_file.stat().st_size
    save_offset(settings, size)
    with settings.log_file.open("a") as f:
        f.write(error_line())
    assert load_offset(settings) == size


def test_api_key_is_read_from_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-from-dotenv\nAGENT_MODE=issue\n")
    s = Settings(_env_file=env)
    assert s.anthropic_api_key.get_secret_value() == "sk-from-dotenv"
    assert s.mode == "issue"
    assert "sk-from-dotenv" not in repr(s)  # SecretStr keeps it out of logs and tracebacks


class NoCredentialsClient(FakeClient):
    def _create(self, **kwargs):
        raise TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token..."')


def test_missing_credentials_abort_cleanly_without_advancing_checkpoint(settings, capsys):
    settings.log_file.write_text(error_line())
    assert run(settings, client=NoCredentialsClient([])) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not settings.state_file.exists()  # next run retries the same lines


def test_github_failure_does_not_lose_the_report(settings, monkeypatch):
    settings.mode = "issue"
    settings.log_file.write_text(error_line("stats") + error_line("other"))

    def boom(self, title, body):
        raise httpx.ConnectError("github is down")

    monkeypatch.setattr(DryRunGitHub, "create_issue", boom)
    client = FakeClient([response([text_block(finding_json())]), response([text_block(finding_json(title="Other"))])])
    assert run(settings, client=client) == 0
    report = next(settings.reports_dir.glob("*/report.md")).read_text()
    assert report.count("GitHub action failed") == 2  # both findings attempted, both recorded


def test_existing_issue_gets_comment_but_no_duplicate_pr(settings, monkeypatch):
    settings.mode = "pr"
    settings.log_file.write_text(error_line())
    monkeypatch.setattr(DryRunGitHub, "find_open_issue", lambda self, fp: {"number": 7, "html_url": "u"})
    run(settings, client=FakeClient([response([text_block(finding_json())])]))
    events = [json.loads(line) for line in settings.audit_file.read_text().splitlines()]
    kinds = [e["kind"] for e in events if e["event"] == "github_dry_run"]
    assert kinds == ["comment"]
