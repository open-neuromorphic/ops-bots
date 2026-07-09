import asyncio
import json
from pathlib import Path
import logging
from pydantic import BaseModel, Field
import config
from services.llm import route_with_retry, LLMRequest, TaskType
from context_engine.library_index import ContextLibrary
from utils.template import render_template

logger = logging.getLogger(__name__)

class GuideResponse(BaseModel):
    guide_context: str = Field(description="The dense, bulleted contextual guide in Markdown format.")

async def build_guide_context(lib: ContextLibrary) -> Path:
    meta_dir = Path(config.META_DIR)
    meta_dir.mkdir(parents=True, exist_ok=True)

    standing_state = ""
    glossary_path = meta_dir / "entity_glossary.json"
    if glossary_path.exists():
        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                standing_state += "--- ENTITY GLOSSARY ---\n" + json.dumps(data, indent=2) + "\n\n"
                logger.info(f"Loaded Glossary: {len(data.keys()) - 1} persons, {len(data.get('known_non_persons', {}))} non-persons.")
        except Exception as e:
            logger.warning(f"Failed to load glossary: {e}")

    ledger_path = meta_dir / "threads_ledger.json"
    if ledger_path.exists():
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                standing_state += "--- ACTIVE THREADS LEDGER ---\n" + json.dumps(data, indent=2) + "\n\n"
                logger.info(f"Loaded Threads Ledger: {len(data.keys())} active organizational threads.")
        except Exception as e:
            logger.warning(f"Failed to load threads ledger: {e}")

    recent_transcripts = lib.query(source_type="meeting_transcript")[:5]
    sample_text = standing_state

    logger.info("Loading 5 most recent transcripts for current operational context...")
    for entry in recent_transcripts:
        if entry.excluded: continue
        source_p = Path(entry.source_path) if entry.source_path else None
        if source_p and source_p.exists():
            sample_text += f"Title: {entry.title}\nDate: {entry.date}\n{source_p.read_text(encoding='utf-8')[:3000]}\n\n"

    system_prompt = render_template("prompts/guide_generate.j2")

    logger.info(f"Prompt prepared ({len(sample_text)} characters). Calling LLM Backend...")
    req = LLMRequest(
        task_type=TaskType.STRONG.value,
        prompt=f"Analyze these recent meeting excerpts and state ledgers to extract the guide:\n\n{sample_text}",
        system=system_prompt,
        response_schema=GuideResponse.model_json_schema()
    )

    response = await route_with_retry(req)

    try:
        final_content = GuideResponse.model_validate_json(response.content).guide_context
    except Exception as e:
        logger.error(f"Failed to parse GuideResponse JSON: {e}")
        final_content = response.content

    guide_path = meta_dir / "guide_context.md"
    guide_path.write_text(final_content, encoding="utf-8")
    return guide_path


if __name__ == "__main__":
    lib_instance = ContextLibrary()
    path = asyncio.run(build_guide_context(lib_instance))
    print(f"✅ Guide context built and cached at {path}")