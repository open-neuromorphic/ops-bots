from pathlib import Path
from datetime import datetime, timezone, timedelta
import re
from context_engine.library_index import ContextLibrary
from context_engine.formatter import escape_xml, cdata_wrap, normalize_crlf


def fetch_transcripts(library: ContextLibrary, tags: str | None, since: str | None, profile: str = "full") -> tuple[
    str, int]:
    tag_list = tags.split(",") if tags and tags != "all" else None
    matches = library.query(category_tags=tag_list, source_type="meeting_transcript", since=since)
    matches.extend(library.query(category_tags=tag_list, source_type="ec_transcript", since=since))
    if not matches: return "", 0

    bundle_content = []
    file_count = 0
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    for entry in matches:
        if entry.excluded: continue
        use_summary = (profile == "compact") or (profile == "hybrid" and entry.date < cutoff)

        content = None
        series_slug = escape_xml(entry.category_tag)
        urn_date = escape_xml(entry.date)
        transcript_id = f"transcript:{series_slug}:{urn_date}"

        if use_summary and entry.summary_path and Path(entry.summary_path).exists():
            content = normalize_crlf(Path(entry.summary_path).read_text(encoding="utf-8"))
            bundle_content.append(
                f'<transcript id="{transcript_id}">\n  <summary>{cdata_wrap(content)}</summary>\n</transcript>')
            file_count += 1
        else:
            file_path = Path(entry.source_path) if entry.source_path else None

            if not file_path or not file_path.exists():
                from config import FATHOM_FMT_DIR
                possible_files = list(Path(FATHOM_FMT_DIR).glob(f"*{entry.id.replace('fathom:', '')}*.txt"))
                if possible_files: file_path = possible_files[0]

            if file_path and file_path.exists():
                content = normalize_crlf(file_path.read_text(encoding="utf-8"))
                bundle_content.append(f'<transcript id="{transcript_id}">')

                parts = re.split(r'\n(?=[A-Za-z0-9 _]+:\s)', "\n" + content.strip())
                parsed_any = False
                for p in parts:
                    p = p.strip()
                    if not p or p.startswith("--- MEETING METADATA"): continue
                    m = re.match(r"^([A-Za-z0-9 _]+):\s*(.*)", p, re.DOTALL)
                    if m:
                        speaker, text = m.groups()
                        bundle_content.append(
                            f'  <message user="{escape_xml(speaker)}">{cdata_wrap(text.strip())}</message>')
                        parsed_any = True

                if not parsed_any:
                    bundle_content.append(f'  <raw_log>{cdata_wrap(content)}</raw_log>')
                bundle_content.append(f'</transcript>')
                file_count += 1

    return "\n".join(bundle_content), file_count