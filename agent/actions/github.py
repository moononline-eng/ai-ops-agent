"""Minimal GitHub REST client, plus a dry-run twin with the same interface.

Uses only the REST API (no git push), so the token never touches git config or
a remote URL. Every write goes through `_write`, which enforces the per-run
write budget and records an audit event.
"""

import base64

import httpx

from agent.audit import AuditLog

LABEL = "ai-ops-agent"
AI_LABEL = "ai-generated"


class WriteBudgetExceeded(Exception):
    pass


class GitHub:
    def __init__(self, repo: str, token: str, audit: AuditLog, max_writes: int):
        if not repo or not token:
            raise ValueError("AGENT_GITHUB_REPO and AGENT_GITHUB_TOKEN are required for GitHub actions")
        self.repo = repo
        self.audit = audit
        self.writes_left = max_writes
        self.http = httpx.Client(
            base_url=f"https://api.github.com/repos/{repo}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )

    # ---- reads -------------------------------------------------------------
    def find_open_issue(self, fingerprint: str) -> dict | None:
        r = self.http.get("/issues", params={"labels": LABEL, "state": "open", "per_page": 100})
        r.raise_for_status()
        marker = fingerprint_marker(fingerprint)
        return next((i for i in r.json() if marker in (i.get("body") or "")), None)

    def branch_sha(self, branch: str) -> str:
        r = self.http.get(f"/git/ref/heads/{branch}")
        r.raise_for_status()
        return r.json()["object"]["sha"]

    def file_sha(self, path: str, ref: str) -> str | None:
        r = self.http.get(f"/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()["sha"]

    # ---- writes ------------------------------------------------------------
    def _write(self, kind: str, method: str, url: str, json: dict, counts: bool = True) -> dict:
        if counts:
            if self.writes_left <= 0:
                raise WriteBudgetExceeded("GitHub write budget for this run is used up")
            self.writes_left -= 1
        self.audit.record("github_write", kind=kind, method=method, url=url)
        r = self.http.request(method, url, json=json)
        r.raise_for_status()
        return r.json()

    def create_issue(self, title: str, body: str) -> dict:
        return self._write("create_issue", "POST", "/issues", {"title": title, "body": body, "labels": [LABEL]})

    def comment(self, number: int, body: str) -> dict:
        return self._write("comment", "POST", f"/issues/{number}/comments", {"body": body})

    def create_branch(self, branch: str, sha: str) -> dict:
        return self._write("create_branch", "POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha}, counts=False)

    def put_file(self, path: str, content: bytes, branch: str, message: str, sha: str | None) -> dict:
        payload = {"message": message, "content": base64.b64encode(content).decode(), "branch": branch}
        if sha:
            payload["sha"] = sha
        return self._write("put_file", "PUT", f"/contents/{path}", payload, counts=False)

    def create_draft_pr(self, title: str, body: str, head: str, base: str) -> dict:
        pr = self._write(
            "create_pr", "POST", "/pulls", {"title": title, "body": body, "head": head, "base": base, "draft": True}
        )
        self._write("label_pr", "POST", f"/issues/{pr['number']}/labels", {"labels": [LABEL, AI_LABEL]}, counts=False)
        return pr


class DryRunGitHub:
    """Same interface, no network. Logs what *would* happen."""

    def __init__(self, audit: AuditLog, max_writes: int):
        self.audit = audit
        self.writes_left = max_writes
        self._n = 0

    def _fake(self, kind: str, **data) -> dict:
        if self.writes_left <= 0:
            raise WriteBudgetExceeded("GitHub write budget for this run is used up")
        self.writes_left -= 1
        self._n += 1
        self.audit.record("github_dry_run", kind=kind, **data)
        return {"number": self._n, "html_url": f"(dry-run {kind} #{self._n})"}

    def find_open_issue(self, fingerprint: str) -> dict | None:
        return None

    def create_issue(self, title: str, body: str) -> dict:
        return self._fake("create_issue", title=title)

    def comment(self, number: int, body: str) -> dict:
        return self._fake("comment", number=number)

    def propose_pr(self, title: str, files: list[str]) -> dict:
        return self._fake("create_pr", title=title, files=files)


def fingerprint_marker(fingerprint: str) -> str:
    return f"<!-- ai-ops-agent fingerprint:{fingerprint} -->"
