import discord
from discord.ext import commands
from discord import app_commands
import json
import re
import logging
import config
from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, ProgressIndicator

from pipeline.pr_automation.fetch_issue import fetch_issue_context
from pipeline.pr_automation.generate_content import generate_draft, ContentDraft
from pipeline.pr_automation.submit_pr import push_draft_to_staging, open_production_pr
from services.cache import get as cache_get, put as cache_put, invalidate as cache_invalidate, list_keys

logger = logging.getLogger(__name__)


class PRAutomationCog(commands.GroupCog, group_name="onm-pr", group_description="GitHub PR Automation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("PRAutomationCog loaded.")

    async def _send_preview_dm(self, interaction: discord.Interaction, draft: ContentDraft, draft_id: str,
                               issue_num: str, preview_url: str, actions_url: str):
        """Helper to format and send the standard preview DM for both /preview and /set-images."""
        preview_msg = f"**Draft Generated & Staged for Issue #{issue_num}**\n"
        preview_msg += f"**Target Path:** `{draft.target_path}`\n"
        preview_msg += f"**PR Title:** {draft.pr_title}\n\n"

        preview_msg += f"🌐 **Live Staging Preview:** <{preview_url}> *(May take 1-2 mins to build)*\n"
        preview_msg += f"⚙️ **Build Progress:** <{actions_url}>\n\n"

        is_core_file = draft.target_path.endswith("_index.md") or draft.target_path == "content/index.md"
        if is_core_file:
            preview_msg += "🚨 **WARNING:** This PR targets a Core Routing/Index file. Review extremely carefully.\n\n"

        preview_msg += "⚠️ **SECURITY WARNING:** This draft was generated from a public GitHub issue.\n"
        preview_msg += "> **You MUST manually check the GitHub diff before running `/onm-pr approve`** to ensure the submitter did not prompt-inject malicious Markdown (e.g. `<script>` tags) into the site.\n\n"

        if draft.image_assets:
            preview_msg += "**🖼️ Images Accepted:**\n"
            for asset in draft.image_assets:
                preview_msg += f"✅ `{asset.role}` → `{asset.target_path}`\n"

        if draft.image_warnings:
            preview_msg += "\n**⚠️ Image Warnings/Notes:**\n"
            for w in draft.image_warnings:
                preview_msg += f"- {w}\n"

        if draft.discovered_candidates and not draft.image_assets:
            preview_msg += "\n**🔍 Discovered Candidates (None Accepted):**\n"
            for c in draft.discovered_candidates:
                preview_msg += f"- `{c.candidate_id}`: <{c.url}>\n"

        preview_msg += f"\n---\n**Next Steps:**\n"
        preview_msg += f"To create the official Pull Request to Production, run:\n`/onm-pr approve draft_id:{draft_id}`\n\n"
        preview_msg += f"To change selected images and update staging, run:\n`/onm-pr set-images draft_id:{draft_id} candidate_ids:img_X`"

        try:
            await interaction.user.send(content=preview_msg)
            await interaction.edit_original_response(
                content="✅ Draft generated and pushed to staging! Links sent to your DMs.")
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="❌ Draft generated and staged successfully, but I couldn't send you the preview link. **Please enable DMs from server members** and run the command again.")

    @app_commands.command(name="preview",
                          description="Generate a draft for an issue, push to staging, and DM you the preview link.")
    @app_commands.describe(issue_num="GitHub issue number on the Prod repository")
    @require_clearance("volunteer_technical")
    async def preview(self, interaction: discord.Interaction, issue_num: int):
        owner = config.PROD_REPO_OWNER
        repo = config.PROD_REPO_NAME
        self.bot.loop.create_task(self._background_preview(interaction, owner, repo, issue_num))

    async def _background_preview(self, interaction: discord.Interaction, owner: str, repo: str, issue_num: int):
        try:
            steps = ["Fetch Issue Context", "Run LLM & Download Media", "Push to Staging"]
            progress = ProgressIndicator(interaction, steps, f"PR Automation: #{issue_num}")
            await progress.update(0, "🟦")

            issue_context = await fetch_issue_context(owner, repo, issue_num)
            await progress.update(0, "🟩")
            await progress.update(1, "🟦")

            draft = await generate_draft(issue_context)
            draft.author_discord_handle = interaction.user.name
            draft_id = f"{draft.issue_ref}_{draft.generated_at}"

            cache_put(f"{draft_id}.json", draft.model_dump_json(indent=2), subdir="pr_drafts")
            cache_put(f"{draft_id}.md", draft.content, subdir="pr_drafts")

            await progress.update(1, "🟩")
            await progress.update(2, "🟦")

            preview_url, actions_url = await push_draft_to_staging(draft)

            await progress.update(2, "🟩")

            await self._send_preview_dm(interaction, draft, draft_id, str(issue_num), preview_url, actions_url)
        except Exception as e:
            await report_error(interaction, e, "Error generating draft")

    @app_commands.command(name="set-images",
                          description="Override AI image selection by manually specifying candidate IDs.")
    @app_commands.describe(draft_id="The ID of the draft",
                           candidate_ids="Comma-separated candidate IDs (e.g. img_1,img_2), or 'clear' to remove images")
    @require_clearance("volunteer_technical")
    async def set_images(self, interaction: discord.Interaction, draft_id: str, candidate_ids: str):
        if not re.match(r'^[\w.-]+$', draft_id):
            return await interaction.response.send_message("❌ Invalid draft ID format.", ephemeral=True)

        c_ids = [c.strip() for c in candidate_ids.split(",") if c.strip()]
        if not c_ids:
            return await interaction.response.send_message("❌ Please provide at least one candidate ID.",
                                                           ephemeral=True)

        await interaction.response.send_message(f"⚙️ Applying manual image override to `{draft_id}`...", ephemeral=True)
        self.bot.loop.create_task(self._background_set_images(interaction, draft_id, c_ids))

    async def _background_set_images(self, interaction: discord.Interaction, draft_id: str, candidate_ids: list[str]):
        try:
            from pipeline.pr_automation.override_images import apply_image_override
            draft = await apply_image_override(draft_id, candidate_ids)

            await interaction.edit_original_response(
                content="🚀 Images overridden! Pushing update to staging environment...")
            preview_url, actions_url = await push_draft_to_staging(draft)

            issue_num = draft.branch_name.split("-")[-1]
            await self._send_preview_dm(interaction, draft, draft_id, issue_num, preview_url, actions_url)
        except ValueError as ve:
            await interaction.edit_original_response(content=f"❌ {ve}")
        except Exception as e:
            await report_error(interaction, e, "Error applying image override")

    @app_commands.command(name="approve",
                          description="Approve a staged draft. Opens a Pull Request to the Production repository.")
    @app_commands.describe(draft_id="The ID of the draft to approve")
    @require_clearance("volunteer_technical")
    async def approve(self, interaction: discord.Interaction, draft_id: str):
        if not re.match(r'^[\w.-]+$', draft_id):
            return await interaction.response.send_message("❌ Invalid draft ID format.", ephemeral=True)
        await interaction.response.send_message(
            f"🚀 Promoting draft `{draft_id}`...\nOpening Cross-Repo PR to Production...", ephemeral=True)
        self.bot.loop.create_task(self._background_approve(interaction, draft_id))

    async def _background_approve(self, interaction: discord.Interaction, draft_id: str):
        try:
            draft_file = cache_get(f"{draft_id}.json", subdir="pr_drafts")
            if not draft_file:
                return await interaction.edit_original_response(content=f"❌ Draft `{draft_id}` not found in cache.")

            draft = ContentDraft.model_validate_json(draft_file.read_text(encoding="utf-8"))

            status_msg = await open_production_pr(draft)
            await interaction.edit_original_response(content=status_msg)

            cache_invalidate(f"{draft_id}.json", subdir="pr_drafts")
            cache_invalidate(f"{draft_id}.md", subdir="pr_drafts")
            for asset in draft.image_assets:
                cache_invalidate(f"{draft.issue_ref}_{asset.cache_key}", subdir="pr_drafts")

        except Exception as e:
            await report_error(interaction, e, "Error submitting PR")

    @app_commands.command(name="status", description="List pending PR drafts currently active on Staging.")
    @require_clearance("volunteer_technical")
    async def status(self, interaction: discord.Interaction):
        try:
            drafts = [k for k in list_keys(subdir="pr_drafts") if k.endswith(".json")]
            if not drafts:
                return await interaction.response.send_message("No pending drafts found.", ephemeral=True)

            msg = "**Pending Staged Drafts:**\n"
            for d in drafts:
                try:
                    draft_path = cache_get(d, subdir="pr_drafts")
                    data = json.loads(draft_path.read_text())
                    msg += f"- ID: `{draft_path.stem}` | Target: `{data.get('target_path', 'unknown')}`\n"
                except Exception as e:
                    continue
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            await report_error(interaction, e, "Error retrieving status")


async def setup(bot: commands.Bot):
    await bot.add_cog(PRAutomationCog(bot))