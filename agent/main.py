"""CLI entry point.

  python -m agent run                          # report only, dry run (safe default)
  python -m agent run --mode issue --no-dry-run
  python -m agent run --mode pr --no-dry-run --from-start
"""

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import anthropic
import httpx

from agent.actions.github import DryRunGitHub, GitHub, WriteBudgetExceeded
from agent.actions.issues import open_or_update_issue
from agent.actions.pull_requests import open_draft_pr, validate_patch
from agent.actions.report import write_report
from agent.analyzer import Analyzer, BudgetExceeded
from agent.audit import AuditLog
from agent.collector import collect
from agent.config import Settings, load_settings
from agent.policy import RANK, decide


def log_identity(log_file: Path) -> str:
    """Hash of the file's first line: changes when the log is rotated or replaced."""
    try:
        with log_file.open("rb") as f:
            return hashlib.sha256(f.readline()).hexdigest()[:16]
    except FileNotFoundError:
        return ""


def load_offset(s: Settings) -> int:
    """Resume where the last run stopped, unless the log file is a different one now."""
    try:
        state = json.loads(s.state_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return 0
    offset = state.get("offset", 0)
    size = s.log_file.stat().st_size if s.log_file.exists() else 0
    if state.get("log_id") != log_identity(s.log_file) or offset > size:
        return 0  # log was rotated or replaced: start from the top
    return offset


def save_offset(s: Settings, offset: int) -> None:
    s.state_file.write_text(json.dumps({"offset": offset, "log_id": log_identity(s.log_file)}))


def run(s: Settings, from_start: bool = False, client=None) -> int:
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    audit = AuditLog(s.audit_file, run_id)
    audit.record("run_start", mode=s.mode, dry_run=s.dry_run, model=s.model)
    print(f"run {run_id}: mode={s.mode} dry_run={s.dry_run}")

    offset = 0 if from_start else load_offset(s)
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
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.APIConnectionError) as e:
            return _abort(audit, f"cannot use the Anthropic API ({type(e).__name__}): {e}")
        except TypeError as e:
            if "authentication" not in str(e):
                raise
            return _abort(audit, "no Anthropic credentials: set ANTHROPIC_API_KEY in the environment or .env")
        except anthropic.APIStatusError as e:
            # One bad request shouldn't sink the run: record it and move on to the next group.
            print(f"  API error for this group, skipping: {e.status_code} {e.message}")
            audit.record("api_error", fingerprint=group.fingerprint, status=e.status_code, error=str(e)[:500])
            continue
        if finding:
            results.append((finding, decide(finding, s)))

    links: dict[str, str] = {}
    if s.mode != "report" and results:
        gh = (
            DryRunGitHub(audit, s.max_github_writes_per_run)
            if s.dry_run
            else GitHub(s.github_repo, s.github_token.get_secret_value(), audit, s.max_github_writes_per_run)
        )
        for finding, decision in results:
            try:
                act_on_github(gh, s, finding, decision, links)
            except WriteBudgetExceeded as e:
                print(f"  stopping GitHub actions: {e}")
                audit.record("write_budget_exceeded")
                break
            except httpx.HTTPError as e:
                # Keep going: the report still gets written and other findings still get handled.
                print(f"  GitHub error for {finding.fingerprint}: {e}")
                decision.reasons.append(f"GitHub action failed: {e}")
                audit.record("github_error", fingerprint=finding.fingerprint, error=str(e)[:500])

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


def _abort(audit: AuditLog, message: str) -> int:
    # The checkpoint is not advanced, so the next run retries these log lines.
    print(f"error: {message}", file=sys.stderr)
    audit.record("run_aborted", error=message)
    return 2


def act_on_github(gh, s: Settings, finding, decision, links: dict) -> None:
    if RANK[decision.action] < RANK["issue"]:
        return
    issue, created = open_or_update_issue(gh, finding)
    links[finding.fingerprint] = issue.get("html_url", "")
    if decision.action != "pr":
        return
    if not created:
        # A PR was already attempted when this issue was opened; don't open duplicates.
        decision.reasons.append("issue already open; not opening another PR")
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
