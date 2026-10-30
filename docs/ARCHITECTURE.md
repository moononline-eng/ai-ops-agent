# Architecture

## Data flow

```
                  ┌──────────────────────────── one run ─────────────────────────────┐
 logs/app.jsonl ──▶ collector ──▶ redact ──▶ analyzer (per error group) ──▶ policy ──▶ actions
  (read-only)      group by        secrets     Claude + read-only tools     rules      report.md + .patch
                   fingerprint     & PII out   ↻ tool loop, capped          in code    GitHub issue
                   checkpointed                structured JSON Finding                 sandbox test → draft PR
                  └──────────────────────────────── audit.jsonl ─────────────────────┘
```

## Key design decisions

### 1. Group before you prompt (collector)
Production logs are huge and repetitive. Sending raw logs to an LLM is expensive, and it also works worse. The collector reduces logs to **error groups**. A group's fingerprint is the exception type plus the deepest stack frame in *our* code, so a framework frame doesn't count. Ten thousand identical KeyErrors become one group with a count and three samples.

The fingerprint does three jobs. It controls cost, it gives the model focused context, and it is the dedupe key for GitHub issues. Each run only reads new lines, using a byte-offset checkpoint (`.agent_state.json`).

### 2. Redact on the way in (redact)
Logs contain emails, IPs, tokens, and sometimes passwords. Redaction runs **before** the LLM sees anything, and again on tool output, because source files can hold secrets too. The patterns are deliberately greedy.

### 3. A workflow with one agentic step
Most of the pipeline is ordinary deterministic code. Only the "investigate the root cause" step is agentic: Claude decides which files to read. The rule of thumb is to use an LLM only where you need judgment and to keep everything around it predictable.

### 4. A hand-written tool loop (analyzer)
The Anthropic SDK has a tool runner that drives the loop for you. Here the loop is written by hand, because owning it makes the guardrails explicit and easy to read:

- a hard cap on tool calls per investigation, and on loop turns
- a token budget across the whole run (`BudgetExceeded` stops the run cleanly)
- an audit event for every model response and tool call
- `stop_reason` handling for `refusal`, `max_tokens`, `tool_use`, and `end_turn`

The final answer is constrained by **structured outputs** (`output_config.format` with a JSON schema), then validated again with Pydantic. Downstream code never parses free text.

### 5. Read-only tools only (tools)
The model gets `list_files`, `read_file`, and `search_code`. It gets no shell and no write access. Each tool is jailed to the repo root, which blocks `..` paths, absolute paths, and symlinks that escape. A deny-list hides `.env`, `.git`, `.github`, and keys. Tools are marked `strict: true`, so their inputs always match the schema.

### 6. The model proposes, policy decides (policy)
The model never chooses the action. `policy.decide()` takes the *configured* ceiling (`report` < `issue` < `pr`) and downgrades it when needed. That happens when there is no patch, when confidence is low, when the patch touches protected or non-allowlisted paths, when it changes file modes, or when it is too large. Because these are plain `if` statements, prompt injection can't bypass them.

### 7. Prove the patch before proposing it (pull_requests)
A patch is applied to a **scratch copy** of the repo, and the test suite runs against that copy with a scrubbed environment and a timeout. Only patches that pass become **draft** PRs. Files are uploaded through the GitHub REST API rather than `git push`, so the token never touches git.

### 8. Everything is audited (audit)
`audit/audit.jsonl` is append-only. It records model usage per turn, every tool call and its input, every GitHub write (or dry-run intent), refusals, and budget stops. When the agent does something surprising, this file tells you why.

## Model choices

- **Model:** `claude-opus-5-5` by default. Set `AGENT_MODEL=claude-sonnet-5-5` for cheaper runs, then compare report quality.
- **Thinking:** adaptive. Depth is controlled with `AGENT_EFFORT` (`high` by default).
- **Prompt caching:** `cache_control` on the request means the system prompt, tools, and growing history are cached across the turns of the loop. Check `cache_read` in the audit log.
- **Refusal fallback:** requests opt into server-side `fallbacks: "default"`. If a safety classifier declines, which can happen with security-flavored logs, the API retries on a fallback model instead of failing.

## Production deployment options

| Option | Fits when |
|---|---|
| **Scheduled GitHub Action** (`ops-agent.yml`) | Logs can be fetched from a log backend. Easiest setup, runners are disposable, secrets live in GitHub. |
| **Container next to the app** (`docker-compose.yml`) | Logs live on the host or in a shared volume. The agent is hardened: read-only root filesystem, no capabilities, separate network. |
| **Kubernetes CronJob** | The same container with a read-only log volume mount and a NetworkPolicy that allows egress only to `api.anthropic.com` and `api.github.com`. |
| **Event-driven** | An alerting tool (Sentry, Datadog) calls a webhook that triggers the run. Same agent, different trigger. |
