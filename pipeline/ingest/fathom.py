import asyncio
import json
import re
import logging
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import config

logger = logging.getLogger(__name__)

class FathomApiClient:
    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url
    def get_all_meetings(self):
        raise NotImplementedError("Fathom API integration is currently stubbed. Meeting ingestion cannot proceed.")
    def get_transcript(self, recording_id):
        raise NotImplementedError("Fathom API integration is currently stubbed.")

class TranscriptEntry(BaseModel):
    recording_id: str
    title: str
    date: str
    cache_path: Path
    formatted_path: Optional[Path] = None

def _sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '-', name).replace("\n", " ").strip().replace(" ", "_")

async def fetch_all() -> list[TranscriptEntry]:
    if not config.FATHOM_API_KEY:
        raise ValueError("FATHOM_API_KEY is not set.")

    raw_dir = Path(config.FATHOM_RAW_DIR)
    raw_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_sync():
        client = FathomApiClient(api_key=config.FATHOM_API_KEY, base_url=config.FATHOM_BASE_URL)
        all_meetings = client.get_all_meetings()
        entries = []

        for meeting in all_meetings:
            recording_id = str(meeting.get('recording_id'))
            if not recording_id or recording_id in config.FATHOM_EXCLUDED_RECORDING_IDS:
                continue

            title = meeting.get('title', f"Meeting_{recording_id}")
            date_str = meeting.get("created_at", "1970-01-01").split("T")[0]
            cache_filepath = raw_dir / f"{recording_id}.json"

            if not cache_filepath.exists():
                transcript_data = client.get_transcript(recording_id)
                output_data = {"meeting_metadata": meeting, "transcript_data": transcript_data}
                with open(cache_filepath, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, indent=2, ensure_ascii=False)

            formatted_path = Path(config.FATHOM_FMT_DIR) / f"{date_str}_{_sanitize(title)}_{recording_id}.txt"

            entries.append(TranscriptEntry(
                recording_id=recording_id,
                title=title,
                date=date_str,
                cache_path=cache_filepath,
                formatted_path=formatted_path if formatted_path.exists() else None
            ))
        return entries
    return await asyncio.to_thread(_fetch_sync)

async def format_transcript(entry: TranscriptEntry) -> Path:
    def _format_sync():
        with open(entry.cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        metadata = data.get("meeting_metadata", {})
        transcript_items = data.get("transcript_data", {}).get("transcript", [])
        out_dir = Path(config.FATHOM_FMT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)

        date_str = metadata.get("created_at", "nodate").split("T")[0]
        title_str = metadata.get("title", f"Meeting_{entry.recording_id}")
        out_path = out_dir / f"{date_str}_{_sanitize(title_str)}_{entry.recording_id}.txt"

        with open(out_path, 'w', encoding='utf-8') as out_f:
            out_f.write(f"--- MEETING METADATA ---\nTitle: {title_str}\nDate: {metadata.get('created_at')}\nRecording ID: {entry.recording_id}\nFathom URL: {metadata.get('url')}\n--------------------------\n\n")
            current_speaker = None
            accumulated = []
            for item in transcript_items:
                speaker_name = item.get("speaker", {}).get("display_name", "Unknown Speaker")
                text = item.get("text", "").strip()
                if not text: continue
                if speaker_name != current_speaker:
                    if current_speaker and accumulated:
                        out_f.write(f"{current_speaker}: {' '.join(accumulated)}\n\n")
                    current_speaker = speaker_name
                    accumulated = [text]
                else:
                    accumulated.append(text)
            if current_speaker and accumulated:
                out_f.write(f"{current_speaker}: {' '.join(accumulated)}\n\n")
        return out_path
    return await asyncio.to_thread(_format_sync)

async def main():
    try:
        entries = await fetch_all()
        for e in entries:
            if not e.formatted_path:
                logger.info(f"Formatting {e.recording_id}...")
                await format_transcript(e)
        logger.info(f"Processed {len(entries)} transcripts successfully.")
    except Exception as ex:
        logger.error(f"Error processing transcripts: {ex}")

if __name__ == "__main__":
    asyncio.run(main())