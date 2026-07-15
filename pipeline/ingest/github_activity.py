import asyncio
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import logging
from services.github import search_issues, fetch_pr_diff, get_recent_commits
from models.github import GitHubIssue

logger = logging.getLogger(__name__)


class ActivityBundle(BaseModel):
    owner: str
    repo: str
    formatted_markdown: str


def _format_item(item: GitHubIssue, item_type: str = "Issue") -> str:
    item_number = item.number
    item_title = item.title
    item_author = item.user.login if item.user else 'N/A'
    item_body = item.body or ""
    labels = [label.name for label in item.labels]

    content = f"========================================\n"
    content += f"{item_type} #{item_number}: {item_title}\n"
    content += f"Author: {item_author}\n"
    content += f"State: {item.state}\n"
    if item.state == 'closed':
        content += f"Closed At: {item.closed_at or 'N/A'}\n"
    content += f"Labels: {labels}\n"
    content += f"----------------------------------------\n\n"
    content += f"{item_body}\n\n"
    return content


async def fetch_activity(owner: str, repo: str, days_closed: int = 7) -> ActivityBundle:
    full_text_content = ""

    query_open = f"repo:{owner}/{repo} is:open"
    open_items = await search_issues(query_open)

    if open_items:
        full_text_content += f"### Currently Open Issues & PRs\n\n"
        for item in open_items:
            is_pr = item.pull_request is not None
            item_type = "Pull Request" if is_pr else "Issue"
            full_text_content += _format_item(item, item_type)

            if is_pr:
                diff_url = item.pull_request.get('diff_url') if isinstance(item.pull_request, dict) else None
                if diff_url:
                    diff_content = await fetch_pr_diff(diff_url)
                    full_text_content += f"--- Diff ---\n\n{diff_content}\n\n--- End of Diff ---\n\n"
            full_text_content += f"========================================\n\n\n"

    date_since = (datetime.now(timezone.utc) - timedelta(days=days_closed)).strftime('%Y-%m-%dT%H:%M:%SZ')

    commits = await get_recent_commits(owner, repo, date_since)
    if commits:
        full_text_content += f"### Recent Commits (Last {days_closed} days)\n"
        for c in commits[:20]:
            msg = c['commit']['message'].split('\n')[0]
            author = c['commit']['author']['name'] if c.get('commit', {}).get('author') else 'Unknown'
            full_text_content += f"- {c['sha'][:7]}: {msg} (@{author})\n"
        full_text_content += "\n========================================\n\n"

    query_closed = f"repo:{owner}/{repo} is:closed closed>{date_since}"
    closed_items = await search_issues(query_closed)

    if closed_items:
        full_text_content += f"### Recently Closed Issues & Merged PRs\n\n"
        for item in closed_items:
            is_pr = item.pull_request is not None
            item_type = "Pull Request" if is_pr else "Issue"
            full_text_content += _format_item(item, item_type)
            full_text_content += f"========================================\n\n\n"

    return ActivityBundle(owner=owner, repo=repo, formatted_markdown=full_text_content)


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    bundle = await fetch_activity(args.owner, args.repo)
    logger.info(f"Generated {len(bundle.formatted_markdown)} bytes of activity data for {args.owner}/{args.repo}")


if __name__ == "__main__":
    asyncio.run(main())