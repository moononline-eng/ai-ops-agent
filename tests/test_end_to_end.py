"""Full pipeline with a fake model and dry-run GitHub: logs in, report + actions out."""

import json
import shutil
import stat

from agent.actions.pull_requests import validate_patch
from agent.main import run
from tests.conftest import FakeClient, finding_json, log_line, response, text_block


def write_logs(settings):
    entry = {
        "level": "ERROR",
        "msg": "unhandled error",
        "exception": {
            "type": "ZeroDivisionError",
            "message": "division by zero",
            "frames": [{"file": "demo_app/main.py", "line": 2, "func": "stats"}],
        },
    }
    settings.log_file.write_text(log_line(**entry) * 4)


def audit_events(settings):
    return [json.loads(line)["event"] for line in settings.audit_file.read_text().splitlines()]


def test_report_mode(settings):
    write_logs(settings)
    run(settings, client=FakeClient([response([text_block(finding_json())])]))

    report = next(settings.reports_dir.glob("*/report.md")).read_text()
    assert "ZeroDivisionError in stats" in report and "4x" in report
    assert next(settings.reports_dir.glob("*/*.patch")).read_text().startswith("diff --git")
    assert "github_dry_run" not in audit_events(settings)


def test_checkpoint_prevents_reprocessing(settings):
    write_logs(settings)
    run(settings, client=FakeClient([response([text_block(finding_json())])]))
    # Second run has no new lines, so the model must not be called (FakeClient would raise).
    run(settings, client=FakeClient([]))


def test_pr_mode_dry_run_validates_patch_and_logs_intent(settings, repo):
    settings.mode = "pr"
    (repo / "tests").mkdir()
    (repo / "tests" / "test_stats.py").write_text(
        "from demo_app.main import stats\n\ndef test_empty():\n    assert stats([]) == 0\n"
    )
    (repo / "demo_app" / "__init__.py").write_text("")
    write_logs(settings)
    run(settings, client=FakeClient([response([text_block(finding_json())])]))

    events = audit_events(settings)
    assert events.count("github_dry_run") == 2  # issue + PR, nothing actually sent
    # The real repo was not modified, only the sandbox copy.
    assert "if orders else 0" not in (repo / "demo_app" / "main.py").read_text()


def test_patch_validation_works_on_read_only_source(repo):
    """Containers mount the source read-only; the sandbox copy must still be patchable."""
    (repo / "demo_app" / "__init__.py").write_text("")
    patch = json.loads(finding_json())["patch"]
    for path in [repo, *repo.rglob("*")]:
        path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        result = validate_patch(repo, patch)
        assert "if orders else 0" in (result.workdir / "demo_app" / "main.py").read_text(), result.log
        shutil.rmtree(result.workdir)
    finally:
        for path in [repo, *repo.rglob("*")]:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
