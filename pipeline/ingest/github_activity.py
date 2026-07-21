import asyncio
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import logging
import re
from services.github import search_issues, fetch_pr_diff, get_recent_commits, get_pr_files, get_issue_comments
from context_engine.formatter import escape_xml, cdata_wrap, strip_boilerplate
from services.cache import get as cache_get, put as cache_put
from services.entity_lookup import resolve_github_author, resolve_git_author

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

        # Invalidate legacy cache artifacts to resolve the closed-records metadata regression
        if use_cache:
            cached_text = cached_path.read_text(encoding="utf-8")
            if 'created_at=' not in cached_text or '<author>' not in cached_text:
                use_cache = False
            else:
                xml_content.append(cached_text)
                continue

        item_xml = []
        author_raw = item.user.login if item.user else "ghost"
        author_resolved = resolve_github_author(author_raw)
        labels_lower = [l.name.lower() for l in item.labels]

        # Extract dates safely to avoid backslashes inside f-string curly braces
        created_at_val = item.created_at or ""
        updated_at_val = item.updated_at or ""
        closed_at_val = item.closed_at or ""

        item_xml.append(
            f'  <{tag} id="{tag_id}" state="{item.state}" created_at="{created_at_val}" updated_at="{updated_at_val}" closed_at="{closed_at_val}">')
        item_xml.append(f'    <title>{escape_xml(item.title)}</title>')
        item_xml.append(f'    <author>{escape_xml(author_resolved)}</author>')

        clean_body = strip_boilerplate(item.body)
        item_xml.append(f'    <description>{cdata_wrap(clean_body)}</description>')

        if item.comments > 0:
            comments = await get_issue_comments(owner, repo, item.number)
            item_xml.append(f'    <comments>')
            for c in comments:
                c_author_raw = c.user.login if c.user else "ghost"
                c_author_resolved = resolve_github_author(c_author_raw)
                clean_comment = strip_boilerplate(c.body)
                c_created_at_val = c.created_at or ""
                item_xml.append(
                    f'      <comment author="{escape_xml(c_author_resolved)}" timestamp="{c_created_at_val}">')
                item_xml.append(f'        {cdata_wrap(clean_comment)}')
                item_xml.append(f'      </comment>')
            item_xml.append(f'    </comments>')

        if is_pr:
            # Always grab the file manifest for PRs to describe scope without heavy diffs
            files = await get_pr_files(owner, repo, item.number)
            if files:
                item_xml.append(f'    <manifest>')
                for f in files:
                    action = str(f.get('status', 'modified')).upper()
                    path = escape_xml(f.get('filename', ''))
                    item_xml.append(f'      <file action="{action}" path="{path}" />')
                item_xml.append(f'    </manifest>')

            # Limit full diff output to substantive governance decisions
            if is_gov and "pruning" not in labels_lower and item.pull_request:
                diff_url = item.pull_request.get('diff_url')
                if diff_url:
                    diff = await fetch_pr_diff(diff_url)
                    item_xml.append(f'    <governance_diff>{cdata_wrap(diff)}</governance_diff>')

        item_xml.append(f'  </{tag}>')
        item_xml_str = "\n".join(item_xml)

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

            author_raw = c['commit']['author']['name'] if c.get('commit', {}).get('author') else 'ghost'
            author_resolved = resolve_git_author(author_raw)
            sha = escape_xml(c['sha'][:7])

            xml_content.append(
                f'    <commit sha="{sha}" author="{escape_xml(author_resolved)}">{escape_xml(msg)}</commit>')
        xml_content.append(f'  </commits>')

    return ActivityBundle(owner=owner, repo=repo, xml_content="\n".join(xml_content))