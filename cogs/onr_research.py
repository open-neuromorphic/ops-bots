import discord
from discord.ext import commands, tasks
from discord import app_commands
import logging
import urllib.parse
import re
from datetime import datetime, timezone, timedelta

import config
from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, text_to_file

from models.onr import ArxivPaper, ONRState
from pipeline.onr.scraper import fetch_and_filter_new_papers
from pipeline.onr.handoff import generate_engagement_report
from pipeline.onr.orchestrator import (
    onr_stats_store, onr_papers_store,
    post_paper_to_channel, open_active_thread, run_sync_pipeline,
    format_date_with_days_ago, get_license_display, OPEN_ACCESS_POLICY_MSG
)

logger = logging.getLogger(__name__)

ARXIV_ID_REGEX = re.compile(r"^[0-9]{4}\.[0-9]{4,5}(v[0-9]+)?$|^[a-z\-]+(\.[a-zA-Z]+)?/[0-9]{7}(v[0-9]+)?$")


class ManualSubmissionView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Approve & Post", style=discord.ButtonStyle.green, custom_id="onr_manual_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        footer_text = embed.footer.text if embed.footer else ""
        if "ArXiv ID:" not in footer_text:
            return await interaction.response.send_message("❌ Could not extract ArXiv ID from embed.", ephemeral=True)
        arxiv_id = footer_text.split("ArXiv ID: ")[-1].strip()

        state = onr_stats_store.get(arxiv_id)
        if state and state.status != "pending_review":
            return await interaction.response.send_message(
                f"⚠️ This paper has already been processed (Current status: `{state.status}`).", ephemeral=True)

        paper = onr_papers_store.get(arxiv_id)
        if not paper:
            return await interaction.response.send_message("❌ Paper data not found in cache. It may have been purged.",
                                                           ephemeral=True)

        guild = interaction.guild
        channel = discord.utils.get(guild.text_channels, name=config.ONR_RESEARCH_CHANNEL)
        if not channel:
            return await interaction.response.send_message("❌ Target channel not found.", ephemeral=True)

        await post_paper_to_channel(channel, paper)

        for child in self.children: child.disabled = True
        await interaction.response.edit_message(
            content=f"✅ Approved and posted to <#{channel.id}> by {interaction.user.mention}.", view=self)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="onr_manual_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        footer_text = embed.footer.text if embed.footer else ""
        arxiv_id = footer_text.split("ArXiv ID: ")[-1].strip() if "ArXiv ID:" in footer_text else None

        if arxiv_id:
            state = onr_stats_store.get(arxiv_id)
            if state:
                state.status = "rejected"
                onr_stats_store.put(arxiv_id, state)

        for child in self.children: child.disabled = True
        await interaction.response.edit_message(content=f"❌ Rejected by {interaction.user.mention}.", view=self)


