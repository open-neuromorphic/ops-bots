import asyncio
from datetime import datetime, timezone
import logging
from config import GITHUB_REPOS
from pipeline.ingest.github_repo import fetch_markdown
from pipeline.ingest.github_activity import fetch_activity

logger = logging.getLogger(__name__)

async def fetch_github_content(keys_str: str, mode: str, since_dt: datetime | None) -> tuple[str, int]:
    """
    Fetches GitHub content (docs, activity, or both) entirely in-memory using pipeline components.
    Returns (formatted_markdown, repo_count).
    """
    keys = keys_str.split(",") if keys_str and keys_str != "all" else None

    targets = GITHUB_REPOS
    if keys:
        targets = [r for r in GITHUB_REPOS if r.key in keys]

    if not targets:
        return "", 0

    bundle_content = []

    for repo_conf in targets:
        bundle_content.append(f"## GitHub: {repo_conf.owner}/{repo_conf.repo}")

        if mode in ("docs", "both") and "docs" in repo_conf.modes:
            try:
                repo_content = await fetch_markdown(repo_conf.owner, repo_conf.repo)
                docs_markdown = repo_content.to_markdown()
                if docs_markdown.strip():
                    bundle_content.append(f"### Repository Docs\n\n{docs_markdown}")
            except Exception as e:
                logger.warning(f"Error fetching docs for {repo_conf.repo}: {e}")
                bundle_content.append(f"> ⚠️ Error fetching docs: {e}")

        if mode in ("activity", "both"):
            days_closed = 7
            if since_dt:
                delta = datetime.now(timezone.utc) - since_dt
                days_closed = max(1, delta.days)

            try:
                activity_bundle = await fetch_activity(owner=repo_conf.owner, repo=repo_conf.repo, days_closed=days_closed)
                if activity_bundle.formatted_markdown.strip():
                    bundle_content.append(f"### Repository Activity (Last {days_closed} days)\n\n{activity_bundle.formatted_markdown}")
            except Exception as e:
                logger.warning(f"Error fetching activity for {repo_conf.repo}: {e}")
                bundle_content.append(f"> ⚠️ Error fetching activity: {e}")

        bundle_content.append("---\n")

    return "\n".join(bundle_content), len(targets)