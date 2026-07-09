import discord
from discord.ext import commands
from discord import app_commands
from collections import Counter
import logging

from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, text_to_file
from pipeline.reporting.user_metrics import generate_user_roles_csv, generate_user_acquisition_csv

logger = logging.getLogger(__name__)


class UserDataCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("UserDataCog loaded.")

    @app_commands.command(name="onm-get-user-data",
                          description="Export a spreadsheet of everyone in the server and the roles they have.")
    @require_clearance("ec_admin", guild_only=True)
    async def get_user_data(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message("📊 Generating user data report... Check your DMs!", ephemeral=True)
            guild = interaction.guild

            user_data_rows = []
            async for member in guild.fetch_members(limit=None):
                if member.bot: continue
                role_names = [role.name for role in member.roles if role.name != "@everyone"]
                roles_string = ", ".join(role_names) if role_names else "No specific roles"
                user_data_rows.append([str(member.id), member.name, member.display_name, roles_string])

            csv_string = generate_user_roles_csv(user_data_rows)
            discord_file = text_to_file(csv_string, "server_user_roles.csv")

            await send_report(interaction, f"📊 Here is the user data CSV for **{guild.name}**:", discord_file)
        except Exception as e:
            await report_error(interaction, e, "Error generating member data report")

    @app_commands.command(name="onm-user-acquisition-report",
                          description="Export a spreadsheet showing how many new people joined the server each month.")
    @require_clearance("ec_admin", guild_only=True)
    async def user_acquisition_report(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_message("📈 Generating user acquisition report... Check your DMs!",
                                                    ephemeral=True)
            guild = interaction.guild

            join_dates = Counter()
            async for member in guild.fetch_members(limit=None):
                if member.joined_at:
                    join_dates[member.joined_at.strftime('%Y-%m')] += 1

            csv_string = generate_user_acquisition_csv(join_dates)
            csv_file = text_to_file(csv_string, "user_acquisition_chart_data.csv")

            await send_report(interaction, f"📈 Here is the user acquisition data for **{guild.name}**.", csv_file)
        except Exception as e:
            await report_error(interaction, e, "Error generating user acquisition data")


async def setup(bot: commands.Bot):
    await bot.add_cog(UserDataCog(bot))