import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
from datetime import datetime
import logging

import config
from context_engine.library_index import ContextLibrary
from context_engine.builder import build_bundle
from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, text_to_file, ProgressIndicator
from models.meta import load_threads_ledger, load_entity_glossary, EntityEntry
from models.requests import ContextBuildRequest

logger = logging.getLogger(__name__)


class ContextEngineCog(commands.GroupCog, group_name="onm-context", group_description="AI Context Engine"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lib = ContextLibrary()
        logger.info("ContextEngineCog loaded as onm-context group.")

    @app_commands.command(name="build", description="Build an AI Context Bundle from all configured sources.")
    @app_commands.describe(since="Lookback period (e.g., 30d or 2026-05-01)", deliver="How to deliver the bundle",
                           profile="Profile dictates bundle size ('compact' uses LLM summaries instead of full text)")
    @app_commands.choices(deliver=[
        app_commands.Choice(name="DM Me (Default)", value="dm"),
        app_commands.Choice(name="Save to Host Disk Only", value="save-only")
    ], profile=[
        app_commands.Choice(name="Full Text (Huge Context)", value="full"),
        app_commands.Choice(name="Compact (Summarized)", value="compact"),
        app_commands.Choice(name="Hybrid (Recent Full, Older Summarized)", value="hybrid")
    ])
    @require_clearance("ec_admin", guild_only=False)
    async def build(self, interaction: discord.Interaction, since: str = None, deliver: str = "dm",
                    profile: str = "full"):
        try:
            req = ContextBuildRequest(profile=profile, since=since)
            self.bot.loop.create_task(self._background_build(interaction, req, deliver))
        except Exception as e:
            await report_error(interaction, e, "Error triggering bundle build")

    async def _background_build(self, interaction: discord.Interaction, req: ContextBuildRequest, deliver: str):
        try:
            steps = []
            if req.discord: steps.append("Fetch Discord Logs")
            if req.transcripts: steps.append("Fetch Transcripts")
            if req.github: steps.append("Fetch GitHub Content")
            steps.append("Compile Bundle")

            progress = ProgressIndicator(interaction, steps, "Building Context Bundle...")
            await progress.update(0, "⬛")

            doc_str, filepath, size_bytes = await build_bundle(
                args=req,
                caller_name=f"@{interaction.user.name}",
                lib=self.lib,
                progress_cb=progress.update
            )
            size_kb = size_bytes / 1024

            if deliver == "save-only":
                msg = f"✅ Context bundle saved securely to host at:\n`{filepath}`\nSize: {size_kb:.1f} KB"
                await interaction.edit_original_response(content=msg)
            else:
                await interaction.edit_original_response(
                    content=f"✅ Bundle built! ({size_kb:.1f} KB). Uploading to DMs...")
                file = discord.File(filepath)
                await interaction.user.send(content="Here is your Context Engine Bundle:", file=file)
                await interaction.edit_original_response(content="✅ Bundle delivered to your DMs.")
        except Exception as e:
            await report_error(interaction, e, "Error during bundle build")

    @app_commands.command(name="digest", description="Read a previously generated monthly event digest.")
    @require_clearance("ec_admin", guild_only=False)
    async def digest(self, interaction: discord.Interaction, source: str, month: str):
        try:
            entry_id = f"digest:{source}:{month}"
            entry = self.lib.get(entry_id)
            if not entry or not entry.source_path or not Path(entry.source_path).exists():
                return await interaction.response.send_message(
                    f"❌ Digest not found for `{source}` in `{month}`. Has it been generated via CLI yet?",
                    ephemeral=True)
            await interaction.response.defer(ephemeral=True)
            file = discord.File(entry.source_path)
            await send_report(interaction, f"📜 Here is the digest for **{source}** ({month}):", file_to_send=file,
                              ephemeral_ack="✅ Digest retrieved!")
        except Exception as e:
            await report_error(interaction, e, "Failed to retrieve digest")

    @app_commands.command(name="thread-status", description="Check the status of a specific organizational thread.")
    @require_clearance("ec_admin", guild_only=False)
    async def thread_status(self, interaction: discord.Interaction, thread_id: str = None):
        try:
            ledger = load_threads_ledger(Path(config.META_DIR) / "threads_ledger.json")
            if not ledger:
                return await interaction.response.send_message("❌ Threads ledger not initialized or empty.",
                                                               ephemeral=True)

            if thread_id:
                if thread_id not in ledger:
                    return await interaction.response.send_message(f"❌ Thread `{thread_id}` not found.", ephemeral=True)
                t = ledger[thread_id]
                msg = f"**Thread:** {t.title}\n**Status:** {t.status}\n**Summary:** {t.summary}\n**Last Updated:** {t.last_updated} (via {t.last_updated_by_run})"
                if t.confidentiality_note:
                    msg = f"⚠️ *{t.confidentiality_note}*\n\n" + msg
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                active = [tid for tid, data in ledger.items() if data.status == 'active']
                if not active:
                    return await interaction.response.send_message("No active threads found.", ephemeral=True)
                msg = "**Active Organizational Threads:**\n" + "\n".join(
                    [f"- `{tid}`: {ledger[tid].title}" for tid in active])
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            await report_error(interaction, e, "Failed to load thread status")

    @app_commands.command(name="who-is", description="Look up a person in the entity glossary.")
    @require_clearance("ec_admin", guild_only=False)
    async def who_is(self, interaction: discord.Interaction, name: str):
        try:
            glossary = load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")
            if not glossary:
                return await interaction.response.send_message("❌ Glossary not initialized.", ephemeral=True)

            name_lower = name.lower()
            for key, data in glossary.items():
                if not isinstance(data, EntityEntry):
                    continue
                all_names = [data.canonical_name] + data.discord_handles + data.fathom_names + data.misheard_as
                all_names_lower = [str(n).lower() for n in all_names if n]
                key_searchable = key.replace('_', ' ').lower()

                if name_lower == key_searchable or any(name_lower in s for s in all_names_lower):
                    msg_parts = [f"**{data.canonical_name or key}**"]
                    if data.role: msg_parts.append(f"**Role:** {data.role}")
                    if data.discord_handles: msg_parts.append(f"**Discord:** {', '.join(data.discord_handles)}")
                    if data.github_username: msg_parts.append(f"**GitHub:** {data.github_username}")
                    if data.fathom_names: msg_parts.append(f"**Fathom Names:** {', '.join(data.fathom_names)}")
                    if data.misheard_as: msg_parts.append(f"**Misheard As:** {', '.join(data.misheard_as)}")
                    if data.notes: msg_parts.append(f"\n*Notes:* {data.notes}")
                    return await interaction.response.send_message("\n".join(msg_parts), ephemeral=True)

            await interaction.response.send_message(f"❌ Could not find `{name}` in the entity glossary.",
                                                    ephemeral=True)
        except Exception as e:
            await report_error(interaction, e, "Failed to search glossary")


async def setup(bot: commands.Bot):
    await bot.add_cog(ContextEngineCog(bot))