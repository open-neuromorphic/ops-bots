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
from services.cache import is_stale, hash_of


async def sync_snapshots() -> tuple[int, int, str]:
    logs = []
    def log(msg):
        print(msg)
        logs.append(msg)

    log(">>> Syncing GitHub Snapshot Documents <<<")
    lib = ContextLibrary()

    docs_repos = [r for r in config.GITHUB_REPOS if "docs" in r.modes]

    updated_count = 0
    skipped_count = 0

    for repo_conf in docs_repos:
        log(f"Fetching markdown for {repo_conf.owner}/{repo_conf.repo}...")
        try:
            repo_content = await fetch_markdown(repo_conf.owner, repo_conf.repo)

            repo_cache_dir = Path(config.GITHUB_DATA_DIR) / "repos" / f"{repo_conf.owner}_{repo_conf.repo}"

            for rel_path, content in repo_content.markdown_files.items():
                entry_id = f"snapshot:{repo_conf.key}:{rel_path}"
                source_p = repo_cache_dir / rel_path

                # Create a temporary entry object to test staleness via existing cache util
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
            log(f"❌ Error processing repo {repo_conf.repo}: {e}")

    log(f"\n✅ Snapshot Sync Complete. Updated {updated_count} files, skipped {skipped_count} unchanged files.")
    return updated_count, skipped_count, "\n".join(logs)


def main():
    asyncio.run(sync_snapshots())


if __name__ == "__main__":
    main()