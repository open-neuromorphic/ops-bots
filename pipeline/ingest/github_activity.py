import asyncio
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import logging
import re
from services.github import search_issues, fetch_pr_diff, get_recent_commits, get_pr_files, get_issue_comments, get_repo_labels
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

    # Fetch repository label definitions schema
    repo_labels = []
    try:
        repo_labels = await get_repo_labels(owner, repo)
    except Exception as e:
        logger.warning(f"Failed to fetch repo labels for {owner}/{repo}: {e}")

    if repo_labels:
        xml_content.append("  <labels_schema>")
        for label in repo_labels:
            desc = label.get("description") or ""
            color = label.get("color") or ""
            xml_content.append(f'    <label id="{label.get("id")}" name="{escape_xml(label.get("name"))}" color="{escape_xml(color)}">{escape_xml(desc)}</label>')
        xml_content.append("  </labels_schema>")

    date_since = (datetime.now(timezone.utc) - timedelta(days=days_closed)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # 1. Fetch ALL open issues/PRs
    open_items = await search_issues(f"repo:{owner}/{repo} is:open")

    # 2. Fetch ONLY issues/PRs closed within the lookback window
    closed_items = await search_issues(f"repo:{owner}/{repo} is:closed closed:>{date_since}")

    all_items = open_items + closed_items

    open_prs_xml = []
    closed_prs_xml = []
    open_issues_xml = []
    closed_issues_xml = []

    for item in all_items:
        is_pr = item.pull_request is not None
        tag = "pull_request" if is_pr else "issue"
        tag_id = f"gh:{repo}:{'pr' if is_pr else 'issue'}:{item.number}"

        cache_key = f"{tag_id.replace(':', '_')}.xml"
        cached_path = cache_get(cache_key, subdir="github_items")
        use_cache = False

        # Better cache utilization: apply to BOTH open and closed items to save API calls
        if cached_path and cached_path.exists() and item.updated_at:
            mtime = cached_path.stat().st_mtime
            updated_ts = datetime.strptime(item.updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc).timestamp()
            if mtime > updated_ts:
                use_cache = True

        # Invalidate legacy cache artifacts to resolve the closed-records metadata regression or if <labels> element is missing
        if use_cache:
            cached_text = cached_path.read_text(encoding="utf-8")
            if 'created_at=' not in cached_text or '<author>' not in cached_text or (item.labels and '<labels>' not in cached_text):
                use_cache = False
            else:
                item_xml_str = cached_text

        if not use_cache:
            item_xml = []
            author_raw = item.user.login if item.user else "ghost"
            author_resolved = resolve_github_author(author_raw)
            labels_lower = [l.name.lower() for l in item.labels]

            created_at_val = item.created_at or ""
            updated_at_val = item.updated_at or ""
            closed_at_val = item.closed_at or ""

            item_xml.append(
                f'      <{tag} id="{tag_id}" state="{item.state}" created_at="{created_at_val}" updated_at="{updated_at_val}" closed_at="{closed_at_val}">')
            item_xml.append(f'        <title>{escape_xml(item.title)}</title>')
            item_xml.append(f'        <author>{escape_xml(author_resolved)}</author>')

            if item.labels:
                item_xml.append('        <labels>')
                for label in item.labels:
                    item_xml.append(f'          <label>{escape_xml(label.name)}</label>')
                item_xml.append('        </labels>')

            clean_body = strip_boilerplate(item.body)
            item_xml.append(f'        <description>{cdata_wrap(clean_body)}</description>')

            if item.comments > 0:
                item_xml.append(f'        <comments>')
                for c in comments:
                    c_author_raw = c.user.login if c.user else "ghost"
                    c_author_resolved = resolve_github_author(c_author_raw)
                    clean_comment = strip_boilerplate(c.body)
                    c_created_at_val = c.created_at or ""
                    item_xml.append(
                        f'          <comment author="{escape_xml(c_author_resolved)}" timestamp="{c_created_at_val}">')
                    item_xml.append(f'{cdata_wrap(clean_comment)}')
                    item_xml.append(f'          </comment>')
                item_xml.append(f'        </comments>')

            if is_pr:
                files = await get_pr_files(owner, repo, item.number)
                if files:
                    item_xml.append(f'        <manifest>')
                    for f in files:
                        action = str(f.get('status', 'modified')).upper()
                        path = escape_xml(f.get('filename', ''))
                        item_xml.append(f'          <file action="{action}" path="{path}" />')
                    item_xml.append(f'        </manifest>')

                if is_gov and "pruning" not in labels_lower and item.pull_request:
                    diff_url = item.pull_request.get('diff_url')
                    if diff_url:
                        diff = await fetch_pr_diff(diff_url)
                        item_xml.append(f'        <governance_diff>{cdata_wrap(diff)}</governance_diff>')

            item_xml.append(f'      </{tag}>')
            item_xml_str = "\n".join(item_xml)

            # Update cache to save massive API rate limits on subsequent fetches
            cache_put(cache_key, item_xml_str, subdir="github_items")

        # Route to appropriate hierarchical bucket
        if is_pr:
            if item.state == "open":
                open_prs_xml.append(item_xml_str)
            else:
                closed_prs_xml.append(item_xml_str)
        else:
            if item.state == "open":
                open_issues_xml.append(item_xml_str)
            else:
                closed_issues_xml.append(item_xml_str)

    if open_prs_xml or closed_prs_xml:
        xml_content.append("  <pull_requests>")
        if open_prs_xml:
            xml_content.append("    <open>")
            xml_content.extend(open_prs_xml)
            xml_content.append("    </open>")
        if closed_prs_xml:
            xml_content.append(f'    <recently_closed lookback_days="{days_closed}">')
            xml_content.extend(closed_prs_xml)
            xml_content.append("    </recently_closed>")
        xml_content.append("  </pull_requests>")

    if open_issues_xml or closed_issues_xml:
        xml_content.append("  <issues>")
        if open_issues_xml:
            xml_content.append("    <open>")
            xml_content.extend(open_issues_xml)
            xml_content.append("    </open>")
        if closed_issues_xml:
            xml_content.append(f'    <recently_closed lookback_days="{days_closed}">')
            xml_content.extend(closed_issues_xml)
            xml_content.append("    </recently_closed>")
        xml_content.append("  </issues>")

    commits = await get_recent_commits(owner, repo, date_since)
    if commits:
        xml_content.append(f'  <recent_commits lookback_days="{days_closed}">')
        for c in commits:
            msg = c['commit']['message'].split('\n')[0]
            if re.match(r"^Merge (pull request|branch)", msg):
                continue

            author_raw = c['commit']['author']['name'] if c.get('commit', {}).get('author') else 'ghost'
            author_resolved = resolve_git_author(author_raw)
            sha = escape_xml(c['sha'][:7])

            xml_content.append(
                f'    <commit sha="{sha}" author="{escape_xml(author_resolved)}">{escape_xml(msg)}</commit>')
        xml_content.append(f'  </recent_commits>')

    return ActivityBundle(owner=owner, repo=repo, xml_content="\n".join(xml_content))