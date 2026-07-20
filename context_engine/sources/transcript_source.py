from pathlib import Path
from datetime import datetime, timezone, timedelta
import config
from context_engine.library_index import ContextLibrary
from context_engine.formatter import render_text_entry


def fetch_transcripts(library: ContextLibrary, tags: str | None, since: str | None, profile: str = "full") -> tuple[
    str, int]:
    tag_list = tags.split(",") if tags and tags != "all" else None
    matches = library.query(category_tags=tag_list, source_type="meeting_transcript", since=since)
    matches.extend(library.query(category_tags=tag_list, source_type="ec_transcript", since=since))
    if not matches:
        return "", 0

    bundle_content = []
    file_count = 0
    transcripts_dir = Path(config.FATHOM_FMT_DIR)

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    for entry in matches:
        if entry.excluded:
            continue

        use_summary = (profile == "compact") or (profile == "hybrid" and entry.date < cutoff)
        content = None
        title_prefix = "Transcript Summary" if use_summary else "Transcript"

        # 1. Attempt to load summary if requested
        if use_summary and entry.summary_path and Path(entry.summary_path).exists():
            content = Path(entry.summary_path).read_text(encoding="utf-8")
        else:
            # 2. Fallback to source full-text
            file_path = Path(entry.source_path) if entry.source_path else None

            # Legacy fallback: try to find by ID in directory
            if not file_path or not file_path.exists():
                possible_files = list(transcripts_dir.glob(f"*{entry.id.replace('fathom:', '')}*.txt"))
                if possible_files:
                    file_path = possible_files[0]

            if file_path and file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                title_prefix = "Transcript (Full Text)"

        if content:
            metadata = f"**Tags:** {entry.category_tag} · **Date:** {entry.date}"
            if use_summary and title_prefix == "Transcript (Full Text)":
                metadata += " · *Note: Summary was missing, falling back to full text.*"

            bundle_content.append(render_text_entry(f"{title_prefix}: {entry.title}", metadata, content))
            file_count += 1
        else:
            bundle_content.append(f"> ⚠️ Transcript {entry.id} not found on disk.\n")

    return "\n\n".join(bundle_content), file_count