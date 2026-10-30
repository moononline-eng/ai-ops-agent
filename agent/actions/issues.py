"""Turn a finding into a GitHub issue (or a comment on the existing one)."""

from agent.actions.github import fingerprint_marker
from agent.analyzer import Finding


def issue_body(f: Finding) -> str:
    parts = [
        (
            f"**Severity:** {f.severity} · **Category:** {f.category} · **Seen:** {f.occurrences}x · "
            f"**Agent confidence:** {f.confidence:.0%}"
        ),
        "",
        "### Root cause",
        f.root_cause,
        "",
    ]
    if f.evidence:
        parts += ["### Evidence", *[f"- {e}" for e in f.evidence], ""]
    if f.affected_files:
        parts += ["### Affected files", *[f"- `{p}`" for p in f.affected_files], ""]
    parts += ["### Suggested fix", f.suggested_fix, ""]
    if f.patch.strip():
        parts += [
            "<details><summary>Proposed patch</summary>",
            "",
            "```diff",
            f.patch.rstrip(),
            "```",
            "</details>",
            "",
        ]
    if f.improvements:
        parts += ["### Further improvements", *[f"- [ ] {i}" for i in f.improvements], ""]
    parts += [
        "---",
        (
            "_Opened automatically by ai-ops-agent from production logs. "
            "Log samples were redacted before analysis. Verify before acting._"
        ),
        fingerprint_marker(f.fingerprint),
    ]
    return "\n".join(parts)


def open_or_update_issue(gh, f: Finding) -> dict:
    """Dedupe by fingerprint: one open issue per distinct problem."""
    existing = gh.find_open_issue(f.fingerprint)
    if existing:
        gh.comment(existing["number"], f"Seen again: {f.occurrences} more occurrence(s) since the last run.")
        return existing
    return gh.create_issue(f"[ops-agent] {f.title}", issue_body(f))
