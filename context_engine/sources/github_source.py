import asyncio
from datetime import datetime, timezone
import logging
from config import GITHUB_REPOS
from pipeline.ingest.github_repo import fetch_markdown
from pipeline.ingest.github_activity import fetch_activity
from context_engine.formatter import escape_xml, cdata_wrap, normalize_crlf

logger = logging.getLogger(__name__)


async def fetch_github_content(keys_str: str, mode: str, since_dt: datetime | None) -> tuple[str, int]:
    keys = keys_str.split(",") if keys_str and keys_str != "all" else None
    targets = GITHUB_REPOS
    if keys: targets = [r for r in GITHUB_REPOS if r.key in keys]
    if not targets: return "", 0

    bundle_content = []

    for repo_conf in targets:
        repo_id = f"gh:{escape_xml(repo_conf.repo)}"
        is_gov = (repo_conf.repo == "communications")
        repo_type = "governance" if is_gov else "technical"

        repo_xml = []
        days_closed = max(1, (datetime.now(timezone.utc) - since_dt).days) if since_dt else 30

        repo_xml.append(f'<repository id="{repo_id}" type="{repo_type}">')

        if mode in ("docs", "both") and "docs" in repo_conf.modes:
            try:
                repo_content = await fetch_markdown(repo_conf.owner, repo_conf.repo)
                docs_xml = []
                for path, content in repo_content.markdown_files.items():
                    content = normalize_crlf(content)
                    is_template = "template" in path.lower()
                    docs_xml.append(
                        f'      <document path="{escape_xml(path)}" is_template="{str(is_template).lower()}">{cdata_wrap(content)}</document>')

                if docs_xml:
                    repo_xml.append("  <documents>")
                    repo_xml.extend(docs_xml)
                    repo_xml.append("  </documents>")
            except Exception as e:
                logger.warning(f"Error fetching docs for {repo_conf.repo}: {e}")

        if mode in ("activity", "both") and "activity" in repo_conf.modes:
            try:
                activity_bundle = await fetch_activity(owner=repo_conf.owner, repo=repo_conf.repo,
                                                       days_closed=days_closed)
                repo_xml.append(activity_bundle.xml_content)
            except Exception as e:
                logger.warning(f"Error fetching activity for {repo_conf.repo}: {e}")

        repo_xml.append(f'</repository>')
        bundle_content.append("\n".join(repo_xml))

    return "\n".join(bundle_content), len(targets)