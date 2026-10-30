import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Keep demo-app test logs out of the real logs/ directory.
os.environ.setdefault("LOG_FILE", str(Path(tempfile.gettempdir()) / "ops-agent-test-app.jsonl"))

from agent.audit import AuditLog
from agent.config import Settings


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small fake application repo for the agent to inspect."""
    (tmp_path / "demo_app").mkdir()
    (tmp_path / "demo_app" / "main.py").write_text(
        "def stats(orders):\n    return sum(orders) / len(orders)\n"
    )
    (tmp_path / ".env").write_text("SECRET=hunter2\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    return tmp_path


@pytest.fixture
def settings(tmp_path: Path, repo: Path) -> Settings:
    return Settings(
        _env_file=None,
        repo_root=repo,
        log_file=tmp_path / "app.jsonl",
        state_file=tmp_path / "state.json",
        reports_dir=tmp_path / "reports",
        audit_file=tmp_path / "audit" / "audit.jsonl",
    )


@pytest.fixture
def audit(settings: Settings) -> AuditLog:
    return AuditLog(settings.audit_file, "test-run")


# ---- fake Anthropic client -------------------------------------------------

def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(id: str, name: str, input: dict):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def response(content, stop_reason="end_turn", input_tokens=1000, output_tokens=200):
    usage = SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage)


class FakeClient:
    """Replays scripted responses and records every request it receives."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=_dump)))
        return self.responses.pop(0)


def _dump(o):
    return vars(o) if isinstance(o, SimpleNamespace) else str(o)


def finding_json(**overrides) -> str:
    data = {
        "title": "ZeroDivisionError in stats",
        "category": "bug",
        "severity": "high",
        "root_cause": "Division by len(orders) when the list is empty.",
        "evidence": ["demo_app/main.py:2 divides by len(orders)"],
        "affected_files": ["demo_app/main.py:2"],
        "suggested_fix": "Return 0 when there are no orders.",
        "patch": (
            "diff --git a/demo_app/main.py b/demo_app/main.py\n"
            "--- a/demo_app/main.py\n"
            "+++ b/demo_app/main.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def stats(orders):\n"
            "-    return sum(orders) / len(orders)\n"
            "+    return sum(orders) / len(orders) if orders else 0\n"
        ),
        "confidence": 0.9,
        "improvements": ["Add a unit test for the empty case"],
    }
    data.update(overrides)
    return json.dumps(data)


def log_line(**entry) -> str:
    return json.dumps(entry) + "\n"
