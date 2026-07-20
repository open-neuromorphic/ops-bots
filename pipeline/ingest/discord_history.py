import discord
import os
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from calendar import monthrange
import logging
import config
from context_engine.formatter import scan_and_redact
from services.entity_lookup import resolve_discord_author

logger = logging.getLogger(__name__)

# Hard ceiling to prevent Out of Memory (OOM) crashes on massively spammed channels
MAX_HISTORY_MESSAGES = 25000

async def fetch_monthly_channel_history(channel_key: str, month_str: str, force_refresh: bool = False,
                                        bot_client: discord.Client = None) -> Path:
    """
    Fetches a specific month of channel history (including threads), caches it to disk.
    If bot_client is provided, uses the active connection. Otherwise, spins up a temporary client.
    """
    target_channel_conf = next((c for c in config.DISCORD_CHANNELS if c.key == channel_key), None)
    if not target_channel_conf:
        raise ValueError(f"Unknown discord channel key: '{channel_key}'. Check config.DISCORD_CHANNELS.")

    year, month = map(int, month_str.split('-'))
    start_date = datetime(year, month, 1, tzinfo=timezone.utc)
    _, last_day = monthrange(year, month)
    end_date = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

    out_dir = Path(config.DISCORD_LOGS_DIR) / channel_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{month_str}.txt"

    if out_path.exists() and not force_refresh:
        logger.info(f"Monthly cache for {channel_key} ({month_str}) already exists. Skipping download.")
        return out_path

    logger.info(f"Fetching live Discord history for #{target_channel_conf.channel_name} ({month_str})...")

    async def _do_fetch(client: discord.Client) -> list:
        collected = []
        guild = client.get_guild(config.DISCORD_GUILD_ID)
        if not guild:
            raise ValueError(f"Bot is not in the guild {config.DISCORD_GUILD_ID}")

        channel = discord.utils.get(guild.text_channels, name=target_channel_conf.channel_name)
        if not channel:
            raise ValueError(f"Channel #{target_channel_conf.channel_name} not found.")

        logger.info(f"Fetching main channel messages for #{target_channel_conf.channel_name}...")
        async for message in channel.history(after=start_date, before=end_date, limit=MAX_HISTORY_MESSAGES,
                                             oldest_first=True):
            if message.author.bot or not message.clean_content.strip(): continue
            safe_content, _ = scan_and_redact(message.clean_content)
            ts = message.created_at.strftime('%Y-%m-%d %H:%M')
            author_resolved = resolve_discord_author(message.author.name)
            collected.append(f"[{ts}] {author_resolved}: {safe_content}")

        logger.info(f"Fetching active threads for #{target_channel_conf.channel_name}...")
        for thread in channel.threads:
            if len(collected) >= MAX_HISTORY_MESSAGES: break
            async for message in thread.history(after=start_date, before=end_date, limit=None, oldest_first=True):
                if len(collected) >= MAX_HISTORY_MESSAGES: break
                if message.author.bot or not message.clean_content.strip(): continue
                safe_content, _ = scan_and_redact(message.clean_content)
                ts = message.created_at.strftime('%Y-%m-%d %H:%M')
                author_resolved = resolve_discord_author(message.author.name)
                collected.append(f"[{ts}] {author_resolved} (in thread #{thread.name}): {safe_content}")

        logger.info(f"Fetching archived threads for #{target_channel_conf.channel_name}...")
        async for thread in channel.archived_threads(limit=None, before=end_date):
            if len(collected) >= MAX_HISTORY_MESSAGES: break
            if thread.archive_timestamp and thread.archive_timestamp < start_date:
                continue
            async for message in thread.history(after=start_date, before=end_date, limit=None, oldest_first=True):
                if len(collected) >= MAX_HISTORY_MESSAGES: break
                if message.author.bot or not message.clean_content.strip(): continue
                safe_content, _ = scan_and_redact(message.clean_content)
                ts = message.created_at.strftime('%Y-%m-%d %H:%M')
                author_resolved = resolve_discord_author(message.author.name)
                collected.append(f"[{ts}] {author_resolved} (in thread #{thread.name}): {safe_content}")

        if len(collected) >= MAX_HISTORY_MESSAGES:
            logger.warning(
                f"Reached MAX_HISTORY_MESSAGES ({MAX_HISTORY_MESSAGES}) for #{target_channel_conf.channel_name}. History truncated.")

        return collected

    collected_messages = []

    if bot_client:
        logger.info("Using active bot client for fetch.")
        collected_messages = await _do_fetch(bot_client)
    else:
        logger.info("Spawning temporary client for fetch.")
        token = os.getenv('DISCORD_BOT_TOKEN') or os.getenv('DISCORD_TOKEN_SCRIBE') or os.getenv(
            'DISCORD_TOKEN_UNIFIED')
        if not token:
            raise ValueError("No valid Discord token found in environment variables.")

        intents = discord.Intents.default()
        intents.message_content = True
        temp_client = discord.Client(intents=intents)

        @temp_client.event
        async def on_ready():
            try:
                nonlocal collected_messages
                collected_messages = await _do_fetch(temp_client)
            except Exception as e:
                logger.error(f"Error during temporary client fetch: {e}")
            finally:
                await temp_client.close()

        async with temp_client:
            await temp_client.start(token)

    def extract_time(msg_line):
        return datetime.strptime(msg_line[1:17], '%Y-%m-%d %H:%M')

    collected_messages.sort(key=extract_time)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"--- DISCORD LOG: #{target_channel_conf.channel_name} ({month_str}) ---\n\n")
        f.write("\n\n".join(collected_messages))
        if len(collected_messages) >= MAX_HISTORY_MESSAGES:
            f.write(
                "\n\n[SYSTEM WARNING: Maximum message capacity reached. Data truncated to prevent memory exhaustion.]")
        if not collected_messages:
            f.write("*No messages found for this period.*")

    logger.info(f"Saved {len(collected_messages)} messages to {out_path}")
    return out_path