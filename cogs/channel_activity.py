import discord
from discord.ext import commands
from discord import app_commands
import logging

from utils.checks import require_clearance
from utils.discord_utils import send_report, text_to_file, report_error, get_channel_last_activity
from pipeline.reporting.channel_metrics import build_channel_topics_report, build_inactive_channels_report

logger = logging.getLogger(__name__)

class ChannelActivityCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("ChannelActivityCog loaded.")

    @app_commands.command(name="onm-channel-topics-report",
                          description="Find out which public channels are missing a topic/description.")
    @app_commands.describe(post_in_channel="Post results in this channel instead of DM (default False).")
    @require_clearance("ec_admin", guild_only=True)
    async def channel_topics_report(self, interaction: discord.Interaction, post_in_channel: bool = False):
        try:
            guild = interaction.guild

            ack_message = "🔍 Generating public channel topics report... This may take a moment on large servers."
            if post_in_channel and interaction.channel:
                ack_message += " Results will be posted here."
            else:
                ack_message += " Check your DMs!"
            await interaction.response.send_message(ack_message, ephemeral=True)

            channels_data = []
            scanned_channels, skipped_channels = 0, 0

            sorted_text_channels = sorted(guild.text_channels,
                                          key=lambda c: (c.category.position if c.category else float('inf'), c.position))

            for channel in sorted_text_channels:
                is_public = channel.permissions_for(guild.default_role).view_channel and channel.permissions_for(
                    guild.me).view_channel
                if not is_public:
                    skipped_channels += 1
                    continue

                scanned_channels += 1
                category_name = channel.category.name if channel.category else "No Category"
                channels_data.append({
                    "name": channel.name,
                    "category": category_name,
                    "topic": channel.topic.strip() if channel.topic else None
                })

            report_str = build_channel_topics_report(channels_data, guild.name, scanned_channels, skipped_channels)
            report_file = text_to_file(report_str, "public_channel_topics_report.txt")
            await send_report(interaction, f"📊 Here is your public channel topics report for **{guild.name}**:",
                              report_file, post_in_channel)
        except Exception as e:
            await report_error(interaction, e, "Error generating public channel topics report")

    @app_commands.command(name="onm-inactive-channels-report",
                          description="Find channels that haven't been used recently so you can clean them up.")
    @app_commands.describe(days_inactive="Min days inactive (default 30).",
                           check_threads="Consider thread activity (default False).",
                           post_in_channel="Post results in this channel instead of DM.")
    @require_clearance("ec_admin", guild_only=True)
    async def inactive_channels_report(self, interaction: discord.Interaction,
                                       days_inactive: app_commands.Range[int, 7, 365] = 30, check_threads: bool = False,
                                       post_in_channel: bool = False):
        try:
            guild = interaction.guild
            await interaction.response.send_message(f"🔍 Scanning for channels inactive for {days_inactive}+ days...",
                                                    ephemeral=True)

            channel_activity_data = []
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).read_message_history:
                    continue

                try:
                    latest_activity = await get_channel_last_activity(channel, check_threads)
                    channel_activity_data.append({
                        "name": channel.name,
                        "category": channel.category.name if channel.category else "No Category",
                        "last_active_dt": latest_activity
                    })
                except Exception as e:
                    logger.exception(f"Failed to read channel {channel.name}: {e}")

            report_str, inactive_count = build_inactive_channels_report(channel_activity_data, days_inactive)
            if inactive_count == 0:
                await interaction.edit_original_response(content="✅ No inactive channels found!")
                return

            report_file = text_to_file(report_str, "inactive_channels.txt")
            await send_report(interaction, f"📊 Found {inactive_count} inactive channels:", report_file,
                              post_in_channel)
        except Exception as e:
            await report_error(interaction, e, "Error generating inactive channels report")

async def setup(bot: commands.Bot):
    await bot.add_cog(ChannelActivityCog(bot))