class IdentVerificationView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Ping ONM Research Mod Team", style=discord.ButtonStyle.primary,
                       custom_id="onr_ident_ping")
    async def ping_mods(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        rev_channel = discord.utils.get(guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
        if rev_channel:
            await rev_channel.send(
                f"🔔 **Identity Verification Request:**\nUser {interaction.user.mention} (`{interaction.user.name}`) has requested to link their real name/socials "
                f"to their Discord handle for ONR publication credits. Please reach out to them to update the entity glossary."
            )
            await interaction.response.send_message(
                "✅ The mod team has been notified. They will reach out to you shortly!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Error: Reviewers channel not found.", ephemeral=True)


class ONRResearchCog(commands.GroupCog, group_name="onr", group_description="ONR Community Paper Listener"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("ONRResearchCog loaded.")
        self.poll_arxiv_task.start()

    async def cog_load(self):
        self.bot.add_view(ManualSubmissionView(self))
        self.bot.add_view(IdentVerificationView(self))

    def cog_unload(self):
        self.poll_arxiv_task.cancel()

    @tasks.loop(hours=config.ONR_POLL_HOURS)
    async def poll_arxiv_task(self):
        await self.bot.wait_until_ready()
        logger.info(
            f"Starting scheduled arXiv polling & state machine check (Interval: {config.ONR_POLL_HOURS} hours)...")
        await run_sync_pipeline(self.bot)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != "🔥": return
        if payload.user_id == self.bot.user.id: return

        guild = self.bot.get_guild(config.DISCORD_GUILD_ID)
        if not guild: return
        channel = guild.get_channel(payload.channel_id)
        if not channel or channel.name != config.ONR_RESEARCH_CHANNEL: return

        all_states = onr_stats_store.list_all()
        for state in all_states:
            if state.arxiv_id == "latest_paper": continue
            if state.message_id == payload.message_id and state.status == "proposed":
                try:
                    msg = await channel.fetch_message(payload.message_id)
                    fires = next((r.count - 1 for r in msg.reactions if str(r.emoji) == "🔥"), 0)
                    if fires >= config.ONR_THRESHOLD_UPVOTES:
                        paper = onr_papers_store.get(state.arxiv_id)
                        if paper:
                            await open_active_thread(state, msg, paper, fires)
                except Exception as e:
                    logger.debug(f"Error checking reaction against state {state.arxiv_id}: {e}")
                break

    @app_commands.command(name="recent", description="List the most recent open-source papers matching the ONR query.")
    @app_commands.describe(limit="Number of open papers to show (1-10)", ephemeral="Hide from others? (default: True)")
    async def recent_papers(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 10] = 5,
                            ephemeral: bool = True):
        await interaction.response.send_message("🔍 Scanning recent arXiv publications...", ephemeral=ephemeral)
        try:
            papers = await fetch_and_filter_new_papers(query=config.ARXIV_CURRENT_QUERY, max_results=30,
                                                       skip_cached=False, save_to_cache=False)
            open_papers = papers[:limit]
            if not open_papers:
                return await interaction.edit_original_response(content="❌ No recent open-source papers found.")

            embed = discord.Embed(title="Recent Open-Source Papers", color=discord.Color.blue())
            for p in open_papers:
                authors = ", ".join(p.authors[:3]) + (" et al." if len(p.authors) > 3 else "")
                desc = (
                    f"**Authors:** {authors}\n"
                    f"**Published:** {format_date_with_days_ago(p.published_date)}\n"
                    f"**License:** {get_license_display(p.license, p.is_open_license)}\n"
                    f"[View on arXiv]({p.url})"
                )
                if p.pdf_url: desc += f" | [View PDF]({p.pdf_url})"
                embed.add_field(name=p.title, value=desc, inline=False)

            await interaction.edit_original_response(content="✅ Found recent open papers:", embed=embed)
        except Exception as e:
            await report_error(interaction, e, "Failed to retrieve recent papers")

    @app_commands.command(name="sync", description="Manually trigger the arXiv polling and state machine pipeline.")
    @require_clearance("ec_admin", guild_only=True)
    async def sync_arxiv(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message("⚙️ Starting manual ONR sync... This may take a minute.",
                                                    ephemeral=True)
            posted, updated = await run_sync_pipeline(self.bot)
            await interaction.edit_original_response(
                content=f"✅ Sync complete!\n- **{posted}** new papers posted.\n- **{updated}** active states processed."
            )
        except Exception as e:
            await report_error(interaction, e, "Failed to run manual ONR sync")

    @app_commands.command(name="get", description="Test fetching and formatting a paper privately.")
    @app_commands.describe(arxiv_id="Specific arXiv ID (e.g. 2607.00286). Leave blank for latest matching query.")
    async def get_paper(self, interaction: discord.Interaction, arxiv_id: str = None):
        if arxiv_id and not ARXIV_ID_REGEX.match(arxiv_id):
            return await interaction.response.send_message("❌ Invalid ArXiv ID format.", ephemeral=True)

        await interaction.response.send_message("🔍 Fetching paper data from arXiv...", ephemeral=True)
        try:
            from services.arxiv import fetch_arxiv_feed, scrape_paper_license, verify_open_license
            if not arxiv_id:
                paper = onr_stats_store.get(
                    "latest_paper")
                if not paper:
                    papers = await fetch_and_filter_new_papers(query=config.ARXIV_CURRENT_QUERY, max_results=15,
                                                               skip_cached=False, save_to_cache=False)
                    if not papers: return await interaction.edit_original_response(
                        content="❌ No open papers found matching the query.")
                    paper = papers[0]
                    import services.cache as c
                    c.put("latest_paper.json", paper.model_dump_json(indent=2), subdir="researchbot/onr_stats")
            else:
                paper = onr_papers_store.get(arxiv_id)
                if not paper:
                    raw_papers = await fetch_arxiv_feed(id_list=arxiv_id)
                    if not raw_papers: return await interaction.edit_original_response(
                        content="❌ Paper not found on arXiv.")
                    raw = raw_papers[0]
                    scraped_id = raw["arxiv_id"]
                    license_uri = await scrape_paper_license(scraped_id)
                    is_open = verify_open_license(license_uri)
                    paper = ArxivPaper(
                        arxiv_id=scraped_id, title=raw["title"], summary=raw["summary"], authors=raw["authors"],
                        published_date=raw["published_date"], url=raw["url"], pdf_url=raw["pdf_url"],
                        license=license_uri or "unknown", is_open_license=is_open, submitted_by="manual_get"
                    )

            if arxiv_id and not paper.is_open_license:
                from services.arxiv import format_license_uri
                return await interaction.edit_original_response(
                    content=f"{OPEN_ACCESS_POLICY_MSG}\n\n*Detected License:* `{format_license_uri(paper.license)}`"
                )

            embed = discord.Embed(
                title=paper.title, url=paper.url,
                description=f"**Abstract:**\n{paper.summary[:2000]}\n\n*React with {config.ONR_THRESHOLD_UPVOTES} 🔥 to open a {config.ONR_DISCUSSION_HOURS}-hour community discussion thread!*",
                color=discord.Color.teal()
            )
            embed.add_field(name="Authors", value=", ".join(paper.authors[:5]), inline=False)
            embed.add_field(name="Published", value=format_date_with_days_ago(paper.published_date), inline=True)
            embed.add_field(name="License", value=get_license_display(paper.license, paper.is_open_license),
                            inline=True)
            if paper.pdf_url: embed.add_field(name="PDF", value=f"[View PDF]({paper.pdf_url})", inline=True)
            embed.set_footer(text=f"ArXiv ID: {paper.arxiv_id}")
            await interaction.edit_original_response(content="✅ **Paper formatting preview:**", embed=embed)
        except Exception as e:
            await report_error(interaction, e, "Failed to fetch paper for testing")

    @app_commands.command(name="debug",
                          description="View the API query URL being used to poll arXiv and current cache state.")
    async def debug(self, interaction: discord.Interaction):
        encoded_query = urllib.parse.quote(config.ARXIV_CURRENT_QUERY)
        url = f"{config.ARXIV_BASE_URL}?search_query={encoded_query}&{config.ARXIV_CURRENT_FLAGS}&max_results=50"

        from services.cache import list_keys
        papers_in_cache = len(list_keys(subdir="researchbot/onr_papers"))
        stats_in_cache = len(list_keys(subdir="researchbot/onr_stats"))

        msg = (
            f"**ONR Listener Debug**\n**API Target URL:**\n`{url}`\n\n**Query Parameters:**\n"
            f"- `search_query`: `{config.ARXIV_CURRENT_QUERY}`\n- `flags`: `{config.ARXIV_CURRENT_FLAGS}`\n"
            f"- `max_results`: 50 (Polling)\n\n**Cache State:**\n"
            f"- Processed Papers (Open & Closed): `{papers_in_cache}`\n- Active State Trackers: `{stats_in_cache}`\n\n"
            f"[Click here to view raw XML output]({url})"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="submit", description="Manually submit an arXiv URL to the ONR Listener pipeline.")
    @app_commands.describe(arxiv_url="The full arXiv abstract URL")
    async def submit(self, interaction: discord.Interaction, arxiv_url: str):
        try:
            await interaction.response.send_message("🔍 Processing and checking license...", ephemeral=True)
            if "arxiv.org/abs/" not in arxiv_url:
                return await interaction.edit_original_response(
                    content="❌ Please provide a valid `arxiv.org/abs/` URL.")

            arxiv_id = arxiv_url.split("/abs/")[-1].split("v")[0]

            if not ARXIV_ID_REGEX.match(arxiv_id):
                return await interaction.edit_original_response(content="❌ The extracted ArXiv ID is invalid.")

            state = onr_stats_store.get(arxiv_id)

            if state:
                guild_id = config.DISCORD_GUILD_ID
                if state.status in ["pending_review", "rejected"]:
                    chan = discord.utils.get(interaction.guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
                else:
                    chan = discord.utils.get(interaction.guild.text_channels, name=config.ONR_RESEARCH_CHANNEL)

                channel_id = chan.id if chan else 0
                msg_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{state.message_id}"
                thread_link = f"https://discord.com/channels/{guild_id}/{state.thread_id}" if state.thread_id else None

                if state.status == "pending_review":
                    return await interaction.edit_original_response(
                        content=f"⏳ This paper has already been submitted and is currently awaiting QA review here:\n{msg_link}")
                elif state.status == "rejected":
                    return await interaction.edit_original_response(
                        content=f"❌ This paper was previously submitted but was rejected by the QA team.\nQA Thread: {msg_link}")
                elif state.status == "proposed":
                    return await interaction.edit_original_response(
                        content=f"⚠️ This paper has already been approved and is awaiting votes in the community feed here:\n{msg_link}")
                elif state.status == "active_discussion":
                    return await interaction.edit_original_response(
                        content=f"💬 This paper is currently being discussed here:\n{thread_link}")
                elif state.status == "completed":
                    return await interaction.edit_original_response(
                        content=f"✅ This paper was already discussed and logged for the registry. You can read the archived thread here:\n{thread_link}")
                elif state.status == "expired":
                    return await interaction.edit_original_response(
                        content=f"⌛ This paper was previously submitted but did not reach the engagement threshold to open a thread.\nOriginal post: {msg_link}")

            papers = await fetch_and_filter_new_papers(id_list=arxiv_id)
            if not papers:
                paper_data = onr_papers_store.get(arxiv_id)
                if paper_data and not paper_data.is_open_license:
                    from services.arxiv import format_license_uri
                    return await interaction.edit_original_response(
                        content=f"{OPEN_ACCESS_POLICY_MSG}\n\n*Detected License:* `{format_license_uri(paper_data.license)}`"
                    )
                return await interaction.edit_original_response(
                    content="❌ Paper not found on arXiv or failed to process.")

            paper = papers[0]
            paper.submitted_by = interaction.user.name

            guild = interaction.guild
            rev_channel = discord.utils.get(guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
            if not rev_channel:
                return await interaction.edit_original_response(content="❌ Reviewer channel not found.")

            embed = discord.Embed(
                title=f"Manual Submission: {paper.title}", url=paper.url,
                description=f"**Abstract:**\n{paper.summary[:1500]}...\n\n**Submitted by:** {interaction.user.mention}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Authors", value=", ".join(paper.authors[:5]), inline=False)
            embed.add_field(name="License", value=get_license_display(paper.license, paper.is_open_license),
                            inline=True)
            embed.set_footer(text=f"ArXiv ID: {paper.arxiv_id}")

            view = ManualSubmissionView(self)
            qa_msg = await rev_channel.send(content="🚨 **New Manual Paper Submission** requires approval:", embed=embed,
                                            view=view)

            new_state = ONRState(
                arxiv_id=paper.arxiv_id, status="pending_review",
                message_id=qa_msg.id, proposed_at=datetime.now(timezone.utc).isoformat()
            )
            onr_stats_store.put(paper.arxiv_id, new_state)

            await interaction.edit_original_response(
                content=f"✅ Successfully submitted **{paper.title}** to the QA team for review! If approved, it will be posted to the community feed.")
        except Exception as e:
            await report_error(interaction, e, "Failed to submit paper")

    @app_commands.command(name="report", description="Generate an engagement report for tracked ONR papers.")
    @app_commands.describe(days="How many days back to analyze")
    @require_clearance("ec_admin", guild_only=True)
    async def report(self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7):
        try:
            await interaction.response.send_message("📊 Compiling engagement report...", ephemeral=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            all_states = onr_stats_store.list_all()
            active_stats = []
            papers_dict = {}

            for state in all_states:
                if state.arxiv_id == "latest_paper": continue
                dt_str = state.thread_created_at or state.proposed_at
                updated_dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))

                if updated_dt >= cutoff:
                    active_stats.append(state)
                    paper = onr_papers_store.get(state.arxiv_id)
                    if paper:
                        papers_dict[state.arxiv_id] = paper

            report_str = generate_engagement_report(active_stats, papers_dict, days)
            report_file = text_to_file(report_str, f"onr_engagement_{days}d.md")

            await send_report(interaction, "📊 ONR Engagement Report generated:", file_to_send=report_file)
        except Exception as e:
            await report_error(interaction, e, "Failed to generate report")

    @app_commands.command(name="state-list", description="List all active ONR paper states (Admin).")
    @require_clearance("ec_admin", guild_only=True)
    async def state_list(self, interaction: discord.Interaction):
        all_states = onr_stats_store.list_all()
        active_states = [s for s in all_states if s.status in ["pending_review", "proposed",
                                                               "active_discussion"] and s.arxiv_id != "latest_paper"]

        if not active_states:
            return await interaction.response.send_message("No active ONR states found.", ephemeral=True)

        lines = ["**Active ONR Pipeline States:**"]
        for s in sorted(active_states, key=lambda x: x.status):
            lines.append(f"- `{s.arxiv_id}` | Status: **{s.status.upper()}** | 🔥 {s.thumbs_up} | 💬 {s.thread_messages}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="state-rm", description="Remove a paper from the state machine entirely (Admin).")
    @app_commands.describe(arxiv_id="The arXiv ID of the paper to remove")
    @require_clearance("ec_admin", guild_only=True)
    async def state_rm(self, interaction: discord.Interaction, arxiv_id: str):
        if not ARXIV_ID_REGEX.match(arxiv_id):
            return await interaction.response.send_message("❌ Invalid ArXiv ID format.", ephemeral=True)

        try:
            onr_stats_store.delete(arxiv_id)
            onr_papers_store.delete(arxiv_id)
            await interaction.response.send_message(f"✅ Removed state and cache for `{arxiv_id}`.", ephemeral=True)
        except Exception as e:
            await report_error(interaction, e, "Failed to remove state")

    @app_commands.command(name="ident",
                          description="Link your real name or socials to your Discord handle for ONR credits.")
    async def ident(self, interaction: discord.Interaction):
        msg = (
            "**ONR Contributor Identity & Attribution**\n\n"
            "To ensure you receive proper credit as a contributor in our published materials, we maintain a registry mapping Discord handles to real names and/or social profiles (e.g., GitHub, Twitter/X, LinkedIn).\n\n"
            "If you would like to be formally acknowledged in ONR releases, please reach out to the ONM Research Mod team to verify and register your identity.\n\n"
            "Click the button below to ping the mod team and start the process."
        )
        await interaction.response.send_message(msg, view=IdentVerificationView(self), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ONRResearchCog(bot))