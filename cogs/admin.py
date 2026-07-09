import discord
from discord.ext import commands
from discord import app_commands
from utils.checks import require_clearance
from utils.discord_utils import report_error
import logging

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("AdminCog loaded.")

    @app_commands.command(name="onm-sync", description="Force update the bot's commands if they aren't showing up (Admin only).")
    @require_clearance("ec_admin", guild_only=True)
    async def sync_commands(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            synced = await self.bot.tree.sync()
            await interaction.followup.send(f"✅ Synced {len(synced)} command(s) successfully!", ephemeral=True)
            logger.info(f"Manual sync completed: {len(synced)} commands by {interaction.user}")
        except Exception as e:
            await report_error(interaction, e, "Error syncing commands")

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))