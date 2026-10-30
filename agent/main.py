"""CLI entry point.

  python -m agent run                          # report only, dry run (safe default)
  python -m agent run --mode issue --no-dry-run
  python -m agent run --mode pr --no-dry-run --from-start
"""

import argparse
import json
import shutil
import sys
import uuid
from datetime import UTC, datetime

from agent.actions.github import DryRunGitHub, GitHub, WriteBudgetExceeded
from agent.actions.issues import open_or_update_issue
from agent.actions.pull_requests import open_draft_pr, validate_patch
from agent.actions.report import write_report
from agent.analyzer import Analyzer, BudgetExceeded
from agent.audit import AuditLog
from agent.collector import collect
from agent.config import Settings, load_settings
from agent.policy import RANK, decide


def load_offset(s: Settings) -> int:
    try:
        return json.loads(s.state_file.read_text()).get("offset", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def save_offset(s: Settings, offset: int) -> None:
    s.state_file.write_text(json.dumps({"offset": offset}))


def run(s: Settings, from_start: bool = False, client=None) -> int:
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    audit = AuditLog(s.audit_file, run_id)
    audit.record("run_start", mode=s.mode, dry_run=s.dry_run, model=s.model)
    print(f"run {run_id}: mode={s.mode} dry_run={s.dry_run}")

    offset = 0 if from_start else load_offset(s)
    if s.log_file.exists() and offset > s.log_file.stat().st_size:
        offset = 0  # log was rotated
    groups, new_offset = collect(s.log_file, offset)
    print(f"found {len(groups)} problem group(s) in {s.log_file}")
    if not groups:
        save_offset(s, new_offset)
        audit.record("run_end", findings=0)
        return 0

    analyzer = Analyzer(s, audit, client=client)
    results = []
    for group in groups[: s.max_findings_per_run]:
        print(f"  investigating: {group.title} ({group.count}x)")
        try:
            finding = analyzer.investigate(group)
        except BudgetExceeded as e:
            print(f"  stopping: {e}")
            audit.record("budget_exceeded", error=str(e))
            break
        if finding:
            results.append((finding, decide(finding, s)))

    links: dict[str, str] = {}
    if s.mode != "report" and results:
        gh = (
            DryRunGitHub(audit, s.max_github_writes_per_run)
            if s.dry_run
            else GitHub(s.github_repo, s.github_token, audit, s.max_github_writes_per_run)
        )
        try:
            for finding, decision in results:
                act_on_github(gh, s, finding, decision, links)
        except WriteBudgetExceeded as e:
            print(f"  stopping GitHub actions: {e}")
            audit.record("write_budget_exceeded")

    stats = {
        "error groups": len(groups),
        "investigated": min(len(groups), s.max_findings_per_run),
        "findings": len(results),
        "input tokens (incl. cache)": analyzer.tokens_used,
        "output tokens": analyzer.output_tokens,
        "model": s.model,
    }
    report = write_report(results, s.reports_dir, run_id, links, stats)
    save_offset(s, new_offset)
    audit.record("run_end", report=str(report), stats=stats)
    print(f"report: {report}")
    return 0


def act_on_github(gh, s: Settings, finding, decision, links: dict) -> None:
    if RANK[decision.action] < RANK["issue"]:
        return
    issue = open_or_update_issue(gh, finding)
    links[finding.fingerprint] = issue.get("html_url", "")
    if decision.action != "pr":
        return
    result = validate_patch(s.repo_root, finding.patch)
    try:
        if result.ok:
            pr = open_draft_pr(gh, finding, result, s.github_base_branch, issue)
            links[finding.fingerprint] += f" · PR: {pr.get('html_url', '')}"
        else:
            decision.reasons.append("patch failed validation in sandbox")
            gh.comment(issue["number"], f"The proposed patch did not pass validation:\n```\n{result.log[-1500:]}\n```")
    finally:
        if result.workdir:
            shutil.rmtree(result.workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent", description="AI ops agent: logs in, findings out.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="analyze new log entries")
    r.add_argument("--mode", choices=["report", "issue", "pr"])
    r.add_argument("--dry-run", dest="dry_run", action="store_true", default=None)
    r.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    r.add_argument("--log-file")
    r.add_argument("--repo-root")
    r.add_argument("--from-start", action="store_true", help="ignore the checkpoint and re-read the whole log")
    args = parser.parse_args(argv)

    s = load_settings(mode=args.mode, dry_run=args.dry_run, log_file=args.log_file, repo_root=args.repo_root)
    return run(s, from_start=args.from_start)


if __name__ == "__main__":
    sys.exit(main())
