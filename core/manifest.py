from pydantic import BaseModel
from typing import List

class BotManifest(BaseModel):
    name: str
    entrypoint: str
    token_env: str
    log_file: str
    cogs: List[str]
    dependencies: List[str]

BOTS = {
    "onm-scribe": BotManifest(
        name="onm-scribe",
        entrypoint="run_onm_scribe.py",
        token_env="DISCORD_TOKEN_SCRIBE",
        log_file="logs/onm_scribe.log",
        cogs=[
            'cogs.admin', 'cogs.user_data', 'cogs.contributor_report',
            'cogs.channel_activity', 'cogs.social_digest', 'cogs.leadership_digest',
            'cogs.role_analysis', 'cogs.context', 'cogs.menu_scribe'
        ],
        dependencies=[
            "pipeline/reporting/",
            "pipeline/summarize/",
            "pipeline/context_engine/"
        ]
    ),
    "onm-content-ops": BotManifest(
        name="onm-content-ops",
        entrypoint="run_onm_content_ops.py",
        token_env="DISCORD_TOKEN_CONTENT_OPS",
        log_file="logs/onm_content_ops.log",
        cogs=[
            'cogs.admin', 'cogs.github_projects', 'cogs.pr_automation',
            'cogs.menu_content_ops', 'cogs.event_ops'
        ],
        dependencies=[
            "pipeline/pr_automation/"
        ]
    ),
    "onm-research": BotManifest(
        name="onm-research",
        entrypoint="run_onm_research.py",
        token_env="DISCORD_TOKEN_RESEARCH",
        log_file="logs/onm_research.log",
        cogs=[
            'cogs.admin', 'cogs.onr_research', 'cogs.menu_research'
        ],
        dependencies=[
            "pipeline/onr/",
            "services/arxiv.py",
            "services/state_store.py"
        ]
    )
}

CORE_FILES = [
    "core/",
    "services/",
    "utils/",
    "models/meta.py",
    "models/library.py",
    "models/github.py",
    "models/requests.py",
    "models/taxonomies.py",
    "models/onr.py",
    "context_engine/",
    "requirements.txt",
    "config.py",
    "bot_config.json"
]