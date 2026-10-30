"""Read JSONL logs and group problems into "error groups".

A fingerprint is a stable ID for "the same problem": exception type + the
deepest stack frame inside our own code. 500 occurrences of one bug become
one group, which keeps the LLM prompt small and lets us dedupe GitHub issues.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from agent.redact import redact_obj

MAX_SAMPLES = 3


@dataclass
class ErrorGroup:
    fingerprint: str
    kind: str  # "exception" | "slow_request"
    title: str
    count: int = 0
    samples: list[dict] = field(default_factory=list)

    def add(self, entry: dict) -> None:
        self.count += 1
        if len(self.samples) < MAX_SAMPLES:
            self.samples.append(redact_obj(entry))


def _app_frame(frames: list[dict], app_prefix: str) -> dict | None:
    own = [f for f in frames if f.get("file", "").startswith(app_prefix)]
    return own[-1] if own else (frames[-1] if frames else None)


def fingerprint_for(entry: dict, app_prefix: str = "demo_app") -> tuple[str, str, str] | None:
    """Return (fingerprint, kind, title) or None if the entry isn't a problem."""
    exc = entry.get("exception")
    if exc:
        frame = _app_frame(exc.get("frames", []), app_prefix) or {}
        key = f"{exc.get('type')}|{frame.get('file')}|{frame.get('func')}"
        title = f"{exc.get('type')} in {frame.get('func')} ({frame.get('file')}:{frame.get('line')})"
        return _hash(key), "exception", title
    if entry.get("level") == "WARNING" and entry.get("msg") == "slow request":
        key = f"slow|{entry.get('method')}|{entry.get('path')}"
        return _hash(key), "slow_request", f"Slow requests on {entry.get('method')} {entry.get('path')}"
    return None


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def collect(log_file: Path, start_offset: int = 0) -> tuple[list[ErrorGroup], int]:
    """Parse log lines from start_offset. Returns groups (most frequent first) and new offset."""
    groups: dict[str, ErrorGroup] = {}
    if not log_file.exists():
        return [], start_offset
    with log_file.open("rb") as f:
        f.seek(start_offset)
        for raw in f:
            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue  # never crash on a malformed line
            result = fingerprint_for(entry)
            if result is None:
                continue
            fp, kind, title = result
            groups.setdefault(fp, ErrorGroup(fp, kind, title)).add(entry)
        offset = f.tell()
    return sorted(groups.values(), key=lambda g: g.count, reverse=True), offset
