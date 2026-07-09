import discord
from discord.ext import commands
from discord import app_commands
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging

from utils.checks import require_clearance
from utils.discord_utils import send_report, text_to_file, report_error
from pipeline.reporting.social_metrics import score_activity, build_social_digest_report

logger = logging.getLogger(__name__)

class SocialDigestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("SocialDigestCog loaded.")

    async def _fetch_reply_context(self, message: discord.Message) -> str | None:
        if message.reference and message.reference.message_id:
            try:
                ref_channel_id = message.reference.channel_id
                channel_to_fetch = self.bot.get_channel(ref_channel_id) or message.channel
                if channel_to_fetch:
                    referenced_msg = await channel_to_fetch.fetch_message(message.reference.message_id)
                    if referenced_msg:
                        content_preview = referenced_msg.clean_content[:150] + "..." if len(referenced_msg.clean_content) > 150 else referenced_msg.clean_content
                        if not content_preview.strip(): content_preview = "[attachment/embed]"
                        return f"{referenced_msg.author.display_name}: \"{content_preview}\""
            except discord.NotFound:
                logger.debug(f"Reply context not found (deleted message): {message.reference.message_id}")
            except discord.Forbidden:
                logger.debug(f"Missing permissions to fetch reply context in channel {message.reference.channel_id}")
            except Exception as e:
                logger.exception(f"Error fetching reply context: {e}")
        return None

    @app_commands.command(name="onm-generate-activity-digest", description="Get a summary of interesting recent messages from the most active members.")
    @app_commands.describe(num_users="Top users (default 3).", days_lookback="Days back (default 7).", max_messages_per_user="Max messages per user (default 10).", post_in_channel="Post results in this channel instead of DM.")
    @require_clearance("ec_admin", guild_only=True)
    async def generate_activity_digest(self, interaction: discord.Interaction, num_users: app_commands.Range[int, 1, 10] = 3, days_lookback: app_commands.Range[int, 1, 14] = 7, max_messages_per_user: app_commands.Range[int, 5, 30] = 10, target_avg_length: app_commands.Range[int, 5, 100] = 25, length_impact_factor: app_commands.Range[float, 0.0, 2.0] = 0.5, min_effective_ratio: app_commands.Range[float, 0.01, 1.0] = 0.2, include_reply_context: bool = True, post_in_channel: bool = False):
        try:
            guild = interaction.guild

            await interaction.response.send_message("🔍 Generating activity digest...", ephemeral=True)
            now_utc = datetime.now(timezone.utc)
            scan_after_date = now_utc - timedelta(days=days_lookback)
            user_message_data = defaultdict(lambda: {'count': 0, 'total_length': 0, 'messages': []})

            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).read_message_history: continue
                try:
                    async for message in channel.history(limit=None, after=scan_after_date, oldest_first=False):
                        if message.author.bot or not message.clean_content.strip(): continue
                        msg_len = len(message.clean_content)
                        reply_context_str = await self._fetch_reply_context(message) if include_reply_context else None
                        user_message_data[message.author.id]['count'] += 1
                        user_message_data[message.author.id]['total_length'] += msg_len
                        user_message_data[message.author.id]['messages'].append({
                            'content': message.clean_content, 'length': msg_len, 'channel': f"#{channel.name}",
                            'timestamp': message.created_at, 'reply_to': reply_context_str
                        })
                except discord.Forbidden:
                    continue
                except Exception as e:
                    logger.exception(f"Error reading channel {channel.name}: {e}")

            if not user_message_data:
                return await send_report(interaction, f"📊 No non-empty messages found in the last {days_lookback} days.", None, post_in_channel)

            top_user_ids = score_activity(user_message_data, min_effective_ratio, target_avg_length, length_impact_factor, num_users)

            names_dict = {}
            for uid, _ in top_user_ids:
                member = guild.get_member(uid)
                names_dict[uid] = f"{member.display_name}" if member else f"User ID: {uid}"

            report_str = build_social_digest_report(
                guild.name, days_lookback, top_user_ids,
                user_message_data, max_messages_per_user,
                include_reply_context, names_dict
            )

            digest_file = text_to_file(report_str, "activity_digest.txt")
            await send_report(interaction, f"📊 Here is the scored activity digest for **{guild.name}**:", digest_file, post_in_channel)
        except Exception as e:
            await report_error(interaction, e, "Error generating activity digest")

async def setup(bot: commands.Bot):
    await bot.add_cog(SocialDigestCog(bot))