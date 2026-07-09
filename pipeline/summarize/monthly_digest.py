import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
import logging

import config
from context_engine.library_index import ContextLibrary
from pipeline.summarize.format_detect import detect_ec_transcript_format, assign_priority_bucket
from services.llm import route_with_retry, TaskType
from models.requests import LLMRequest
from pipeline.ingest.discord_history import fetch_monthly_channel_history
from utils.template import render_template

logger = logging.getLogger(__name__)


class ProposedLedgerUpdate(BaseModel):
    thread_id: str
    status: str
    date: str
    history_note: str


class MonthlyDigestResponse(BaseModel):
    markdown_digest: str = Field(
        description="The formatted Markdown digest summarizing decisions, blockers, and events.")
    proposed_ledger_updates: list[ProposedLedgerUpdate] = Field(default_factory=list,
                                                                description="Any detected progress or changes relating to active organizational threads.")


def _append_to_review_queue(proposed_deltas: list[dict]):
    if not proposed_deltas:
        return
    queue_path = Path(config.META_DIR) / "pending_review.json"
    queue = []
    if queue_path.exists():
        try:
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Could not load review queue: {e}")
    queue.extend(proposed_deltas)
    queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    logger.info(f"Added {len(proposed_deltas)} proposed ledger updates to pending_review.json")


async def run_monthly_digest(source_key: str, month: str, lib: ContextLibrary):
    logger.info(f"Generating monthly digest for {source_key} ({month})...")
    digests_dir = Path(config.DIGESTS_DIR)
    digests_dir.mkdir(parents=True, exist_ok=True)
    raw_content = ""
    format_type = "unknown"

    if source_key in ["ec_transcript", "meeting_transcript"]:
        matches = lib.query(source_type=source_key)
        month_matches = [m for m in matches if m.date.startswith(month) and not m.excluded]
        if not month_matches:
            logger.info(f"No valid transcripts found for {month}.")
            return
        for match in month_matches:
            source_p = Path(match.source_path) if match.source_path else None
            if source_p and source_p.exists():
                text = source_p.read_text(encoding="utf-8")
                format_type = detect_ec_transcript_format(text)
                raw_content += f"## {match.title} ({match.date}) [Format: {format_type}]\n{text}\n\n"
    elif source_key.startswith("discord:"):
        channel_key = source_key.split(":")[1]
        cached_path = await fetch_monthly_channel_history(channel_key, month)
        entry_id = f"discord:{channel_key}:{month}"
        lib.add_or_update(
            entry_id=entry_id, title=f"Discord History: #{channel_key} ({month})",
            date=f"{month}-01", source_type="discord_history",
            category_tag=channel_key, source_path=str(cached_path), audience_tier="ec"
        )
        raw_content = cached_path.read_text(encoding="utf-8")
        format_type = "raw_asr"
        if "*No messages found for this period.*" in raw_content:
            logger.info(f"No Discord messages found in #{channel_key} for {month}. Skipping digest.")
            return
    else:
        logger.warning(f"Unknown source {source_key}. Aborting.")
        return

    priority = assign_priority_bucket(source_key.replace("discord:", ""), format_type)
    task_type = TaskType.STRONG.value if priority == 3 else TaskType.FAST.value

    guide_path = Path(config.META_DIR) / "guide_context.md"
    guide_text = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""

    system_prompt = render_template("prompts/monthly_digest_system.j2", source_key=source_key,
                                    guide_text=guide_text.strip() if guide_text else None)

    req = LLMRequest(
        task_type=task_type,
        prompt=f"Raw Content for {month}:\n\n{raw_content}",
        system=system_prompt,
        max_tokens=8000,
        response_schema=MonthlyDigestResponse.model_json_schema()
    )

    logger.info("Calling LLM Backend...")
    response = await route_with_retry(req)

    try:
        digest_response = MonthlyDigestResponse.model_validate_json(response.content)
    except Exception as e:
        logger.error(f"Failed to parse monthly digest JSON: {e}")
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    frontmatter = f"---\ndate_generated: {now_iso}\nmodel_used: {response.model_used}\ndigest_month: {month}\nsource_key: {source_key}\n---\n\n"
    final_content = frontmatter + digest_response.markdown_digest

    digest_filename = f"{source_key.replace(':', '_')}_{month}.md"
    digest_path = digests_dir / digest_filename
    digest_path.write_text(final_content, encoding="utf-8")

    proposed_deltas = [d.model_dump() for d in digest_response.proposed_ledger_updates]
    if proposed_deltas:
        for delta in proposed_deltas:
            delta["source_run"] = f"digest:{source_key}:{month}"
        _append_to_review_queue(proposed_deltas)

    digest_entry_id = f"digest:{source_key}:{month}"
    lib.add_or_update(
        entry_id=digest_entry_id, title=f"Monthly Digest: {source_key} ({month})",
        date=f"{month}-28", source_type="event_digest",
        category_tag=source_key.replace("discord:", ""),
        source_path=str(digest_path), audience_tier="ec"
    )
    logger.info(f"Digest created and registered: {digest_path}")