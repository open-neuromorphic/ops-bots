import sys
import os
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from context_engine.library_index import ContextLibrary
from services.cache import is_stale, hash_of

def sync_all_sources() -> tuple[int, int, str]:
    logs = []
    def log(msg):
        print(msg)
        logs.append(msg)

    log(">>> Unified Library Source Sync <<<")
    lib = ContextLibrary()
    updated_count = 0
    skipped_count = 0

    ec_dir = Path(config.EC_MEETINGS_DIR)
    log("\nScanning EC Meetings...")
    if ec_dir.exists():
        for txt_file in ec_dir.glob("*.txt"):
            date_str = txt_file.stem
            entry_id = f"ec:{date_str}"

            existing = lib.get(entry_id)
            if existing and not is_stale(existing, txt_file):
                skipped_count += 1
                continue

            lib.add_or_update(
                entry_id=entry_id,
                title=f"EC Meeting Notes ({date_str})",
                date=date_str,
                source_type="ec_transcript",
                category_tag="ec-meeting",
                source_path=str(txt_file),
                content_hash=hash_of(txt_file),
                audience_tier="ec"
            )
            updated_count += 1
            log(f"  + Added/Updated: {entry_id}")

    fathom_raw = Path(config.FATHOM_RAW_DIR)
    fathom_fmt = Path(config.FATHOM_FMT_DIR)
    log("\nScanning Fathom Transcripts...")
    if fathom_raw.exists():
        for json_file in fathom_raw.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                meta = data.get("meeting_metadata", {})

                rec_id = str(meta.get("recording_id", json_file.stem))
                title = meta.get("title", f"Meeting {rec_id}")
                date_str = meta.get("created_at", "1970-01-01").split("T")[0]

                entry_id = f"fathom:{rec_id}"
                is_excluded = rec_id in config.FATHOM_EXCLUDED_RECORDING_IDS

                txt_files = list(fathom_fmt.glob(f"*{rec_id}*.txt"))
                source_path = str(txt_files[0]) if txt_files else None

                if not source_path:
                    continue

                source_p = Path(source_path)
                existing = lib.get(entry_id)

                if existing and not is_stale(existing, source_p):
                    if existing.excluded != is_excluded:
                        lib.add_or_update(entry_id, excluded=is_excluded,
                                          exclusion_reason="Legacy config exclusion" if is_excluded else None)
                        updated_count += 1
                        log(f"  ~ Updated Exclusion: {entry_id} -> {is_excluded}")
                    else:
                        skipped_count += 1
                    continue

                lib.add_or_update(
                    entry_id=entry_id,
                    title=title,
                    date=date_str,
                    source_type="meeting_transcript",
                    category_tag="uncategorized",
                    source_path=source_path,
                    content_hash=hash_of(source_p),
                    excluded=is_excluded,
                    exclusion_reason="Legacy config exclusion" if is_excluded else None,
                    audience_tier="ec"
                )
                updated_count += 1
                log(f"  + Added/Updated: {entry_id}")
            except Exception as e:
                log(f"  ⚠️ Error processing {json_file.name}: {e}")

    discord_dir = Path(config.DISCORD_LOGS_DIR)
    log("\nScanning Discord History Caches...")
    if discord_dir.exists():
        for channel_dir in discord_dir.iterdir():
            if not channel_dir.is_dir(): continue
            channel_key = channel_dir.name

            for txt_file in channel_dir.glob("*.txt"):
                month_str = txt_file.stem
                entry_id = f"discord:{channel_key}:{month_str}"

                existing = lib.get(entry_id)
                if existing and not is_stale(existing, txt_file):
                    skipped_count += 1
                    continue

                lib.add_or_update(
                    entry_id=entry_id,
                    title=f"Discord History: #{channel_key} ({month_str})",
                    date=f"{month_str}-01",
                    source_type="discord_history",
                    category_tag=channel_key,
                    source_path=str(txt_file),
                    content_hash=hash_of(txt_file),
                    audience_tier="ec"
                )
                updated_count += 1
                log(f"  + Added/Updated: {entry_id}")

    log(f"\n✅ Sync Complete. Updated {updated_count} files, skipped {skipped_count} unchanged files.")
    return updated_count, skipped_count, "\n".join(logs)