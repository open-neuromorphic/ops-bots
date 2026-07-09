import os
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Awaitable
import config
from context_engine.library_index import ContextLibrary
from context_engine.sources.github_source import fetch_github_content
from context_engine.sources.transcript_source import fetch_transcripts
from context_engine.sources.discord_source import fetch_discord_history
from context_engine.formatter import scan_and_redact
from models.requests import ContextBuildRequest
from services.cache import get as cache_get, put as cache_put, is_expired


async def build_bundle(args: ContextBuildRequest, caller_name: str, lib: ContextLibrary,
                       progress_cb: Callable[[int, str], Awaitable[None]] = None):
    doc = []
    doc.append("# ONM Context Bundle")
    doc.append("# SYSTEM PROMPT & CONTEXT")
    doc.append("**AI ASSISTANT INSTRUCTIONS:**")
    doc.append("You are analyzing operational context for the Open Neuromorphic (ONM) community.")
    doc.append(
        "Answer questions based on the people, events, and decisions discussed in the transcripts, documents, and chat logs.")
    doc.append(
        "Do not generate code unless explicitly requested. Focus on synthesis, classification, and summarization.\n")

    discord_entries = lib.query(source_type="discord_history")
    latest_discord = max((e.date for e in discord_entries), default="Unknown") if discord_entries else "Unknown"

    doc.append(f"> Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    doc.append(f"> Requested by: {caller_name}")
    doc.append(f"> Flags: Profile: {args.profile} | Since: {args.since}")
    doc.append(f"> Latest Discord Log in Index: {latest_discord}\n")

    content_chunks = []
    summary = []

    step_idx = 0

    if args.discord:
        if progress_cb: await progress_cb(step_idx, "🟦")
        keys = [args.discord] if args.discord != "all" else ["all"]
        discord_content, doc_count = fetch_discord_history(lib, keys, args.since, args.profile)
        if discord_content.strip():
            safe_content, _ = scan_and_redact(discord_content)
            content_chunks.append(safe_content)
            sum_str = "Summarized" if args.profile == 'compact' else (
                "Hybrid" if args.profile == 'hybrid' else "Full Text")
            summary.append(f"- Discord Logs: {doc_count} month(s) included ({sum_str})")
        if progress_cb: await progress_cb(step_idx, "🟩")
        step_idx += 1

    if args.transcripts:
        if progress_cb: await progress_cb(step_idx, "🟦")
        transcript_content, count = fetch_transcripts(lib, tags=args.transcripts, since=args.since,
                                                      profile=args.profile)
        if transcript_content.strip():
            safe_content, _ = scan_and_redact(transcript_content)
            content_chunks.append(safe_content)
            sum_str = "Summarized" if args.profile == 'compact' else (
                "Hybrid" if args.profile == 'hybrid' else "Full Text")
            summary.append(f"- Transcripts: {count} meeting(s) included ({sum_str})")
        if progress_cb: await progress_cb(step_idx, "🟩")
        step_idx += 1

    if args.github:
        if progress_cb: await progress_cb(step_idx, "🟦")
        gh_mode = args.github_mode
        gh_content, count = await fetch_github_content(args.github, mode=gh_mode, since_dt=None)
        if gh_content.strip():
            safe_content, _ = scan_and_redact(gh_content)
            content_chunks.append(safe_content)
            summary.append(f"- GitHub: {count} repo(s) (Mode: {gh_mode})")
        if progress_cb: await progress_cb(step_idx, "🟩")
        step_idx += 1

    if progress_cb: await progress_cb(step_idx, "🟦")

    doc.append("## Contents")
    doc.extend(summary)
    doc.append("\n---\n")
    doc.extend(content_chunks)

    final_str = "\n".join(doc)

    out_dir = os.path.join(config.ARTIFACTS_DIR, "bundles")
    os.makedirs(out_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_filepath = os.path.join(out_dir, f"onm_context_{timestamp}.md")

    with open(out_filepath, "w", encoding="utf-8") as f:
        f.write(final_str)

    size_bytes = os.path.getsize(out_filepath)
    if progress_cb: await progress_cb(step_idx, "🟩")
    return final_str, out_filepath, size_bytes


async def get_or_create_global_bundle(lib: ContextLibrary, force_rebuild: bool = False) -> str:
    cache_path = cache_get("latest_compact_bundle.md", subdir="bundles")

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
    cache_put("latest_compact_bundle.md", content, subdir="bundles")
    return content