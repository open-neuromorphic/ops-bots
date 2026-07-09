import discord
from discord.ext import commands
from discord import app_commands
import io
import logging

from utils.checks import require_clearance
from utils.discord_utils import send_report, report_error, text_to_file
from pipeline.reporting.role_stats import compute_role_stats

logger = logging.getLogger(__name__)

class RoleAnalysisCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("RoleAnalysisCog loaded.")

    @app_commands.command(name="onm-role-analysis-report",
                          description="See a breakdown of server roles to understand how people are getting involved.")
    @app_commands.describe(post_in_channel="Post results in this channel instead of DM (default False).")
    @require_clearance("ec_admin", guild_only=True)
    async def role_analysis_report(self, interaction: discord.Interaction, post_in_channel: bool = False):
        try:
            await interaction.response.send_message(
                "📊 Generating user role analysis report... This may take a while. Check your DMs!", ephemeral=True)
            guild = interaction.guild

            all_user_roles = []
            try:
                async for member in guild.fetch_members(limit=None):
                    if member.bot: continue
                    roles = [role.name.strip().lower() for role in member.roles if role.name != "@everyone"]
                    all_user_roles.append(roles)
            except Exception as e:
                return await report_error(interaction, e, "Error fetching members")

            getting_involved_keyword = 'getting-involved'
            stats = compute_role_stats(all_user_roles, getting_involved_keyword)

            report = io.StringIO()
            report.write("--- User Role Analysis Report ---\n\n")
            report.write(f"Total number of users: {stats['total_member_count']}\nUsers with roles: {stats['users_with_roles']}\nUsers without specific roles: {stats['users_with_no_roles']}\n\n")
            report.write("--- Overall Role Popularity ---\n")
            for role, count in stats['overall_role_counts'].most_common():
                report.write(f"  - {role}: {count} users\n")

            report.write(f"\n--- Focus on '{getting_involved_keyword}' ---\n")
            report.write(f"Total users in '{getting_involved_keyword}': {stats['users_in_target']}\n")
            report.write(f"Users with ONLY this role: {stats['only_target_count']}\n\n")
            report.write(f"Co-occurring roles for '{getting_involved_keyword}' members:\n")
            for role, count in stats['target_co_occurrence'].most_common():
                report.write(f"  - {role}: {count} users\n")

            report_file = text_to_file(report.getvalue(), "user_role_analysis_report.txt")
            await send_report(interaction, f"📊 Here is the user role analysis report for **{guild.name}**:", report_file, post_in_channel)
        except Exception as e:
            await report_error(interaction, e, "Error generating role analysis report")

async def setup(bot: commands.Bot):
    await bot.add_cog(RoleAnalysisCog(bot))