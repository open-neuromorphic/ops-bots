import os
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Awaitable
import config
from context_engine.library_index import ContextLibrary
from context_engine.sources.github_source import fetch_github_content
from context_engine.sources.transcript_source import fetch_transcripts
from context_engine.sources.discord_source import fetch_discord_history
from context_engine.formatter import scan_and_redact, escape_xml
from models.requests import ContextBuildRequest
from services.cache import get as cache_get, put as cache_put, is_expired
from services.github import search_issues
from services.entity_lookup import resolve_github_author


async def _build_active_governance_map() -> str:
    xml = ["<active_governance_state_map>"]
    try:
        open_issues = await search_issues(f"repo:{config.PROD_REPO_OWNER}/communications is:open")
        prs = []
        issues = []
        for item in open_issues:
            author_raw = item.user.login if item.user else "Unknown"
            author_resolved = resolve_github_author(author_raw)
            title = escape_xml(item.title)

            if item.pull_request:
                prs.append(
                    f'    <pull_request id="gh:communications:pr:{item.number}">\n      <title>{title}</title>\n      <author>{escape_xml(author_resolved)}</author>\n    </pull_request>')
            else:
                issues.append(
                    f'    <issue id="gh:communications:issue:{item.number}">\n      <title>{title}</title>\n      <author>{escape_xml(author_resolved)}</author>\n    </issue>')

        xml.append("  <open_pull_requests>")
        xml.extend(prs)
        xml.append("  </open_pull_requests>")
        xml.append("  <open_issues>")
        xml.extend(issues)
        xml.append("  </open_issues>")
    except Exception as e:
        xml.append(f"  <!-- Error fetching state map: {e} -->")
    xml.append("</active_governance_state_map>")
    return "\n".join(xml)


def _get_entity_glossary_xml() -> str:
    path = Path(config.META_DIR) / "entity_glossary.json"
    if not path.exists(): return "<entity_glossary />"

    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r',\s*([\]}])', r'\1', raw)
    try:
        parsed = json.loads(raw)
        return f"<entity_glossary>\n<![CDATA[\n{json.dumps(parsed, indent=2)}\n]]>\n</entity_glossary>"
    except json.JSONDecodeError:
        return f"<entity_glossary>\n<![CDATA[\n{raw}\n]]>\n</entity_glossary>"


async def build_bundle(args: ContextBuildRequest, caller_name: str, lib: ContextLibrary,
                       progress_cb: Callable[[int, str], Awaitable[None]] = None):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    doc = [f'<onm_context_bundle timestamp="{timestamp}">']

    discord_entries = lib.query(source_type="discord_history")
    latest_discord = max((e.date for e in discord_entries), default="Unknown") if discord_entries else "Unknown"

    doc.append("<metadata>")
    doc.append(f"  <profile>{escape_xml(args.profile)}</profile>")
    doc.append("  <parameters>")
    doc.append(f"    <since>{escape_xml(args.since or 'None')}</since>")
    doc.append(f"    <lookback_window_days>30</lookback_window_days>")
    doc.append("  </parameters>")

    stats = []
    content_chunks = []
    step_idx = 0

    if args.discord:
        if progress_cb: await progress_cb(step_idx, "🟦")
        keys = [args.discord] if args.discord != "all" else ["all"]
        discord_content, doc_count = fetch_discord_history(lib, keys, args.since, args.profile)
        if discord_content.strip():
            safe_content, _ = scan_and_redact(discord_content)
            content_chunks.append(f"<discord_channels>\n{safe_content}\n</discord_channels>")
            stats.append(f"    <discord_months>{doc_count}</discord_months>")
        if progress_cb: await progress_cb(step_idx, "🟩")
        step_idx += 1

    if args.transcripts:
        if progress_cb: await progress_cb(step_idx, "🟦")
        transcript_content, count = fetch_transcripts(lib, tags=args.transcripts, since=args.since,
                                                      profile=args.profile)
        if transcript_content.strip():
            safe_content, _ = scan_and_redact(transcript_content)
            content_chunks.append(f"<meeting_transcripts>\n{safe_content}\n</meeting_transcripts>")
            stats.append(f"    <transcripts>{count}</transcripts>")
        if progress_cb: await progress_cb(step_idx, "🟩")
        step_idx += 1

    if args.github:
        if progress_cb: await progress_cb(step_idx, "🟦")
        gh_mode = args.github_mode
        since_dt = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
        gh_content, count = await fetch_github_content(args.github, mode=gh_mode, since_dt=since_dt)
        if gh_content.strip():
            safe_content, _ = scan_and_redact(gh_content)
            content_chunks.append(safe_content)
            stats.append(f"    <github_repos>{count}</github_repos>")
        if progress_cb: await progress_cb(step_idx, "🟩")
        step_idx += 1

    if progress_cb: await progress_cb(step_idx, "🟦")

    doc.append("  <statistics>")
    doc.extend(stats)
    doc.append("  </statistics>")
    doc.append("</metadata>\n")

    doc.append(_get_entity_glossary_xml() + "\n")

    state_map = await _build_active_governance_map()
    doc.append(state_map + "\n")

    doc.append("<operational_data>\n")
    doc.extend(content_chunks)
    doc.append("</operational_data>\n")

    doc.append("</onm_context_bundle>")

    final_str = "\n".join(doc)

    out_dir = os.path.join(config.ARTIFACTS_DIR, "bundles")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_filepath = os.path.join(out_dir, f"onm_context_{ts}.xml")

    with open(out_filepath, "w", encoding="utf-8") as f:
        f.write(final_str)

    size_bytes = os.path.getsize(out_filepath)
    if progress_cb: await progress_cb(step_idx, "🟩")
    return final_str, out_filepath, size_bytes


async def get_or_create_global_bundle(lib: ContextLibrary, force_rebuild: bool = False) -> str:
    cache_path = cache_get("latest_compact_bundle.xml", subdir="bundles")

    if cache_path and not force_rebuild and not is_expired(cache_path, 12 * 3600):
        return cache_path.read_text(encoding="utf-8")

    req = ContextBuildRequest(
        profile="compact",
        discord="all",
        transcripts="all",
        github="all",
        github_mode="docs",
        since=None,
        dry_run=False,
        out=None
    )

    content, _, _ = await build_bundle(req, caller_name="System Cache (Auto-Rebuild)", lib=lib)
    cache_put("latest_compact_bundle.xml", content, subdir="bundles")
    return content