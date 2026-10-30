import json

from agent.analyzer import Finding
from agent.policy import check_patch, decide
from tests.conftest import finding_json


def make(**overrides) -> Finding:
    return Finding.model_validate(json.loads(finding_json(**overrides)))


def evil_patch(path: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n"


def test_report_mode_never_escalates(settings):
    assert decide(make(), settings).action == "report"


def test_good_patch_allows_pr(settings):
    settings.mode = "pr"
    d = decide(make(), settings)
    assert d.action == "pr", d.reasons


def test_low_confidence_downgrades_to_issue(settings):
    settings.mode = "pr"
    d = decide(make(confidence=0.4), settings)
    assert d.action == "issue" and "confidence" in d.reasons[0]


def test_empty_patch_downgrades_to_issue(settings):
    settings.mode = "pr"
    assert decide(make(patch=""), settings).action == "issue"


def test_protected_and_outside_paths_rejected(settings):
    for path in [".github/workflows/ci.yml", "agent/policy.py", "pyproject.toml", "Dockerfile.agent", "scripts/x.py"]:
        assert check_patch(evil_patch(path), settings), path
    assert check_patch(evil_patch("../etc/passwd"), settings)


def test_large_patch_rejected(settings):
    body = "".join(f"+line {i}\n" for i in range(settings.max_diff_lines + 1))
    patch = "diff --git a/demo_app/x.py b/demo_app/x.py\n--- a/demo_app/x.py\n+++ b/demo_app/x.py\n@@ -0,0 +1 @@\n" + body
    assert any("limit" in p for p in check_patch(patch, settings))


def test_file_mode_changes_rejected(settings):
    patch = evil_patch("demo_app/main.py").replace("--- a/", "old mode 100644\nnew mode 100755\n--- a/")
    assert any("mode" in p for p in check_patch(patch, settings))
