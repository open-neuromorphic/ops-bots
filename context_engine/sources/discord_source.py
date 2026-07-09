from pathlib import Path
from datetime import datetime, timezone, timedelta
from context_engine.library_index import ContextLibrary
from context_engine.formatter import render_text_entry


def fetch_discord_history(library: ContextLibrary, tags: list[str], since: str | None, profile: str = "full") -> tuple[
    str, int]:
    tag_list = tags if tags and "all" not in tags else None
    matches = library.query(category_tags=tag_list, source_type="discord_history", since=since)

    if not matches:
        return "", 0

    bundle_content = []
    file_count = 0

    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    for entry in matches:
        if entry.excluded:
            continue

        use_summary = (profile == "compact") or (profile == "hybrid" and entry.date < cutoff)
        content = None
        title_prefix = "Discord Summary" if use_summary else "Discord Log"

        if use_summary and entry.summary_path and Path(entry.summary_path).exists():
            content = Path(entry.summary_path).read_text(encoding="utf-8")
        else:
            file_path = Path(entry.source_path) if entry.source_path else None
            if file_path and file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                title_prefix = "Discord Log (Full Text)"

        if content:
            # Skip empty months to save context tokens
            if "*No messages found for this period.*" in content or "No activity recorded for this period." in content:
                continue

            metadata = f"**Channel:** {entry.category_tag} · **Month:** {entry.date[:7]}"
            if use_summary and title_prefix == "Discord Log (Full Text)":
                metadata += " · *Note: Summary was missing, falling back to full text.*"

            bundle_content.append(render_text_entry(f"{title_prefix}: {entry.title}", metadata, content))
            file_count += 1
        else:
            bundle_content.append(f"> ⚠️ Discord Log {entry.id} not found on disk.\n")

    return "\n\n".join(bundle_content), file_count