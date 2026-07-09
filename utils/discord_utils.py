import discord
import logging
import io
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class ProgressIndicator:
    def __init__(self, interaction: discord.Interaction, steps: list[str], title: str = "Processing...",
                 use_followup: bool = False):
        self.interaction = interaction
        self.steps = steps
        self.title = title
        self.states = ["⬛"] * len(steps)
        self.last_update = 0
        self.use_followup = use_followup
        self.message = None

    async def update(self, index: int, state: str):
        if index >= len(self.states): return
        self.states[index] = state

        now = time.time()
        # Ensure we don't hit rate limits, but always bypass limit on 🟩 completion ticks
        if state != "🟩" and (now - self.last_update) < 1.0:
            return
        self.last_update = now

        lines = [f"{self.states[i]} {i + 1}: {step}" for i, step in enumerate(self.steps)]
        msg = f"⚙️ **{self.title}**\n" + "\n".join(lines)
        try:
            if self.use_followup:
                if not self.message:
                    self.message = await self.interaction.followup.send(content=msg, ephemeral=True, wait=True)
                else:
                    await self.message.edit(content=msg)
            else:
                if self.interaction.response.is_done():
                    await self.interaction.edit_original_response(content=msg)
                else:
                    await self.interaction.response.send_message(content=msg, ephemeral=True)
        except Exception:
            pass


def text_to_file(text: str, filename: str) -> discord.File:
    """Helper to convert string data directly into a Discord attachment."""
    return discord.File(fp=io.BytesIO(text.encode('utf-8')), filename=filename)


async def send_report(
        interaction: discord.Interaction,
        text_message: str,
        file_to_send: discord.File | None = None,
        post_in_channel: bool = False,
        ephemeral_ack: str = "✅ Report sent to your DMs!"
) -> None:
    guild = interaction.guild
    target_channel_name = f"channel #{interaction.channel.name}" if interaction.channel else "DM"
    final_ack_message = ephemeral_ack
    if post_in_channel and interaction.channel and file_to_send:
        final_ack_message = "✅ Report posted in this channel."

    try:
        if post_in_channel and interaction.channel:
            can_send = interaction.channel.permissions_for(guild.me).send_messages
            can_attach = interaction.channel.permissions_for(guild.me).attach_files if file_to_send else True

            if can_send and can_attach:
                send_kwargs = {"content": text_message, "ephemeral": False}
                if file_to_send: send_kwargs["file"] = file_to_send
                await interaction.followup.send(**send_kwargs)
            else:
                if file_to_send and hasattr(file_to_send.fp, 'seek'): file_to_send.fp.seek(0)
                alt_dm_kwargs = {"content": f"ℹ️ Couldn't post in {target_channel_name} (permissions).\n{text_message}"}
                if file_to_send: alt_dm_kwargs["file"] = file_to_send
                await interaction.user.send(**alt_dm_kwargs)
                final_ack_message = "✅ Report ready. Couldn't post here, sent to DMs."
        else:
            dm_kwargs = {"content": text_message}
            if file_to_send: dm_kwargs["file"] = file_to_send
            await interaction.user.send(**dm_kwargs)

        try:
            await interaction.edit_original_response(content=final_ack_message)
        except discord.NotFound:
            logger.debug("Original interaction message was deleted before it could be updated with an ack.")
    except discord.Forbidden:
        try:
            await interaction.edit_original_response(
                content="❌ Could not send report. Check privacy settings/bot permissions.")
        except discord.NotFound:
            logger.debug("Original interaction message deleted while attempting to report a Forbidden error.")
    except Exception as e:
        await report_error(interaction, e, "Error sending results")


async def report_error(interaction: discord.Interaction, e: Exception, context_msg: str = "An error occurred"):
    logger.exception(f"{context_msg}: {e}")
    error_msg = f"❌ {context_msg}: {e}"
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(content=error_msg)
        else:
            await interaction.response.send_message(content=error_msg, ephemeral=True)
    except Exception as fallback_e:
        logger.error(f"Failed to send error message to user: {fallback_e}")


async def gather_historical_messages(guild: discord.Guild, scan_after_date: datetime) -> tuple[
    list[tuple[int, datetime]], int, int]:
    all_relevant_messages = []
    processed_items_count = 0
    skipped_items_count = 0
    processed_thread_ids = set()

    for channel in guild.text_channels:
        if not channel.permissions_for(guild.me).read_message_history:
            skipped_items_count += 1
            continue
        try:
            async for message in channel.history(limit=None, after=scan_after_date, oldest_first=False):
                if not message.author.bot:
                    all_relevant_messages.append((message.author.id, message.created_at))
            processed_items_count += 1
        except discord.Forbidden:
            skipped_items_count += 1
        except Exception as e:
            logger.exception(f"Error scanning channel {channel.name}: {e}")
            skipped_items_count += 1

        threads_to_process = list(channel.threads)
        try:
            async for thread_obj in channel.archived_threads(limit=None):
                threads_to_process.append(thread_obj)
        except discord.Forbidden:
            pass
        except Exception as e:
            logger.exception(f"Error fetching archived threads: {e}")

        for thread in threads_to_process:
            if thread.id in processed_thread_ids: continue
            processed_thread_ids.add(thread.id)
            try:
                async for message in thread.history(limit=None, after=scan_after_date, oldest_first=False):
                    if not message.author.bot:
                        all_relevant_messages.append((message.author.id, message.created_at))
            except discord.Forbidden:
                skipped_items_count += 1
            except Exception as e:
                logger.exception(f"Error scanning thread: {e}")
                skipped_items_count += 1

    for thread in guild.threads:
        if thread.id in processed_thread_ids or thread.archived: continue
        processed_thread_ids.add(thread.id)
        try:
            async for message in thread.history(limit=None, after=scan_after_date, oldest_first=False):
                if not message.author.bot:
                    all_relevant_messages.append((message.author.id, message.created_at))
            processed_items_count += 1
        except discord.Forbidden:
            skipped_items_count += 1
        except Exception as e:
            logger.exception(f"Error scanning guild thread: {e}")
            skipped_items_count += 1

    return all_relevant_messages, processed_items_count, skipped_items_count


async def get_channel_last_activity(channel: discord.TextChannel, check_threads: bool) -> datetime | None:
    last_msg = None
    try:
        async for msg in channel.history(limit=1):
            last_msg = msg
    except (discord.Forbidden, discord.NotFound):
        pass

    last_thread_msg_time = None
    if check_threads:
        try:
            for thread in channel.threads:
                async for tmsg in thread.history(limit=1):
                    if not last_thread_msg_time or tmsg.created_at > last_thread_msg_time:
                        last_thread_msg_time = tmsg.created_at
        except (discord.Forbidden, discord.NotFound):
            pass

    latest_activity = None
    if last_msg:
        latest_activity = last_msg.created_at
    if last_thread_msg_time and (not latest_activity or last_thread_msg_time > latest_activity):
        latest_activity = last_thread_msg_time

    return latest_activity