from pathlib import Path
import logging
from services.github import ensure_repo_cache
from pipeline.pr_automation.fetch_issue import IssueContext
from pipeline.pr_automation.fetch_images import ImageCandidate
from models.taxonomies import TaxonomyFile

logger = logging.getLogger(__name__)


async def build_prompt_context(issue: IssueContext, image_candidates: list[ImageCandidate]) -> str:
    repo_path = await ensure_repo_cache(issue.owner, issue.repo)

    context_str = "Below is the context for the GitHub Issue we need to resolve.\n\n"
    context_str += issue.to_prompt_string()

    if image_candidates:
        context_str += "\n--- CANDIDATE IMAGES FOUND IN ISSUE ---\n"
        for c in image_candidates:
            context_str += f"[{c.candidate_id}] url={c.url} alt={c.alt_text!r} location={c.source_location}\n"
            if c.surrounding_text:
                context_str += f"    preceding text: \"...{c.surrounding_text}\"\n"
    else:
        context_str += "\n--- CANDIDATE IMAGES FOUND IN ISSUE ---\n(none found)\n"

    context_str += "\nBelow is structural information about the target repository (Hugo site).\n"

    archetypes_dir = repo_path / "archetypes"
    if archetypes_dir.exists():
        context_str += "\n--- REPOSITORY ARCHETYPES (Hugo Frontmatter Templates) ---\n"
        for md_file in archetypes_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            context_str += f"File: archetypes/{md_file.name}\n```markdown\n{content}\n```\n\n"

    categories_json = repo_path / "data" / "categories.json"
    taxonomies_dir = repo_path / "data" / "taxonomies"

    if categories_json.exists():
        context_str += "\n--- VALID TAXONOMIES (Use these for 'category' fields) ---\n"
        content = categories_json.read_text(encoding="utf-8", errors="ignore")
        try:
            parsed = TaxonomyFile.model_validate_json(content)
            context_str += f"File: data/categories.json\n```json\n{parsed.model_dump_json(indent=2)}\n```\n\n"
        except Exception as e:
            logger.warning(f"Validation error on categories.json: {e}")
            context_str += f"File: data/categories.json\n```json\n{content}\n```\n\n"
    elif taxonomies_dir.exists():
        context_str += "\n--- VALID TAXONOMIES (Use these for 'category' fields) ---\n"
        for json_file in taxonomies_dir.glob("*.json"):
            content = json_file.read_text(encoding="utf-8", errors="ignore")
            try:
                parsed = TaxonomyFile.model_validate_json(content)
                context_str += f"File: data/taxonomies/{json_file.name}\n```json\n{parsed.model_dump_json(indent=2)}\n```\n\n"
            except Exception as e:
                logger.warning(f"Validation error on {json_file.name}: {e}")
                context_str += f"File: data/taxonomies/{json_file.name}\n```json\n{content}\n```\n\n"
    else:
        logger.warning(
            "Neither data/categories.json nor data/taxonomies/ found! PR draft will lack category guardrails.")

    content_dir = repo_path / "content"
    if content_dir.exists():
        context_str += "\n--- CONTENT DIRECTORY STRUCTURE (Directories only) ---\n"
        dirs = [str(p.relative_to(repo_path)) for p in content_dir.rglob("*") if p.is_dir()]
        context_str += "\n".join(dirs[:100])
        context_str += "\n"

    return context_str