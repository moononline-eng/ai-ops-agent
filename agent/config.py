"""All agent settings in one place, loaded from env vars / .env.

Safe defaults: report-only, dry-run, small budgets. Everything that writes to
the outside world must be switched on explicitly.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGENT_", extra="ignore")

    # What the agent is allowed to do: report < issue < pr
    mode: Literal["report", "issue", "pr"] = "report"
    # Dry run: decide and log everything, but make no GitHub calls
    dry_run: bool = True

    # Inputs
    log_file: Path = Path("logs/app.jsonl")
    repo_root: Path = Path(".")  # the source tree the agent may read
    state_file: Path = Path(".agent_state.json")  # checkpoint: last processed log offset

    # Outputs
    reports_dir: Path = Path("reports")
    audit_file: Path = Path("audit/audit.jsonl")

    # Model. The key is read without the AGENT_ prefix, from the environment or .env.
    # Leave it unset to fall back to the SDK's own resolution (e.g. an `ant auth login` profile).
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_tokens: int = 16000

    # Budgets (hard caps enforced in code, not by the model)
    max_findings_per_run: int = 5
    max_tool_calls_per_finding: int = 12
    max_input_tokens_per_run: int = 400_000
    max_github_writes_per_run: int = 3
    min_confidence_for_pr: float = 0.8
    max_diff_lines: int = 200
    # Patches may only touch files under these prefixes (JSON list in env)
    patch_allowed_prefixes: list[str] = ["demo_app/", "tests/"]

    # GitHub (only used when mode != report and dry_run is false)
    github_repo: str = ""  # "owner/name"
    github_token: SecretStr = SecretStr("")  # fine-grained token, see docs/SAFETY.md
    github_base_branch: str = "main"


def load_settings(**overrides) -> Settings:
    return Settings(**{k: v for k, v in overrides.items() if v is not None})
