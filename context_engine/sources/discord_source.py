from pathlib import Path
from datetime import datetime, timezone, timedelta
import re
from context_engine.library_index import ContextLibrary
from context_engine.formatter import escape_xml, cdata_wrap, normalize_crlf


def fetch_discord_history(library: ContextLibrary, tags: list[str], since: str | None, profile: str = "full") -> tuple[
    str, int]:
    tag_list = tags if tags and "all" not in tags else None
    matches = library.query(category_tags=tag_list, source_type="discord_history", since=since)
    if not matches: return "", 0

    bundle_content = []
    file_count = 0
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    for entry in matches:
        if entry.excluded: continue
        use_summary = (profile == "compact") or (profile == "hybrid" and entry.date < cutoff)

        content = None
        if use_summary and entry.summary_path and Path(entry.summary_path).exists():
            content = Path(entry.summary_path).read_text(encoding="utf-8")
            content = normalize_crlf(content)

            bundle_content.append(
                f'<channel id="discord:{escape_xml(entry.category_tag)}:{escape_xml(entry.date[:7])}">')
            bundle_content.append(f'  <summary>{cdata_wrap(content)}</summary>')
            bundle_content.append(f'</channel>')
            file_count += 1
        else:
            file_path = Path(entry.source_path) if entry.source_path else None
            if file_path and file_path.exists():
                raw_content = file_path.read_text(encoding="utf-8")
                raw_content = normalize_crlf(raw_content)

                bundle_content.append(
                    f'<channel id="discord:{escape_xml(entry.category_tag)}:{escape_xml(entry.date[:7])}">')

                parts = re.split(r'\n(?=\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] )', "\n" + raw_content.strip())
                parsed_any = False

                for p in parts:
                    p = p.strip()
                    if not p: continue
                    if p.startswith("--- DISCORD LOG"): continue

                    m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] ([^:]+):\s*(.*)", p, re.DOTALL)
                    if m:
                        ts, author, text = m.groups()
                        bundle_content.append(
                            f'  <message timestamp="{escape_xml(ts.replace(" ", "T"))}Z" user="{escape_xml(author)}">{cdata_wrap(text.strip())}</message>')
                        parsed_any = True

                if not parsed_any:
                    bundle_content.append(f'  <raw_log>{cdata_wrap(raw_content)}</raw_log>')

                bundle_content.append(f'</channel>')
                file_count += 1

    return "\n".join(bundle_content), file_count