import json
import logging
import base64
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from services.llm import route_with_retry, TaskType
from models.requests import LLMRequest
from pipeline.pr_automation.fetch_issue import IssueContext
from pipeline.pr_automation.build_context import build_prompt_context
from pipeline.pr_automation.fetch_images import extract_image_candidates, download_image, verify_image_bytes, \
    ImageDownloadError, ImageCandidate
from utils.template import render_template
from services.cache import put as cache_put

logger = logging.getLogger(__name__)


class ImageDecision(BaseModel):
    candidate_id: str
    role: str
    confidence: str
    reasoning: str
    target_path: str | None = None


class PRDraftResponse(BaseModel):
    target_path: str = Field(
        description="The relative file path in the repo to create or update. For new content, this MUST be a Hugo Page Bundle path ending in /index.md (e.g., content/neuromorphic-computing/software/my-tool/index.md).")
    pr_title: str = Field(description="A descriptive title for the Pull Request.")
    pr_body: str = Field(description="A short description for the PR body, mentioning Fixes #ISSUE_NUMBER.")
    image_decisions: list[ImageDecision] = Field(default_factory=list,
                                                 description="Classification logic for any candidate images.")
    markdown_content: str = Field(
        description="The FULL raw markdown content for the file, including the YAML frontmatter block.")


class ImageAsset(BaseModel):
    target_path: str
    cache_key: str
    source_url: str
    role: str
    content_type: str
    size_bytes: int


class ContentDraft(BaseModel):
    issue_ref: str
    target_path: str
    content: str
    branch_name: str
    pr_title: str
    pr_body: str
    generated_at: str
    model_used: str
    image_assets: list[ImageAsset] = []
    image_warnings: list[str] = []
    discovered_candidates: list[ImageCandidate] = []
    author_discord_handle: str = "Unknown"


async def generate_draft(issue: IssueContext) -> ContentDraft:
    # 1. Extract candidates
    raw_image_candidates = extract_image_candidates(issue)

    # 2. Phase 3: Pre-fetch images to pass actual vision bytes to the LLM
    valid_candidates = []
    multimodal_data = []
    prefetched_images = {}  # Map candidate_id -> (bytes, content_type)
    image_warnings = []

    for candidate in raw_image_candidates:
        try:
            img_bytes, content_type = await download_image(candidate.url)
            verify_image_bytes(img_bytes)

            b64_data = base64.b64encode(img_bytes).decode("utf-8")
            multimodal_data.append({"mime_type": content_type, "data": b64_data})

            valid_candidates.append(candidate)
            prefetched_images[candidate.candidate_id] = (img_bytes, content_type)
        except ImageDownloadError as e:
            logger.warning(f"Skipping vision pre-fetch for {candidate.candidate_id}: {e}")
            image_warnings.append(f"Could not load `{candidate.candidate_id}` for vision check: {e}")

    # 3. Build Prompt (Only passing the candidates that successfully downloaded so text/images align perfectly)
    prompt_context = await build_prompt_context(issue, valid_candidates)

    if valid_candidates:
        prompt_context += "\nNOTE: The images attached to this prompt correspond exactly, in order, to the candidate IDs listed above."

    system_prompt = render_template("prompts/pr_generate.j2")

    req = LLMRequest(
        task_type=TaskType.STRONG.value,
        prompt=prompt_context,
        system=system_prompt,
        response_schema=PRDraftResponse.model_json_schema(),
        multimodal_data=multimodal_data if multimodal_data else None
    )

    response = await route_with_retry(req, max_attempts=4)

    try:
        draft_response = PRDraftResponse.model_validate_json(response.content)

        # Enforce content/ prefix
        if not draft_response.target_path.startswith("content/"):
            clean_path = draft_response.target_path.lstrip("/")
            draft_response.target_path = f"content/{clean_path}"

        # Enforce Hugo Page Bundle format
        if not draft_response.target_path.endswith(".md"):
            if not draft_response.target_path.endswith("/"):
                draft_response.target_path += "/"
            draft_response.target_path += "index.md"
        elif draft_response.target_path.endswith(".md") and not draft_response.target_path.endswith(
                "index.md") and not draft_response.target_path.endswith("_index.md"):
            base = draft_response.target_path[:-3]
            draft_response.target_path = f"{base}/index.md"

    except Exception as e:
        raise ValueError(f"Failed to parse LLM structured output: {e}\nRaw output:\n{response.content[:500]}...")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    draft_id = f"{issue.owner}-{issue.repo}-{issue.number}"

    image_assets = []

    accepted_candidates = [d for d in draft_response.image_decisions if
                           d.role in ("logo_primary", "logo_dark_variant") and d.confidence in ("high", "medium")]
    seen_roles = set()
    filtered_candidates = []

    for decision in accepted_candidates:
        if decision.role not in seen_roles:
            filtered_candidates.append(decision)
            seen_roles.add(decision.role)
        else:
            image_warnings.append(f"Ignored duplicate {decision.role} designation for {decision.candidate_id}.")

    for decision in draft_response.image_decisions:
        if decision.confidence == "low" or decision.role == "unclear":
            image_warnings.append(
                f"Image {decision.candidate_id} was marked unclear/low confidence by vision model. Requires human review.")

    # 4. Cache accepted images using the pre-fetched bytes (No double-downloading)
    candidate_dict = {c.candidate_id: c for c in valid_candidates}
    for decision in filtered_candidates:
        candidate = candidate_dict.get(decision.candidate_id)
        if not candidate or candidate.candidate_id not in prefetched_images:
            continue

        img_bytes, content_type = prefetched_images[candidate.candidate_id]
        cache_key = f"{decision.candidate_id}_{ts}.bin"
        cache_put(f"{draft_id}_{cache_key}", img_bytes, subdir="pr_drafts")

        image_assets.append(ImageAsset(
            target_path=decision.target_path or f"content/{decision.candidate_id}.png",
            cache_key=cache_key,
            source_url=candidate.url, role=decision.role, content_type=content_type, size_bytes=len(img_bytes)
        ))

    return ContentDraft(
        issue_ref=draft_id,
        target_path=draft_response.target_path,
        content=draft_response.markdown_content,
        branch_name=f"bot/issue-{issue.number}",
        pr_title=draft_response.pr_title,
        pr_body=draft_response.pr_body,
        generated_at=ts,
        model_used=response.model_used,
        image_assets=image_assets,
        image_warnings=image_warnings,
        discovered_candidates=valid_candidates,
    )