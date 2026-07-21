import discord
from discord.ext import commands
from discord import app_commands
import uuid
import json
import logging
import os
from pathlib import Path
import asyncio
from datetime import datetime, timezone

import config
from models.meta import ThreadEntry, ThreadHistoryNote, load_threads_ledger
from models.requests import ContextBuildRequest
from utils.checks import require_clearance
from utils.discord_utils import report_error, ProgressIndicator
from utils.menu_framework import (
    MenuSession, session_store, ScreenSpec, ButtonSpec,
    render_screen, MenuButton, update_menu_message
)
from context_engine.library_index import ContextLibrary
from context_engine.builder import build_bundle
from services.cache import is_stale
from ops.sync_sources import sync_all_sources
from ops.sync_snapshot_docs import sync_snapshots
from pipeline.ingest.discord_history import fetch_monthly_channel_history
from pipeline.summarize.transcript import summarize_stale_transcripts

logger = logging.getLogger(__name__)


def load_queue() -> list[dict]:
    queue_path = Path(config.META_DIR) / "pending_review.json"
    if not queue_path.exists(): return []
    try:
        return json.loads(queue_path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_queue(queue: list[dict]):
    queue_path = Path(config.META_DIR) / "pending_review.json"
    if not queue:
        if queue_path.exists(): queue_path.unlink()
    else:
        queue_path.write_text(json.dumps(queue, indent=2), encoding="utf-8")


async def handle_main_screen(interaction: discord.Interaction, session: MenuSession, payload: str = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    session.current_screen = "MAIN"
    session_store.put(session.session_id, session)

    queue = load_queue()
    queue_count = len(queue)
    queue_label = f"⚖️ Review Queue ({queue_count})" if queue_count > 0 else "⚖️ Review Queue"

    spec = ScreenSpec(
        content="📊 **Context Engine Control Panel**\n\nSelect a module below to manage the AI library and system state.",
        buttons=[
            ButtonSpec(label="📥 Bundles & Summaries", action="nav_bundles", style=discord.ButtonStyle.primary, row=0),
            ButtonSpec(label=queue_label, action="nav_review", style=discord.ButtonStyle.success if queue_count > 0 else discord.ButtonStyle.secondary, row=0),
            ButtonSpec(label="⚙️ System Settings", action="nav_settings", style=discord.ButtonStyle.secondary, row=0),
            ButtonSpec(label="❌ Close", action="close_session", style=discord.ButtonStyle.danger, row=1)
        ]
    )
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_nav_bundles(interaction: discord.Interaction, session: MenuSession, payload: str = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    session.current_screen = "BUNDLES"
    session_store.put(session.session_id, session)

    lib = ContextLibrary()
    entries = lib.query()
    total_entries = len(entries)
    unsummarized, stale = 0, 0
    discord_dates = []

    for e in entries:
        if e.source_type == "discord_history":
            discord_dates.append(e.date)
        if e.source_type in ["meeting_transcript", "ec_transcript", "discord_history"] and not e.excluded:
            source_p = Path(e.source_path) if e.source_path else None
            if source_p and source_p.exists():
                if not e.summary_path or not Path(e.summary_path).exists():
                    unsummarized += 1
                elif is_stale(e, source_p):
                    stale += 1

    latest_discord_date = max(discord_dates) if discord_dates else "None"

    content = "📥 **Bundles & Summaries**\n\n"
    content += f"**Total Library Entries:** `{total_entries}`\n"
    content += f"**Latest Discord Record:** `{latest_discord_date}`\n"
    content += f"**Unsummarized Documents:** `{unsummarized}`\n"
    content += f"**Stale Summaries:** `{stale}`\n\n"

    buttons = [
        ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0),
        ButtonSpec(label="Compact Bundle", action="req_bundle", payload="compact", style=discord.ButtonStyle.success, row=1),
        ButtonSpec(label="Hybrid Bundle", action="req_bundle", payload="hybrid", style=discord.ButtonStyle.success, row=1),
        ButtonSpec(label="Full Bundle", action="req_bundle", payload="full", style=discord.ButtonStyle.success, row=1),
        ButtonSpec(label=f"🤖 Run Summarizer ({unsummarized + stale})", action="run_summarizer", style=discord.ButtonStyle.primary, row=2, disabled=(unsummarized + stale == 0))
    ]
    spec = ScreenSpec(content=content, buttons=buttons)
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_nav_review(interaction: discord.Interaction, session: MenuSession, payload: str = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    session.current_screen = "REVIEW"
    session_store.put(session.session_id, session)

    queue = load_queue()
    if not queue:
        content = "⚖️ **Review Queue**\n\n🎉 *No pending AI ledger updates to review! You are all caught up.*"
        buttons = [ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0)]
    else:
        item = queue[0]
        content = "⚖️ **Review Queue**\n"
        content += f"*Item 1 of {len(queue)}*\n\n"
        content += f"**Thread ID:** `{item.get('thread_id')}`\n"
        content += f"**Proposed Status:** `{item.get('status')}`\n"
        content += f"**Source Run:** `{item.get('source_run')}`\n"
        content += f"**History Note:**\n> {item.get('history_note')}\n"

        buttons = [
            ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0),
            ButtonSpec(label="✅ Accept", action="review_action", payload="accept", style=discord.ButtonStyle.success, row=1),
            ButtonSpec(label="❌ Reject", action="review_action", payload="reject", style=discord.ButtonStyle.danger, row=1),
            ButtonSpec(label="⏭️ Skip", action="review_action", payload="skip", style=discord.ButtonStyle.secondary, row=1)
        ]

    spec = ScreenSpec(content=content, buttons=buttons)
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_nav_settings(interaction: discord.Interaction, session: MenuSession, payload: str = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    session.current_screen = "SETTINGS"
    session_store.put(session.session_id, session)

    content = "⚙️ **Context Engine Settings**\n\n"
    content += "- **Full System Sync**: Pulls live Discord activity, GitHub snapshot docs, and indexes local transcripts.\n"
    content += "- **Flush Caches**: Clears temporary AI context and pipeline caches. Run this if identity mappings or GitHub payloads appear stale.\n\n"

    sync_log = session.data_context.get("sync_log")
    if sync_log:
        content += f"**Last Action Result:**\n```text\n{sync_log}\n```"

    buttons = [
        ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0),
        ButtonSpec(label="🔄 Run Full System Sync", action="run_full_sync", style=discord.ButtonStyle.primary, row=1),
        ButtonSpec(label="🗑️ Flush All Caches", action="flush_caches", style=discord.ButtonStyle.danger, row=1)
    ]
    spec = ScreenSpec(content=content, buttons=buttons)
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_flush_caches(interaction: discord.Interaction, session: MenuSession, payload: str = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    cache_dir = Path(config.CACHE_DIR)
    deleted_files = 0
    safe_dirs = ["ui_sessions"]  # Prevents destroying the user's active UI menu

    if cache_dir.exists():
        for root, dirs, files in os.walk(cache_dir):
            if any(safe in root for safe in safe_dirs):
                continue
            for file in files:
                os.remove(os.path.join(root, file))
                deleted_files += 1

    session.data_context["sync_log"] = f"✅ Flushed {deleted_files} cached pipeline files."
    await handle_nav_settings(interaction, session)


async def _background_build(interaction: discord.Interaction, profile: str):
    try:
        req = ContextBuildRequest(profile=profile, since=None)
        lib = ContextLibrary()

        steps = ["Fetch Discord Logs", "Fetch Transcripts", "Fetch GitHub Content", "Compile Bundle"]
        progress = ProgressIndicator(interaction, steps, "Building Context Bundle...", use_followup=True)
        await progress.update(0, "⬛")

        _, filepath, size_bytes = await build_bundle(
            args=req,
            caller_name=f"@{interaction.user.name}",
            lib=lib,
            progress_cb=progress.update
        )
        size_kb = size_bytes / 1024

        file = discord.File(filepath)
        await interaction.user.send(
            content=f"✅ Here is your requested Context Engine Bundle (`{profile}`, {size_kb:.1f} KB):", file=file)
        if progress.message:
            await progress.message.edit(content="✅ Bundle built and delivered to your DMs!")
    except discord.Forbidden:
        logger.warning(f"Could not deliver bundle to {interaction.user.name}; DMs are closed.")
    except Exception as e:
        logger.error(f"Background bundle build failed: {e}")


async def handle_req_bundle(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    interaction.client.loop.create_task(_background_build(interaction, payload or "compact"))


async def handle_run_full_sync(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    steps = [
        "Pull Live Discord Data (Current Month)",
        "Pull GitHub Snapshot Docs",
        "Sync Local Files & Index to Library Schema"
    ]
    progress = ProgressIndicator(interaction, steps, "Full System Sync", use_followup=True)
    await progress.update(0, "🟦")

    combined_logs = []
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    discord_pulled = 0
    for chan in config.DISCORD_CHANNELS:
        try:
            await fetch_monthly_channel_history(chan.key, current_month, force_refresh=True,
                                                bot_client=interaction.client)
            discord_pulled += 1
        except Exception as e:
            logger.error(f"Failed to fetch {chan.key}: {e}")
            combined_logs.append(f"❌ Discord error ({chan.key}): {e}")

    combined_logs.append(f"✅ Discord: Pulled latest messages for {discord_pulled} channels.")
    await progress.update(0, "🟩")
    await progress.update(1, "🟦")

    gh_updated, gh_skipped, gh_log = await sync_snapshots()
    combined_logs.append(f"✅ GitHub Docs: Synced {gh_updated} files, skipped {gh_skipped}.")

    await progress.update(1, "🟩")
    await progress.update(2, "🟦")

    local_updated, local_skipped, local_log = await asyncio.to_thread(sync_all_sources)
    combined_logs.append(f"✅ Library Sync: {local_updated} records updated, {local_skipped} skipped.")

    await progress.update(2, "🟩")
    if progress.message:
        await progress.message.edit(content="✅ Full system sync complete!")

    final_log_str = "\n".join(combined_logs) + "\n\n--- Sub-Logs ---\n" + gh_log + "\n" + local_log
    if len(final_log_str) > 1500:
        final_log_str = final_log_str[:1500] + "\n...[Truncated]"

    session.data_context["sync_log"] = final_log_str
    await handle_nav_settings(interaction, session)


async def handle_run_summarizer(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    steps = ["Scan for Stale Transcripts", "Run LLM Summarization Pipeline"]
    progress = ProgressIndicator(interaction, steps, "Summarizer Pipeline", use_followup=True)
    await progress.update(0, "🟦")
    lib = ContextLibrary()
    await progress.update(0, "🟩")
    await progress.update(1, "🟦")

    count = await summarize_stale_transcripts(lib, force=False)
    await progress.update(1, "🟩")
    if progress.message:
        await progress.message.edit(
            content=f"✅ Summarization pipeline complete. Generated new summaries for {count} documents.")
    await handle_nav_bundles(interaction, session)


async def handle_review_action(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    queue = load_queue()
    if not queue:
        return await handle_nav_review(interaction, session)

    item = queue.pop(0)

    if payload == "skip":
        queue.append(item)
        save_queue(queue)
    elif payload == "reject":
        save_queue(queue)
    elif payload == "accept":
        ledger_path = Path(config.META_DIR) / "threads_ledger.json"
        ledger = load_threads_ledger(ledger_path)
        tid = item.get('thread_id')

        if tid not in ledger:
            ledger[tid] = ThreadEntry(
                title=f"New Thread: {tid}", category="other", status=item.get('status', 'active'),
                summary="AI proposed thread. Needs human summary.", last_updated=item.get('date', ''),
                last_updated_by_run=item.get('source_run', '')
            )
        entry = ledger[tid]
        if item.get('status'): entry.status = item.get('status')
        if item.get('date'): entry.last_updated = item.get('date')
        if item.get('source_run'): entry.last_updated_by_run = item.get('source_run')

        entry.history.append(ThreadHistoryNote(
            date=item.get('date'), note=item.get('history_note'), source_entry=item.get('source_run')
        ))

        ledger_path.write_text(json.dumps({k: v.model_dump(exclude_none=True) for k, v in ledger.items()}, indent=2),
                               encoding="utf-8")
        save_queue(queue)

    await handle_nav_review(interaction, session)


class ScribeMenuCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("ScribeMenuCog loaded.")
        self.bot.add_dynamic_items(MenuButton)
        if not hasattr(self.bot, "menu_registry"): self.bot.menu_registry = {}

        self.bot.menu_registry.update({
            "nav_main": handle_main_screen,
            "nav_bundles": handle_nav_bundles,
            "nav_review": handle_nav_review,
            "nav_settings": handle_nav_settings,
            "flush_caches": handle_flush_caches,
            "req_bundle": handle_req_bundle,
            "run_full_sync": handle_run_full_sync,
            "run_summarizer": handle_run_summarizer,
            "review_action": handle_review_action
        })

    @app_commands.command(name="onm-scribe", description="Interactive Context Engine Dashboard & Control Panel.")
    @require_clearance("ec_admin", guild_only=True)
    async def scribe_menu(self, interaction: discord.Interaction):
        try:
            session = MenuSession(
                session_id=str(uuid.uuid4())[:8], bot_id="onm-scribe",
                owner_id=interaction.user.id
            )
            session_store.put(session.session_id, session)
            await handle_main_screen(interaction, session)
        except Exception as e:
            await report_error(interaction, e, "Failed to launch Scribe menu")


async def setup(bot: commands.Bot):
    await bot.add_cog(ScribeMenuCog(bot))