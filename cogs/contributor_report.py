import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import time
import json
import os
import logging

from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, text_to_file, gather_historical_messages
from services.cache import get as cache_get, put as cache_put, is_expired
from pipeline.reporting.contributor_metrics import process_contributor_counts, build_contributor_report

logger = logging.getLogger(__name__)
CACHE_DURATION_SECONDS = 3600


class ContributorReportCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("ContributorReportCog loaded.")

    @app_commands.command(name="onm-top-contributors-report",
                          description="See who is chatting the most in the server over different time periods.")
    @app_commands.describe(limit="Number of top contributors to display per period (1-25, default 10).",
                           post_in_channel="Post results in this channel instead of DM (default: False).",
                           force_refresh="Force a new data scan, ignoring cache (default: False).")
    @require_clearance("ec_admin", guild_only=True)
    async def top_contributors_report(self, interaction: discord.Interaction,
                                      limit: app_commands.Range[int, 1, 25] = 10, post_in_channel: bool = False,
                                      force_refresh: bool = False):
        try:
            guild = interaction.guild
            current_timestamp = time.time()

            cache_key = f"contrib_{guild.id}.json"
            cache_path = cache_get(cache_key, subdir="reports")
            using_cache, cache_age_minutes = False, 0
            counts_7_days, counts_30_days, counts_365_days = {}, {}, {}
            processed_items_count, skipped_items_count = 0, 0

            if not force_refresh and cache_path and not is_expired(cache_path, CACHE_DURATION_SECONDS):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    counts_7_days = data["counts_7_days"]
                    counts_30_days = data["counts_30_days"]
                    counts_365_days = data["counts_365_days"]
                    processed_items_count = data["processed_items"]
                    skipped_items_count = data["skipped_items"]
                    using_cache = True
                    cache_age_minutes = int((current_timestamp - os.path.getmtime(cache_path)) / 60)
                except Exception as e:
                    logger.warning(f"Failed to read cache {cache_key}: {e}")

            ack_msg = f"📈 Message contributor report (from cache, {cache_age_minutes} min ago)..." if using_cache else "📈 Analyzing message contributor report (7, 30, 365 days)..."
            await interaction.response.send_message(ack_msg, ephemeral=True)

            if not using_cache:
                now_utc = datetime.now(timezone.utc)
                scan_after_date = now_utc - timedelta(days=365)
                threshold_30_days = now_utc - timedelta(days=30)
                threshold_7_days = now_utc - timedelta(days=7)

                all_relevant_messages, processed_items_count, skipped_items_count = await gather_historical_messages(guild, scan_after_date)

                if all_relevant_messages:
                    counts_7_days, counts_30_days, counts_365_days = process_contributor_counts(all_relevant_messages,
                                                                                                threshold_7_days,
                                                                                                threshold_30_days)

                cache_data = {
                    "counts_7_days": counts_7_days,
                    "counts_30_days": counts_30_days,
                    "counts_365_days": counts_365_days,
                    "processed_items": processed_items_count,
                    "skipped_items": skipped_items_count
                }
                cache_put(cache_key, json.dumps(cache_data), subdir="reports")

            now_utc_for_report = datetime.now(timezone.utc)

            # Map IDs to names purely for the report view layer, avoiding Discord API imports in pipeline
            names_dict = {}
            for uid in set(list(counts_365_days.keys())):
                member = guild.get_member(int(uid))
                names_dict[
                    int(uid)] = f"{member.name} (Display: {member.display_name})" if member else f"Unknown User (ID: {uid})"

            report_string = build_contributor_report(
                guild.name, now_utc_for_report, using_cache, cache_age_minutes,
                counts_7_days, counts_30_days, counts_365_days,
                processed_items_count, skipped_items_count, limit, names_dict
            )

            report_file = text_to_file(report_string, "top_contributors_report.txt")

            if not (counts_7_days or counts_30_days or counts_365_days):
                await send_report(interaction, f"📊 Report for **{guild.name}**: No messages found.",
                                  post_in_channel=post_in_channel)
            else:
                await send_report(interaction, f"📊 Here is your top message contributors report for **{guild.name}**:",
                                  report_file, post_in_channel=post_in_channel)
        except Exception as e:
            await report_error(interaction, e, "Error generating contributor report")


async def setup(bot: commands.Bot):
    await bot.add_cog(ContributorReportCog(bot))