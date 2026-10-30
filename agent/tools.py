"""Read-only tools the model may call while investigating.

Safety properties (each is tested in tests/test_tools.py):
  * Jail: every path is resolved and must stay inside repo_root.
  * Deny-list: secrets and VCS/CI internals are never readable.
  * Read-only: there is no write, delete or shell tool. Ever.
  * Size caps: outputs are truncated so a huge file can't blow the budget.
  * Output is redacted, because source files can contain secrets too.
"""

from pathlib import Path

from agent.redact import redact

MAX_FILE_LINES = 400
MAX_SEARCH_HITS = 30
MAX_LIST_ENTRIES = 200

# logs/ holds raw, unredacted production data; audit/ and reports/ are the agent's own output.
DENIED_PARTS = {".git", ".github", ".env", "node_modules", "__pycache__", ".venv", "audit", "logs", "reports"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".sqlite", ".db"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".json", ".cfg", ".ini", ".html", ".js", ".ts"}


class ToolError(Exception):
    """Raised for any refused or failed tool call; returned to the model as is_error."""


TOOL_DEFINITIONS = [
    {
        "name": "list_files",
        "description": "List files under a directory of the application repository (recursive, max 200 entries). Use '.' for the repo root.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"directory": {"type": "string", "description": "Repo-relative directory"}},
            "required": ["directory"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a source file from the application repository. Returns numbered lines (max 400).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Repo-relative file path, e.g. demo_app/main.py"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_code",
        "description": "Case-sensitive literal substring search across repository source files. Returns file:line: text matches (max 30).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Literal text to find, e.g. a function name"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


class RepoTools:
    def __init__(self, repo_root: Path):
        self.root = repo_root.resolve()

    def run(self, name: str, args: dict) -> str:
        handlers = {"list_files": self.list_files, "read_file": self.read_file, "search_code": self.search_code}
        if name not in handlers:
            raise ToolError(f"unknown tool: {name}")
        return handlers[name](**args)

    def _safe_path(self, rel: str) -> Path:
        if not isinstance(rel, str) or "\x00" in rel:
            raise ToolError("invalid path")
        target = (self.root / rel).resolve()
        if target != self.root and self.root not in target.parents:
            raise ToolError("path is outside the repository")
        self._check_allowed(target)
        return target

    def _check_allowed(self, path: Path) -> None:
        rel_parts = path.relative_to(self.root).parts
        if any(p in DENIED_PARTS or p.startswith(".env") for p in rel_parts):
            raise ToolError("access to this path is not allowed")
        if path.suffix in DENIED_SUFFIXES:
            raise ToolError("access to this file type is not allowed")

    def _allowed_files(self, base: Path):
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.is_symlink():
                continue
            try:
                self._check_allowed(p.resolve())
            except (ToolError, ValueError):
                continue
            yield p

    def list_files(self, directory: str) -> str:
        base = self._safe_path(directory)
        if not base.is_dir():
            raise ToolError("not a directory")
        entries = [str(p.relative_to(self.root)) for p in self._allowed_files(base)]
        suffix = "\n... (truncated)" if len(entries) > MAX_LIST_ENTRIES else ""
        return "\n".join(entries[:MAX_LIST_ENTRIES]) + suffix

    def read_file(self, path: str) -> str:
        target = self._safe_path(path)
        if not target.is_file():
            raise ToolError("file not found")
        if target.suffix not in TEXT_SUFFIXES:
            raise ToolError("only text source files can be read")
        lines = target.read_text(errors="replace").splitlines()
        numbered = [f"{i + 1:4d} | {line}" for i, line in enumerate(lines[:MAX_FILE_LINES])]
        if len(lines) > MAX_FILE_LINES:
            numbered.append(f"... ({len(lines) - MAX_FILE_LINES} more lines truncated)")
        return redact("\n".join(numbered))

    def search_code(self, query: str) -> str:
        if not query or len(query) > 200:
            raise ToolError("query must be 1-200 characters")
        hits = []
        for p in self._allowed_files(self.root):
            if p.suffix not in TEXT_SUFFIXES:
                continue
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if query in line:
                    hits.append(f"{p.relative_to(self.root)}:{i}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return redact("\n".join(hits) + "\n... (more hits truncated)")
        return redact("\n".join(hits) or "no matches")
