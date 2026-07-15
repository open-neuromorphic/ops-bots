#!/usr/bin/env python3
import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Ensure the script can run standalone by adding project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from context_engine.library_index import ContextLibrary
from pipeline.ingest.github_repo import fetch_markdown
from pipeline.ingest.github_activity import fetch_activity
from services.cache import is_stale, hash_of


async def sync_snapshots() -> tuple[int, int, str]:
    logs = []

    def log(msg):
        print(msg)
        logs.append(msg)

    log(">>> Syncing GitHub Snapshot Documents & Activity <<<")
    lib = ContextLibrary()

    docs_repos = [r for r in config.GITHUB_REPOS if "docs" in r.modes]
    act_repos = [r for r in config.GITHUB_REPOS if "activity" in r.modes]

    updated_count = 0
    skipped_count = 0

    # Sync Repository Documentation (Markdown files)
    for repo_conf in docs_repos:
        log(f"Fetching markdown for {repo_conf.owner}/{repo_conf.repo}...")
        try:
            repo_content = await fetch_markdown(repo_conf.owner, repo_conf.repo)

            repo_cache_dir = Path(config.GITHUB_DATA_DIR) / "repos" / f"{repo_conf.owner}_{repo_conf.repo}"

            for rel_path, content in repo_content.markdown_files.items():
                entry_id = f"snapshot:{repo_conf.key}:{rel_path}"
                source_p = repo_cache_dir / rel_path

                existing_entry = lib.get(entry_id)
                if existing_entry and not is_stale(existing_entry, source_p):
                    skipped_count += 1
                    continue

                log(f"  -> Updating snapshot: {rel_path}")
                lib.add_or_update(
                    entry_id=entry_id,
                    title=f"{repo_conf.repo} - {rel_path}",
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    source_type="snapshot_doc",
                    category_tag=repo_conf.key,
                    source_path=str(source_p),
                    content_hash=hash_of(source_p),
                    audience_tier="ec"  # Snapshots default to EC unless flagged otherwise
                )
                updated_count += 1

        except Exception as e:
            log(f"❌ Error processing docs for repo {repo_conf.repo}: {e}")

    # Sync Repository Activity (Issues, Commits, PRs)
    for repo_conf in act_repos:
        log(f"Fetching activity for {repo_conf.owner}/{repo_conf.repo}...")
        try:
            bundle = await fetch_activity(owner=repo_conf.owner, repo=repo_conf.repo, days_closed=14)
            if bundle.formatted_markdown.strip():
                rel_path = f"{repo_conf.repo}_activity.md"
                entry_id = f"snapshot_activity:{repo_conf.key}"
                repo_cache_dir = Path(config.GITHUB_DATA_DIR) / "repos" / f"{repo_conf.owner}_{repo_conf.repo}"
                repo_cache_dir.mkdir(parents=True, exist_ok=True)
                source_p = repo_cache_dir / rel_path

                source_p.write_text(bundle.formatted_markdown, encoding="utf-8")

                existing_entry = lib.get(entry_id)
                if existing_entry and not is_stale(existing_entry, source_p):
                    skipped_count += 1
                    continue

                log(f"  -> Updating activity snapshot: {rel_path}")
                lib.add_or_update(
                    entry_id=entry_id,
                    title=f"{repo_conf.repo} - Recent Activity",
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    source_type="github_activity",
                    category_tag=repo_conf.key,
                    source_path=str(source_p),
                    content_hash=hash_of(source_p),
                    audience_tier="ec"
                )
                updated_count += 1
        except Exception as e:
            log(f"❌ Error processing activity for repo {repo_conf.repo}: {e}")

    log(f"\n✅ Snapshot Sync Complete. Updated {updated_count} files, skipped {skipped_count} unchanged files.")
    return updated_count, skipped_count, "\n".join(logs)


def main():
    asyncio.run(sync_snapshots())


if __name__ == "__main__":
    main()