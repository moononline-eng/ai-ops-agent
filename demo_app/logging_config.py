"""Structured JSON logging.

Every log record becomes one JSON object per line (JSONL). Structured logs are
what make automated analysis possible: the agent can group errors by exception
type and stack frame instead of regex-scraping free text.
"""

import json
import logging
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("path", "method", "status", "duration_ms", "user_email", "request_id"):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            exc_type, exc, tb = record.exc_info
            frames = traceback.extract_tb(tb)
            entry["exception"] = {
                "type": exc_type.__name__,
                "message": str(exc),
                "frames": [
                    {"file": _relpath(f.filename), "line": f.lineno, "func": f.name}
                    for f in frames
                ],
            }
        return json.dumps(entry)


def _relpath(filename: str) -> str:
    """Make paths repo-relative so the agent can map them to source files."""
    marker = "demo_app" + os.sep
    idx = filename.find(marker)
    return filename[idx:] if idx >= 0 else os.path.basename(filename)


def setup_logging() -> None:
    log_file = Path(os.environ.get("LOG_FILE", "logs/app.jsonl"))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file)
    handler.setFormatter(JsonFormatter())
    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler, stream]
    root.setLevel(logging.INFO)
