import asyncio
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import logging
import re
from services.github import search_issues, fetch_pr_diff, get_recent_commits, get_pr_files, get_issue_comments
from context_engine.formatter import escape_xml, cdata_wrap
from services.cache import get as cache_get, put as cache_put

logger = logging.getLogger(__name__)


class ActivityBundle(BaseModel):
    owner: str
    repo: str
    formatted_markdown: str = ""
    xml_content: str


async def fetch_activity(owner: str, repo: str, days_closed: int = 30) -> ActivityBundle:
    xml_content = []
    is_gov = (repo == "communications")

    date_since = (datetime.now(timezone.utc) - timedelta(days=days_closed)).strftime('%Y-%m-%dT%H:%M:%SZ')
    query = f"repo:{owner}/{repo} updated:>{date_since}"
    items = await search_issues(query)

    for item in items:
        is_pr = item.pull_request is not None
        tag = "pull_request" if is_pr else "issue"
        tag_id = f"gh:{repo}:{'pr' if is_pr else 'issue'}:{item.number}"

        # Check Local Lookback Cache to prevent API quota starvation for unchanged closed items
        cache_key = f"{tag_id.replace(':', '_')}.xml"
        cached_path = cache_get(cache_key, subdir="github_items")
        use_cache = False

        if cached_path and cached_path.exists():
            if item.state == 'closed' and item.updated_at:
                mtime = cached_path.stat().st_mtime
                updated_ts = datetime.strptime(item.updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).timestamp()
                if mtime > updated_ts:
                    use_cache = True

        if use_cache:
            xml_content.append(cached_path.read_text(encoding="utf-8"))
            continue

        item_xml = []
        item_xml.append(f'  <{tag} id="{tag_id}" state="{item.state}">')
        item_xml.append(f'    <title>{escape_xml(item.title)}</title>')
        item_xml.append(f'    <description>{cdata_wrap(item.body)}</description>')

        if is_gov:
            if item.comments > 0:
                comments = await get_issue_comments(owner, repo, item.number)
                item_xml.append(f'    <comments>')
                for c in comments:
                    author = escape_xml(c.user.login) if c.user else "Unknown"
                    item_xml.append(f'      <comment author="{author}" timestamp="{c.created_at or ""}">')
                    item_xml.append(f'        {cdata_wrap(c.body)}')
                    item_xml.append(f'      </comment>')
                item_xml.append(f'    </comments>')

            if is_pr and item.pull_request:
                diff_url = item.pull_request.get('diff_url')
                if diff_url:
                    diff = await fetch_pr_diff(diff_url)
                    item_xml.append(f'    <governance_diff>{cdata_wrap(diff)}</governance_diff>')
        else:
            if is_pr:
                files = await get_pr_files(owner, repo, item.number)
                if files:
                    item_xml.append(f'    <manifest>')
                    for f in files:
                        action = str(f.get('status', 'modified')).upper()
                        path = escape_xml(f.get('filename', ''))
                        item_xml.append(f'      <file action="{action}" path="{path}" />')
                    item_xml.append(f'    </manifest>')

        item_xml.append(f'  </{tag}>')
        item_xml_str = "\n".join(item_xml)

        # Populate Lookback Cache only if closed (it's safe and static)
        if item.state == "closed":
            cache_put(cache_key, item_xml_str, subdir="github_items")

        xml_content.append(item_xml_str)

    commits = await get_recent_commits(owner, repo, date_since)
    if commits:
        xml_content.append(f'  <commits>')
        for c in commits:
            msg = c['commit']['message'].split('\n')[0]
            if re.match(r"^Merge (pull request|branch)", msg):
                continue
            author = escape_xml(c['commit']['author']['name']) if c.get('commit', {}).get('author') else 'Unknown'
            sha = escape_xml(c['sha'][:7])
            xml_content.append(f'    <commit sha="{sha}" author="{author}">{escape_xml(msg)}</commit>')
        xml_content.append(f'  </commits>')

    return ActivityBundle(owner=owner, repo=repo, xml_content="\n".join(xml_content))


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    bundle = await fetch_activity(args.owner, args.repo)
    logger.info(f"Generated {len(bundle.xml_content)} bytes of activity data for {args.owner}/{args.repo}")


if __name__ == "__main__":
    asyncio.run(main())