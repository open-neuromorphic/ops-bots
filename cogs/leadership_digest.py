import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import logging

from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, text_to_file
from pipeline.reporting.digest_metrics import build_leadership_digest

logger = logging.getLogger(__name__)


class LeadershipDigestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("LeadershipDigestCog loaded.")

    @app_commands.command(name="onm-leadership-digest",
                          description="Get a printable summary of recent conversations in the #leadership channel.")
    @app_commands.describe(time_period_months="The lookback period for the digest. Defaults to 2 months.",
                           post_in_channel="Post the report in this channel instead of DM (default: False).")
    @app_commands.choices(time_period_months=[
        app_commands.Choice(name="Last 2 Months", value=2),
        app_commands.Choice(name="Last 4 Months", value=4),
        app_commands.Choice(name="Last 6 Months", value=6),
        app_commands.Choice(name="Last 12 Months", value=12),
        app_commands.Choice(name="All Time", value=0),
    ])
    @require_clearance("ec_admin", guild_only=True)
    async def leadership_digest(self, interaction: discord.Interaction, time_period_months: int = 2,
                                post_in_channel: bool = False):
        try:
            await interaction.response.send_message(
                "📜 Generating digest for the #leadership channel... This may take a moment.", ephemeral=True)
            guild = interaction.guild

            leadership_channel = discord.utils.get(guild.text_channels, name='leadership')
            if not leadership_channel or not leadership_channel.permissions_for(guild.me).read_message_history:
                return await interaction.edit_original_response(
                    content="❌ Channel `#leadership` not found or lacks history permissions.")

            start_date = None
            period_description = "all time"
            if time_period_months > 0:
                start_date = datetime.now(timezone.utc) - timedelta(days=time_period_months * 30.44)
                period_description = f"since {start_date.strftime('%Y-%m-%d')}"

            messages_data = []
            try:
                async for message in leadership_channel.history(limit=None, after=start_date, oldest_first=True):
                    if message.author.bot: continue
                    messages_data.append({
                        "author": message.author.display_name,
                        "timestamp": message.created_at.strftime('%Y-%m-%d %H:%M'),
                        "content": message.clean_content,
                        "attachments": [a.filename for a in message.attachments]
                    })
            except discord.Forbidden:
                return await interaction.edit_original_response(
                    content="❌ Missing read permissions for message history.")
            except Exception as e:
                return await report_error(interaction, e, "Error reading message history")

            report_str = build_leadership_digest(messages_data, guild.name, period_description)
            report_file = text_to_file(report_str, "leadership_digest.txt")

            await send_report(interaction,
                              f"📜 Here is the message digest for the `#leadership` channel from {period_description}:",
                              report_file, post_in_channel)
        except Exception as e:
            await report_error(interaction, e, "Error generating leadership digest")


async def setup(bot: commands.Bot):
    await bot.add_cog(LeadershipDigestCog(bot))