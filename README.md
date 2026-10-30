# ai-ops-agent

A learning project. It shows how to run an **AI agent in production**, next to an app.

The agent does four things:

- reads the app's logs and finds errors and slow endpoints
- investigates the source code with Claude to find the root cause
- suggests a fix and broader improvements
- delivers the result as a **Markdown report + patch file**, a **GitHub issue**, or a **draft PR**, depending on the trust level you configure

It is built to be **safe to run unattended**. See [docs/SAFETY.md](docs/SAFETY.md).

```
demo app ──JSON logs──▶ collector ─▶ redact ─▶ Claude (read-only tools) ─▶ policy ─▶ report / issue / draft PR
                                                                                └──▶ audit log (everything)
```

## Quickstart

```bash
# 1. Install (Python 3.11+)
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 2. Run the offline test suite (no API key needed)
pytest -q

# 3. Start the demo app and generate some errors
uvicorn demo_app.main:app --port 8000 &
python -m demo_app.traffic --rounds 60 --delay 0.05

# 4. Run the agent (safe default: report only, dry run)
cp .env.example .env    # add ANTHROPIC_API_KEY
python -m agent run
cat reports/*/report.md
```

Or run the whole thing in containers:

```bash
cp .env.example .env    # add ANTHROPIC_API_KEY
docker compose up --build
docker compose exec agent sh -c 'cat /data/reports/*/report.md'
```

## Modes: turning up trust step by step

| Mode | Needs | What happens |
|---|---|---|
| `report` (default) | API key | Writes `reports/<run>/report.md` and `<fingerprint>.patch` files. Nothing leaves your machine except redacted logs and code sent to the model. |
| `issue` | + GitHub token | Opens one issue per distinct problem. Problems are deduplicated by fingerprint, and a repeat adds a comment instead of a new issue. |
| `pr` | + GitHub token | Also opens a **draft** PR, but only if the patch passes policy checks **and** the test suite in a sandbox copy. |

`AGENT_DRY_RUN=true` (the default) runs all the logic but only *logs* the GitHub calls it would make, in `audit/audit.jsonl`. Turn it off only when you are ready:

```bash
python -m agent run --mode issue --no-dry-run
```

To re-analyze the whole log, ignoring the checkpoint, add `--from-start`.

## Applying a suggestion yourself

Every report contains ready-to-apply patches:

```bash
git apply --check reports/<run>/<fingerprint>.patch   # does it apply?
git apply reports/<run>/<fingerprint>.patch
pytest -q
```

## Project layout

| Path | What it is |
|---|---|
| `demo_app/` | FastAPI app with 3 planted problems: a KeyError, a ZeroDivisionError, and a slow N+1 loop |
| `agent/collector.py` | Parses JSONL logs and groups them into problem "fingerprints" |
| `agent/redact.py` | Strips secrets and PII before anything reaches the model |
| `agent/tools.py` | The model's only tools: read-only and jailed to the repo |
| `agent/analyzer.py` | The agent loop, with budgets, audit, and structured output |
| `agent/policy.py` | Deterministic rules that decide what the agent may actually do |
| `agent/actions/` | Report, GitHub issue, and sandboxed patch validation with draft PR |
| `agent/audit.py` | Append-only record of every model call, tool call, and action |
| `.github/workflows/ops-agent.yml` | Scheduled production run in GitHub Actions |
| `docker-compose.yml` | Local "production": app + traffic + hardened agent container |

## Learn it

Work through **[docs/LEARNING_PATH.md](docs/LEARNING_PATH.md)**. It walks through the system one concept at a time. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains the design decisions.
