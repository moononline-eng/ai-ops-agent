"""Append-only audit trail: every model call, tool call and external action.

When an autonomous system does something surprising, the audit log is how you
find out why. Keep it boring: one JSON object per line, never rewritten.
"""

import json
from datetime import UTC, datetime
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path, run_id: str):
        self.path = path
        self.run_id = run_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: str, **data) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "event": event,
            **data,
        }
        with self.path.open("a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
