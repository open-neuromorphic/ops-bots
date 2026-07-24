import os
import json
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent
SECRETS_DIR = PROJECT_ROOT / "secrets"
CONFIG_FILE = PROJECT_ROOT / "bot_config.json"

bot_config_data = {}
if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            bot_config_data = json.load(f)
    except Exception as e:
        print(f"Warning: Failed to parse bot_config.json: {e}")


def get_conf(keys_path: str, default):
    keys = keys_path.split('.')
    val = bot_config_data
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SECRETS_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    FATHOM_API_KEY: str | None = None
    LIBRARY_BASE_DIR: str = "~/Documents/onm-library"

    LLM_STRONG_MODEL: str = "gemini-3.5-flash"
    LLM_FAST_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_API_KEY: str | None = None
    LLAMA_CPP_ENDPOINT: str | None = None

    LLAMA_SERVER_BIN: str = "~/Projects/llama.cpp/build/bin/llama-server"
    LLAMA_MODEL_PATH: str = "~/Projects/gemma-4-E4B_q4_0-it.gguf"

    GITHUB_TOKEN: str | None = None
    GITHUB_TOKEN_BOT: str | None = None

    PROD_REPO_OWNER: str = get_conf("github.prod_owner", "your-org")
    PROD_REPO_NAME: str = get_conf("github.prod_repo", "your-repo.github.io")
    STAGING_REPO_OWNER: str = get_conf("github.staging_owner", "your-bot-account")
    STAGING_REPO_NAME: str = get_conf("github.staging_repo", "your-repo.github.io")

    ONR_STAGING_REPO_OWNER: str = get_conf("github.onr_staging_owner", "your-org")
    ONR_STAGING_REPO_NAME: str = get_conf("github.onr_staging_repo", "onr-bot")

    DISCORD_GUILD_ID: int = get_conf("discord.guild_id", 0)

    EC_ADMIN_ROLE_IDS: str = ""
    CONTEXT_ENGINE_ALLOWED_ROLE_IDS: str = ""
    VOLUNTEER_TECHNICAL_ROLE_IDS: str = ""
    VOLUNTEER_CONTENT_ROLE_IDS: str = ""

    DOCUMENT_ID: str | None = None


settings = Settings()

ONR_RESEARCH_CHANNEL: str = get_conf("onr_research.target_channel", "research")
ONR_REVIEWERS_CHANNEL: str = get_conf("onr_research.reviewers_channel", "research-review")
ONR_DIGEST_CHANNELS: list[str] = get_conf("onr_research.digest_channels", [])
ONR_THRESHOLD_UPVOTES: int = get_conf("onr_research.threshold_upvotes", 1)
ONR_POLL_HOURS: int = get_conf("onr_research.poll_interval_hours", 2)
ONR_DISCUSSION_HOURS: int = get_conf("onr_research.discussion_duration_hours", 24)
ONR_PROPOSAL_DAYS: int = get_conf("onr_research.proposal_expiration_days", 7)
ARXIV_CURRENT_QUERY: str = get_conf("onr_research.arxiv_query", 'all:neuromorphic')
ARXIV_CURRENT_FLAGS: str = get_conf("onr_research.arxiv_flags", "sortBy=submittedDate&sortOrder=descending")

MAX_LOGO_IMAGE_BYTES: int = get_conf("pr_automation.max_logo_bytes", 5_000_000)
ALLOWED_LOGO_CONTENT_TYPES: str = get_conf("pr_automation.allowed_logo_types", "image/png,image/jpeg,image/gif,image/webp")
IMAGE_FETCH_TIMEOUT_SECONDS: int = get_conf("pr_automation.image_fetch_timeout_seconds", 20)
ALLOWED_LOGO_CONTENT_TYPES_SET: set[str] = {t.strip() for t in ALLOWED_LOGO_CONTENT_TYPES.split(",") if t.strip()}

CREDENTIALS_FILE: str = str(SECRETS_DIR / "credentials.json")
DRIVE_SCOPES: list[str] = ["https://www.googleapis.com/auth/documents.readonly",
                           "https://www.googleapis.com/auth/drive.readonly"]
DRIVE_TOKEN_FILE: str = str(SECRETS_DIR / "token.json")

CALENDAR_SCOPES: list[str] = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_TOKEN_FILE: str = str(SECRETS_DIR / "token_calendar.json")
CALENDAR_ID: str = get_conf("google.calendar_id", "primary")

FATHOM_BASE_URL: str = "https://api.fathom.ai/external/v1"
FATHOM_EXCLUDED_RECORDING_IDS: list[str] = []
ARXIV_BASE_URL: str = "http://export.arxiv.org/api/query"

LIBRARY_BASE_DIR: str = os.path.expanduser(settings.LIBRARY_BASE_DIR)

SOURCES_DIR: str = os.path.join(LIBRARY_BASE_DIR, "sources")
EC_MEETINGS_DIR: str = os.path.join(SOURCES_DIR, "ec_meetings")
FATHOM_RAW_DIR: str = os.path.join(SOURCES_DIR, "fathom", "raw")
FATHOM_FMT_DIR: str = os.path.join(SOURCES_DIR, "fathom", "formatted")
GITHUB_DATA_DIR: str = os.path.join(SOURCES_DIR, "github")
DISCORD_LOGS_DIR: str = os.path.join(SOURCES_DIR, "discord")

ARTIFACTS_DIR: str = os.path.join(LIBRARY_BASE_DIR, "artifacts")
DIGESTS_DIR: str = os.path.join(ARTIFACTS_DIR, "digests")
SUMMARIES_DIR: str = os.path.join(ARTIFACTS_DIR, "summaries")
ONR_HANDOFF_DIR: str = os.path.join(ARTIFACTS_DIR, "onr_handoffs")
META_DIR: str = os.path.join(LIBRARY_BASE_DIR, "meta")
CACHE_DIR: str = os.path.join(LIBRARY_BASE_DIR, "cache")
STATE_DIR: str = os.path.join(LIBRARY_BASE_DIR, "state")

FINAL_OUTPUT_DIR: str = os.path.join(LIBRARY_BASE_DIR, "google_docs")


def __getattr__(name):
    if hasattr(settings, name): return getattr(settings, name)
    raise AttributeError(f"module 'config' has no attribute '{name}'")


def _parse_ids(val: str) -> list[int]:
    if not val: return []
    return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]


OPERATION_ROLES: dict[str, list[int]] = {
    "ec_admin": _parse_ids(settings.EC_ADMIN_ROLE_IDS or settings.CONTEXT_ENGINE_ALLOWED_ROLE_IDS),
    "volunteer_technical": _parse_ids(settings.VOLUNTEER_TECHNICAL_ROLE_IDS),
    "volunteer_content": _parse_ids(settings.VOLUNTEER_CONTENT_ROLE_IDS),
}


class DiscordChannelSource(BaseModel):
    key: str
    channel_name: str
    category_tag: str


class GitHubRepoSource(BaseModel):
    key: str
    owner: str
    repo: str
    modes: tuple[str, ...]


_raw_channels = get_conf("discord.channels", [])
DISCORD_CHANNELS: list[DiscordChannelSource] = [DiscordChannelSource(**c) for c in _raw_channels]

_raw_repos = get_conf("github.watch_repos", [])
GITHUB_REPOS: list[GitHubRepoSource] = [GitHubRepoSource(**r) for r in _raw_repos]