import asyncio
from pydantic import BaseModel
from typing import Dict
from pathlib import Path
import logging
from services.github import ensure_repo_cache

logger = logging.getLogger(__name__)

class RepoContent(BaseModel):
    owner: str
    repo: str
    markdown_files: Dict[str, str]

    def to_markdown(self) -> str:
        lines = []
        for path, content in self.markdown_files.items():
            lines.append(f"=== FILE: {path} ===\n\n{content}\n\n=== END OF FILE: {path} ===\n")
        return "\n".join(lines)

async def fetch_markdown(owner: str, repo: str) -> RepoContent:
    repo_path = await ensure_repo_cache(owner, repo)
    md_files = {}

    for md_file in repo_path.rglob("*.md"):
        rel_path = md_file.relative_to(repo_path).as_posix()
        try:
            md_files[rel_path] = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Error reading markdown file {rel_path}: {e}")

    return RepoContent(owner=owner, repo=repo, markdown_files=md_files)

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    content = await fetch_markdown(args.owner, args.repo)
    logger.info(f"Fetched {len(content.markdown_files)} markdown files from {args.owner}/{args.repo}")

if __name__ == "__main__":
    asyncio.run(main())