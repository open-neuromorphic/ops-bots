import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
import asyncio
import logging

from utils.checks import require_clearance
from utils.discord_utils import report_error
from utils.time_utils import parse_event_datetime
from services.google_calendar import create_calendar_event

logger = logging.getLogger(__name__)


class EventOpsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("EventOpsCog loaded.")

    @app_commands.command(
        name="onm-event-setup",
        description="Create Google Calendar and Discord Scheduled Events using easy-to-read dates."
    )
    @app_commands.describe(
        title="Title of the event",
        date="Date of the event (YYYY-MM-DD)",
        start_time="Start time (e.g. 14:00 or 2:00 PM)",
        end_time="End time (e.g. 15:30 or 3:30 PM)",
        timezone="Time zone (e.g. EST, PST, CEST, UTC)",
        youtube_id="YouTube Video/Stream ID or full link (optional)",
        speaker_name="Primary speaker or host name (optional)",
        description="Brief event description / abstract (optional)"
    )
    @require_clearance("volunteer_technical", guild_only=True)
    async def event_setup(
            self,
            interaction: discord.Interaction,
            title: str,
            date: str,
            start_time: str,
            end_time: str,
            timezone: str,
            youtube_id: str = None,
            speaker_name: str = None,
            description: str = None
    ):
        try:
            await interaction.response.defer(ephemeral=True)

            try:
                start_dt = parse_event_datetime(date, start_time, timezone)
                end_dt = parse_event_datetime(date, end_time, timezone)

                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                start_iso = start_dt.isoformat()
                end_iso = end_dt.isoformat()
            except ValueError as ve:
                return await interaction.followup.send(f"❌ {ve}", ephemeral=True)

            clean_yt_id = youtube_id or ""
            if "youtube.com" in clean_yt_id or "youtu.be" in clean_yt_id:
                clean_yt_id = clean_yt_id.split("v=")[-1].split("&")[0].split("/")[-1]

            stream_url = f"https://www.youtube.com/watch?v={clean_yt_id}" if clean_yt_id else "https://www.youtube.com/@openneuromorphic"
            event_desc = description or title

            gcal_event = await asyncio.to_thread(
                create_calendar_event,
                title=title,
                description=event_desc,
                start_time_iso=start_iso,
                end_time_iso=end_iso,
                location=stream_url
            )
            gcal_link = gcal_event.get("htmlLink", "")

            discord_event = await interaction.guild.create_scheduled_event(
                name=title[:100],
                description=f"{event_desc[:900]}\n\nCalendar Link: {gcal_link}",
                start_time=start_dt,
                end_time=end_dt,
                entity_type=discord.EntityType.external,
                location=stream_url,
                privacy_level=discord.PrivacyLevel.guild_only
            )

            msg = (
                f"✅ **Event Operations Setup Complete!**\n\n"
                f"📅 **Google Calendar (View):** <{gcal_link}>\n"
                f"💬 **Discord Event Link:** <{discord_event.url}>\n\n"
                f"--- \n"
                f"### 📋 Instructions for your Hugo Event Markdown Document:\n"
                f"Copy and paste the following parameters into your event's `index.md` frontmatter:\n\n"
                f"```yaml\n"
                f"start_datetime: \"{start_iso}\"\n"
                f"end_datetime: \"{end_iso}\"\n"
                f"upcoming: true\n"
                f"video: \"{clean_yt_id}\"\n"
                f"discord_event_url: \"{discord_event.url}\"\n"
                f"```\n\n"
                f"⚠️ **RSVP / Invite Link Limitation:**\n"
                f"The Google API *cannot* automatically generate the 'Invite via Link' (Yes/No/Maybe) URL.\n"
                f"To get it, click the Calendar link above, click **'Invite via link'** in the UI, and add this to your frontmatter manually:\n"
                f"```yaml\n"
                f"official_gcal: \"https://calendar.app.google/...\"\n"
                f"```\n\n"
                f"📌 **Pipeline Status & TODOs:**\n"
                f"- [ ] Map speaker/host/production support in the frontmatter arrays.\n"
                f"- [ ] Commit and push the `index.md` file to the website repository.\n"
            )

            await interaction.followup.send(content=msg, ephemeral=True)

        except Exception as e:
            await report_error(interaction, e, "Error executing event setup")


async def setup(bot: commands.Bot):
    await bot.add_cog(EventOpsCog(bot))