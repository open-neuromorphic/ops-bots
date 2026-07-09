import asyncio
from pathlib import Path
from datetime import datetime, timezone
import logging
from pydantic import BaseModel, Field
import config
from services.llm import route_with_retry, LLMRequest, TaskType
from services.cache import is_stale, hash_of
from context_engine.library_index import ContextLibrary
from utils.template import render_template

logger = logging.getLogger(__name__)

class TranscriptSummaryResponse(BaseModel):
    markdown_summary: str = Field(description="The factual, objective Markdown summary containing decisions, blockers, friction points/events, and thread deltas.")


async def summarize_stale_transcripts(lib: ContextLibrary, force: bool = False) -> int:
    transcripts = lib.query(source_type="meeting_transcript") + lib.query(source_type="ec_transcript") + lib.query(source_type="discord_history")

    meta_dir = Path(config.META_DIR)
    guide_path = meta_dir / "guide_context.md"
    guide_text = guide_path.read_text(encoding='utf-8') if guide_path.exists() else None

    summaries_dir = Path(config.SUMMARIES_DIR)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    summarized_count = 0

    for entry in transcripts:
        if entry.excluded or not entry.source_path:
            continue

        source_p = Path(entry.source_path)
        if not source_p.exists():
            continue

        if not force and not is_stale(entry, source_p) and entry.summary_path and Path(entry.summary_path).exists():
            continue

        logger.info(f"Summarizing: {entry.title} ({entry.date})")
        source_text = source_p.read_text(encoding="utf-8")
        source_bytes = len(source_text.encode("utf-8"))
        now_iso = datetime.now(timezone.utc).isoformat()

        if source_bytes < 5000:
            logger.info(f"  -> Bypassing LLM (Size: {source_bytes} bytes). Using raw logs.")
            model_used = "bypass (low-volume raw log)"
            if "*No messages found for this period.*" in source_text:
                response_content = "> **Note:** No activity recorded for this period."
            else:
                response_content = (
                    "> **Note:** Insufficient activity to warrant AI summarization "
                    "(volume below 5KB threshold). Direct logs included below.\n\n"
                    f"```text\n{source_text.strip()}\n```\n"
                )
        else:
            is_discord = entry.source_type == "discord_history"
            system_prompt = render_template(
                "prompts/transcript_summary.j2",
                is_discord=is_discord,
                confidentiality_note=entry.confidentiality_note,
                guide_text=guide_text.strip() if guide_text else None
            )

            req = LLMRequest(
                task_type=TaskType.STRONG.value,
                prompt=f"Title: {entry.title}\nDate: {entry.date}\n\n{source_text}",
                system=system_prompt,
                response_schema=TranscriptSummaryResponse.model_json_schema()
            )

            response = await route_with_retry(req)
            model_used = response.model_used
            try:
                response_content = TranscriptSummaryResponse.model_validate_json(response.content).markdown_summary
            except Exception as e:
                logger.error(f"Failed to parse TranscriptSummaryResponse JSON: {e}")
                response_content = response.content

        frontmatter = (
            f"---\n"
            f"date_generated: {now_iso}\n"
            f"model_used: {model_used}\n"
            f"source_id: {entry.id}\n"
            f"source_date: {entry.date}\n"
            f"---\n\n"
        )
        final_content = frontmatter + response_content
        summary_filename = f"summary_{entry.id.replace(':', '_')}.md"
        summary_p = summaries_dir / summary_filename
        summary_p.write_text(final_content, encoding="utf-8")

        lib.add_or_update(
            entry.id,
            summary_path=str(summary_p),
            summary_date=now_iso,
            summary_model=model_used,
            content_hash=hash_of(source_p)
        )
        summarized_count += 1

    return summarized_count