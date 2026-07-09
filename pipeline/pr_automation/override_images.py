import logging
from datetime import datetime, timezone
from pipeline.pr_automation.generate_content import ContentDraft, ImageAsset
from pipeline.pr_automation.fetch_images import download_image, verify_image_bytes, ImageDownloadError
from services.cache import get as cache_get, put as cache_put, invalidate as cache_invalidate

logger = logging.getLogger(__name__)


async def apply_image_override(draft_id: str, candidate_ids: list[str]) -> ContentDraft:
    """Clears existing image assets and forces the download/inclusion of manually specified candidates."""
    draft_file = cache_get(f"{draft_id}.json", subdir="pr_drafts")
    if not draft_file:
        raise ValueError(f"Draft `{draft_id}` not found in cache. It may have expired.")

    draft = ContentDraft.model_validate_json(draft_file.read_text(encoding="utf-8"))

    # Clear old assets from cache
    for asset in draft.image_assets:
        cache_invalidate(f"{draft.issue_ref}_{asset.cache_key}", subdir="pr_drafts")

    draft.image_assets = []

    if len(candidate_ids) == 1 and candidate_ids[0].lower() in ("clear", "none"):
        draft.image_warnings = ["Images manually cleared by reviewer."]
        cache_put(f"{draft_id}.json", draft.model_dump_json(indent=2), subdir="pr_drafts")
        return draft

    draft.image_warnings = ["Manual override applied."]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    roles = ["logo_primary", "logo_dark_variant"]

    for i, cid in enumerate(candidate_ids):
        if i >= len(roles):
            draft.image_warnings.append(f"Ignored extra candidate {cid}: only 2 images (primary/dark) supported.")
            break

        candidate = next((c for c in draft.discovered_candidates if c.candidate_id == cid), None)
        if not candidate:
            draft.image_warnings.append(f"Candidate `{cid}` not found in original discovery list.")
            continue

        role = roles[i]
        try:
            img_bytes, content_type = await download_image(candidate.url)
            verify_image_bytes(img_bytes)
            cache_key = f"{candidate.candidate_id}_manual_{ts}.bin"
            cache_put(f"{draft.issue_ref}_{cache_key}", img_bytes, subdir="pr_drafts")

            # Deduce target path based on existing draft path (Hugo Page Bundle convention)
            base_dir = "/".join(draft.target_path.split("/")[:-1])
            content_type_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
            ext = content_type_map.get(content_type, "png")

            target_filename = f"logo.{ext}" if role == "logo_primary" else f"logo-dark.{ext}"
            target_path = f"{base_dir}/{target_filename}" if base_dir else target_filename

            draft.image_assets.append(ImageAsset(
                target_path=target_path,
                cache_key=cache_key,
                source_url=candidate.url,
                role=role,
                content_type=content_type,
                size_bytes=len(img_bytes)
            ))
        except ImageDownloadError as e:
            logger.warning(f"Failed to fetch/verify overridden image {candidate.url}: {e}")
            draft.image_warnings.append(f"Failed to download `{cid}`: {e}")

    # Save updated draft back to cache
    cache_put(f"{draft_id}.json", draft.model_dump_json(indent=2), subdir="pr_drafts")
    return draft