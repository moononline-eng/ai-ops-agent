"""Markdown report + ready-to-apply .patch files. Needs no permissions at all.

This is the safest output and always produced, whatever the mode: a developer
can read the report and run `git apply reports/<run>/<fingerprint>.patch`.
"""

from datetime import UTC, datetime
from pathlib import Path

from agent.analyzer import Finding
from agent.policy import Decision

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def write_report(
    findings: list[tuple[Finding, Decision]],
    reports_dir: Path,
    run_id: str,
    links: dict[str, str] | None = None,
    stats: dict | None = None,
) -> Path:
    links = links or {}
    run_dir = reports_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    ordered = sorted(findings, key=lambda fd: (SEVERITY_ORDER[fd[0].severity], -fd[0].occurrences))
    lines = [f"# Ops agent report: {now}", "", f"Run `{run_id}`: {len(ordered)} finding(s).", ""]
    if stats:
        lines += ["| metric | value |", "|---|---|", *[f"| {k} | {v} |" for k, v in stats.items()], ""]

    if ordered:
        lines += ["## Summary", "", "| severity | category | finding | seen | confidence | action |", "|---|---|---|---|---|---|"]
        for f, d in ordered:
            lines.append(
                f"| {f.severity} | {f.category} | {f.title} | {f.occurrences}x | {f.confidence:.0%} | {d.action} |"
            )
        lines.append("")

    for f, d in ordered:
        lines += [
            f"## {f.title}",
            "",
            (
                f"**Severity:** {f.severity} · **Category:** {f.category} · **Seen:** {f.occurrences}x · "
                f"**Confidence:** {f.confidence:.0%} · **Fingerprint:** `{f.fingerprint}`"
            ),
            "",
        ]
        if f.fingerprint in links:
            lines += [f"**GitHub:** {links[f.fingerprint]}", ""]
        lines += ["### Root cause", "", f.root_cause, ""]
        if f.evidence:
            lines += ["### Evidence", "", *[f"- {e}" for e in f.evidence], ""]
        if f.affected_files:
            lines += ["### Affected files", "", *[f"- `{p}`" for p in f.affected_files], ""]
        lines += ["### Suggested fix", "", f.suggested_fix, ""]
        if f.patch.strip():
            patch_file = run_dir / f"{f.fingerprint}.patch"
            patch_file.write_text(f.patch if f.patch.endswith("\n") else f.patch + "\n")
            lines += [
                "### Patch",
                "",
                f"Apply with: `git apply {patch_file.as_posix()}` (review it first!)",
                "",
                "```diff",
                f.patch.rstrip(),
                "```",
                "",
            ]
        if f.improvements:
            lines += ["### Further improvements", "", *[f"- [ ] {i}" for i in f.improvements], ""]
        if d.reasons:
            lines += ["### Why the agent did not go further", "", *[f"- {r}" for r in d.reasons], ""]

    report = run_dir / "report.md"
    report.write_text("\n".join(lines))
    return report
