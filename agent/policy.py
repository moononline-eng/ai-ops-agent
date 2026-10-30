"""Deterministic guardrails between the model's suggestion and any action.

The model *proposes*, policy *decides*. Nothing here asks the LLM anything, so
a prompt-injected or simply wrong model can't talk its way past these rules.
Every downgrade is recorded with a reason so humans can see why.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from agent.analyzer import Finding
from agent.config import Settings

Action = Literal["report", "issue", "pr"]
RANK = {"report": 0, "issue": 1, "pr": 2}

# Never patchable, regardless of prefix allowlist: CI, secrets, deps, infra.
DENIED_PATCH_PATTERNS = [
    re.compile(p)
    for p in (
        r"(^|/)\.github/", r"(^|/)\.env", r"(^|/)\.git/", r"Dockerfile", r"docker-compose",
        r"pyproject\.toml$", r"requirements.*\.txt$", r"\.(pem|key|p12)$", r"(^|/)agent/",
    )
]
_DIFF_PATH = re.compile(r"^(?:\+\+\+ b/|--- a/)(.+)$")
_DIFF_GIT = re.compile(r"^diff --git a/(\S+) b/(\S+)$")


@dataclass
class Decision:
    action: Action
    reasons: list[str] = field(default_factory=list)


def patch_paths(patch: str) -> set[str]:
    paths = set()
    for line in patch.splitlines():
        if m := _DIFF_GIT.match(line):
            paths.update(m.groups())
        elif (m := _DIFF_PATH.match(line)) and m.group(1) != "/dev/null":
            paths.add(m.group(1).strip())
    return paths


def check_patch(patch: str, s: Settings) -> list[str]:
    """Return reasons the patch is unacceptable (empty list = OK)."""
    problems = []
    paths = patch_paths(patch)
    if not paths:
        problems.append("patch has no recognizable file paths")
    for p in paths:
        if p.startswith("/") or ".." in p.split("/"):
            problems.append(f"unsafe path in patch: {p}")
        elif any(rx.search(p) for rx in DENIED_PATCH_PATTERNS):
            problems.append(f"patch touches a protected file: {p}")
        elif not any(p.startswith(prefix) for prefix in s.patch_allowed_prefixes):
            problems.append(f"patch touches a path outside the allowlist: {p}")
    for marker in ("GIT binary patch", "deleted file mode", "rename from", "new file mode 120000", "old mode", "new mode"):
        if marker in patch:
            problems.append(f"patch contains disallowed operation: {marker!r}")
    changed = sum(
        1 for line in patch.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )
    if changed > s.max_diff_lines:
        problems.append(f"patch changes {changed} lines (limit {s.max_diff_lines})")
    return problems


def decide(finding: Finding, s: Settings) -> Decision:
    """Pick the strongest action allowed by both the configured mode and the rules."""
    reasons: list[str] = []
    ceiling: Action = s.mode

    if RANK[ceiling] >= RANK["pr"]:
        if not finding.patch.strip():
            reasons.append("no patch proposed")
            ceiling = "issue"
        elif finding.confidence < s.min_confidence_for_pr:
            reasons.append(f"confidence {finding.confidence:.2f} below PR threshold {s.min_confidence_for_pr}")
            ceiling = "issue"
        elif problems := check_patch(finding.patch, s):
            reasons.extend(problems)
            ceiling = "issue"

    return Decision(ceiling, reasons)
