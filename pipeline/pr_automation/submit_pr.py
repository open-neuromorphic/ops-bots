import config
import logging
import re
from pipeline.pr_automation.generate_content import ContentDraft
from services.github import push_draft_via_git, create_pr, get_pr_by_branch, update_pr, FileWrite
from services.cache import get as cache_get
import aiohttp

logger = logging.getLogger(__name__)


def calculate_preview_path(target_path: str, content: str) -> str:
    """
    Parses frontmatter to find the type and category of the page.
    Reconstructs the URL path to match Hugo's permalink structures.
    """
    url_path = target_path
    if url_path.startswith("content/"):
        url_path = url_path[8:]

    if url_path.endswith("index.md"):
        url_path = url_path[:-8]
    elif url_path.endswith(".md"):
        url_path = url_path[:-3] + "/"

    content_stripped = content.strip()
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content_stripped, re.DOTALL)
    if not fm_match:
        fm_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL | re.MULTILINE)
        if not fm_match:
            return url_path

    fm_text = fm_match.group(1)

    def get_val(key):
        m = re.search(rf"^{key}\s*:\s*['\"]?([^'\"\n]+)['\"]?", fm_text, re.M)
        return m.group(1).strip() if m else None

    page_type = get_val("type")
    category = get_val("category")
    custom_url = get_val("url")

    parts = [p for p in url_path.split("/") if p]
    name = parts[-1] if parts else "unknown"

    if custom_url:
        return custom_url.strip("/") + "/"

    if page_type == "neuromorphic-software" and category:
        cat_map = {"snn-framework": "snn-frameworks", "data-tool": "data-tools"}
        mapped_cat = cat_map.get(category, category)
        return f"neuromorphic-computing/software/{mapped_cat}/{name}/"
    elif page_type == "neuromorphic-hardware":
        return f"neuromorphic-computing/hardware/{name}/"

    return url_path


async def push_draft_to_staging(draft: ContentDraft) -> tuple[str, str]:
    """Commits and pushes the draft to the staging branch. Returns (preview_url, actions_url)."""
    prod_owner = config.PROD_REPO_OWNER
    prod_repo = config.PROD_REPO_NAME
    staging_owner = config.STAGING_REPO_OWNER
    staging_repo = config.STAGING_REPO_NAME

    commit_msg = f"Add/Update {draft.target_path} (Fixes #{draft.issue_ref.split('-')[-1]})"

    files_to_push = [FileWrite(path=draft.target_path, content=draft.content.encode("utf-8"))]

    for asset in draft.image_assets:
        cached_path = cache_get(f"{draft.issue_ref}_{asset.cache_key}", subdir="pr_drafts")
        if cached_path:
            files_to_push.append(FileWrite(path=asset.target_path, content=cached_path.read_bytes()))

    await push_draft_via_git(
        branch_name=draft.branch_name,
        files=files_to_push,
        commit_msg=commit_msg,
        prod_owner=prod_owner,
        prod_repo=prod_repo,
        staging_owner=staging_owner,
        staging_repo=staging_repo
    )

    url_path = calculate_preview_path(draft.target_path, draft.content)
    preview_url = f"https://{staging_owner}.github.io/{staging_repo}/{url_path}"
    actions_url = f"https://github.com/{staging_owner}/{staging_repo}/actions"

    return preview_url, actions_url


async def open_production_pr(draft: ContentDraft, base_branch: str = "main") -> str:
    """Creates a Pull Request from the staging branch against the production repository."""
    prod_owner = config.PROD_REPO_OWNER
    prod_repo = config.PROD_REPO_NAME
    staging_owner = config.STAGING_REPO_OWNER
    staging_repo = config.STAGING_REPO_NAME

    head_ref = f"{staging_owner}:{draft.branch_name}"

    url_path = calculate_preview_path(draft.target_path, draft.content)
    preview_url = f"https://{staging_owner}.github.io/{staging_repo}/{url_path}"

    author = draft.author_discord_handle
    if not author or author == "Unknown":
        author = "CLI Maintenance Tool"

    rich_pr_body = f"🤖 **Automated PR drafted via Discord** by `@{author}`\n\n"
    rich_pr_body += f"🌐 **Staging Preview:** [View Live Page]({preview_url})\n"
    rich_pr_body += f"*(Note: The staging preview points to the bot's shared staging environment. If another PR is drafted after this one, the preview link may reflect newer changes until this PR is merged.)*\n\n"
    rich_pr_body += "---\n\n"
    rich_pr_body += f"{draft.pr_body}\n"

    try:
        pr_response = await create_pr(
            owner=prod_owner, repo=prod_repo, title=draft.pr_title,
            body=rich_pr_body, head=head_ref, base=base_branch
        )
        msg = f"🎉 **Pull Request Created!**\n"
        msg += f"**PR Link:** {pr_response.get('html_url')}\n"
        return msg

    except aiohttp.ClientResponseError as e:
        if e.status == 422:
            try:
                existing_pr = await get_pr_by_branch(prod_owner, prod_repo, head_ref)
                if existing_pr:
                    await update_pr(prod_owner, prod_repo, existing_pr["number"], draft.pr_title, rich_pr_body)
                    return f"✅ **Pull Request Updated!**\nAn open PR already exists for this branch. Its body has been updated."
            except Exception as update_err:
                logger.warning(f"Failed to patch existing PR body: {update_err}")

            return f"✅ **Branch Updated!**\nAn open PR already exists for this branch. The staging branch was successfully force-pushed with your new changes."

        return f"❌ **Failed to open PR:** GitHub API rejected the cross-repo PR (Status {e.status}). You can view the branch here: https://github.com/{staging_owner}/{staging_repo}/tree/{draft.branch_name}"