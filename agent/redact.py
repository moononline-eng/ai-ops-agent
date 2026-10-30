"""Remove secrets and personal data from log text before it leaves the machine.

Runs on every log line *before* the LLM sees it. Patterns are deliberately
greedy: a false positive costs a little context, a false negative leaks a key.
"""

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("API_KEY", re.compile(r"\bsk-[A-Za-z0-9_\-]{10,}")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{10,}")),
    ("AWS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    ("AUTH_HEADER", re.compile(r"(?i)(authorization|cookie|set-cookie)\s*[:=]\s*[^\s,;\"']+(?:\s+[^\s,;\"']+)?")),
    ("SECRET_KV", re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*[^\s,;\"']+")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("CARD", re.compile(r"\b(?:\d[ \-]?){13,16}\b")),
]


def redact(text: str) -> str:
    for label, pattern in _PATTERNS:
        if label in ("AUTH_HEADER", "SECRET_KV"):
            text = pattern.sub(lambda m, label=label: f"{m.group(1)}=[REDACTED_{label}]", text)
        else:
            text = pattern.sub(f"[REDACTED_{label}]", text)
    return text


_SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|cookie|password|passwd|secret|token|api[_-]?key|session|credential|private[_-]?key)"
)


def redact_obj(obj):
    """Recursively redact every string inside a JSON-like structure.

    Values under sensitive key names are dropped entirely: in {"Authorization": "Bearer x"}
    the value alone matches no pattern, so the key name is the only signal.
    """
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {
            k: "[REDACTED_KEY_VALUE]" if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact_obj(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj
