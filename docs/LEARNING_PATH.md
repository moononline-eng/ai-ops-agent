# Learning path

Work through these steps in order. Each one builds on the previous step and ends with something you can observe.

## 1. The app and its logs
- Read `demo_app/main.py` and find the 3 planted problems.
- Run the app with `uvicorn demo_app.main:app --port 8000`, then generate traffic with `python -m demo_app.traffic --rounds 60 --delay 0.05`.
- Open `logs/app.jsonl`. Notice that every line is JSON and that exceptions carry structured stack frames.
- **Takeaway:** *structured logs are the foundation.* An agent that has to scrape free-text logs is fragile.

## 2. Collector and redaction
- Run `python -c "from agent.collector import collect; from pathlib import Path; [print(g.count, g.title) for g in collect(Path('logs/app.jsonl'))[0]]"`
- Read `tests/test_collector.py` and `tests/test_redact.py`.
- **Exercise:** add a log line containing a fake key `sk-test-1234567890abcdef` and confirm it never appears in `audit/audit.jsonl` after a run.
- **Takeaway:** shrink and sanitize the input *before* the model sees it.

## 3. A single Claude call
Before the full agent, try the simplest thing that could work:
```python
import anthropic, json
from pathlib import Path
from agent.collector import collect
groups, _ = collect(Path("logs/app.jsonl"))
client = anthropic.Anthropic()
r = client.messages.create(model="claude-opus-5-5", max_tokens=4000,
    messages=[{"role": "user", "content": "Explain these errors:\n" + json.dumps([g.samples for g in groups])}])
print(r.content[-1].text)
```
- **Takeaway:** without the code, the model can only guess. That's why it needs tools.

## 4. The tool loop
- Read `agent/analyzer.py`, specifically `investigate()`. Trace one turn: request → `tool_use` → `RepoTools.run` → `tool_result` → next request.
- Run `python -m agent run --from-start`, then read `audit/audit.jsonl`. Look at which files the model chose to read, and how many tokens were cache reads.
- **Exercise:** set `AGENT_MAX_TOOL_CALLS_PER_FINDING=1` and see how answer quality changes.
- **Takeaway:** the agent loop is a plain `for` loop *you* own, so you decide its limits.

## 5. Structured output and policy
- Look at `FINDING_SCHEMA` and the `Finding` model. Look at `policy.decide()`.
- Run `pytest tests/test_policy.py -v`.
- **Exercise:** write a test showing that a patch to `.github/workflows/ci.yml` can never become a PR, even at confidence 1.0.
- **Takeaway:** the model proposes and code decides. Never let free text drive actions.

## 6. GitHub issues
- Create a **throwaway** GitHub repo, push this project to it, and create a fine-grained token (see SAFETY.md).
- Run `python -m agent run --mode issue --from-start` in dry run first, and read the `github_dry_run` audit events.
- Then run `python -m agent run --mode issue --no-dry-run --from-start`. Run it again and check that there are no duplicate issues.

## 7. Draft PRs
- Enable branch protection on `main` first.
- Run `python -m agent run --mode pr --no-dry-run --from-start`.
- Review the draft PR as a skeptical reviewer would. Is the fix right? Did it add a test?
- **Exercise:** break a patch on purpose (edit `validate_patch` input in a test) and watch the agent comment on the issue instead of opening a PR.

## 8. Deploy
- **Containers:** run `docker compose up --build` and read `docker-compose.yml`, especially the hardening options on `agent`.
- **CI:** add the `ANTHROPIC_API_KEY` secret, then trigger *Ops agent* with *Run workflow* in the Actions tab. Read the job summary and download the audit artifact.
- **Takeaway:** in production you replace the "Generate demo logs" step with a fetch from your real log backend. Nothing else changes.

## 9. Going further
- **Real log sources:** add a collector for Loki, CloudWatch, or Datadog that converts its output to the same entry dicts.
- **Notifications:** post the report summary to Slack.
- **Evals:** keep a folder of known bugs with expected root causes, run the agent on them after every prompt change, and score how many it gets right. This is how you improve an agent without guessing.
- **Model comparison:** run the same logs with `AGENT_MODEL=claude-sonnet-5-5` and compare quality against cost.
- **Proactive review:** add a mode that reviews recently changed files and suggests improvements before they cause errors.
