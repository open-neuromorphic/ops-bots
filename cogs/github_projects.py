import discord
from discord.ext import commands
from discord import app_commands
import logging

import config
from services.github import search_issues, create_github_issue
from services.entity_lookup import get_github_handle_for_discord
from utils.checks import require_clearance
from utils.discord_utils import report_error

logger = logging.getLogger(__name__)

REPO_CHOICES = [
    app_commands.Choice(name="Communications", value="communications"),
    app_commands.Choice(name="Website", value="open-neuromorphic.github.io")
]


class IssueModal(discord.ui.Modal, title='Create New GitHub Issue'):
    issue_title = discord.ui.TextInput(label='Issue Title', placeholder='Brief summary...', max_length=100)
    issue_body = discord.ui.TextInput(label='Description', style=discord.TextStyle.paragraph, required=False)

    def __init__(self, repo_name: str):
        super().__init__()
        self.repo_name = repo_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"⏳ Submitting issue to `{self.repo_name}`...", ephemeral=True)
        try:
            body_content = self.issue_body.value + f"\n\n---\n*Reported by Discord user: {interaction.user.name}*"
            res = await create_github_issue("open-neuromorphic", self.repo_name, self.issue_title.value, body_content)
            await interaction.edit_original_response(
                content=f"✅ Issue created successfully!\nLink: {res.get('html_url', '#')}")
        except Exception as e:
            await report_error(interaction, e, "Failed to create issue")


class CreateIssueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🌐 Website Ticket", style=discord.ButtonStyle.primary, custom_id="btn_issue_website")
    async def btn_website(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IssueModal("open-neuromorphic.github.io"))

    @discord.ui.button(label="📢 Communications Ticket", style=discord.ButtonStyle.secondary, custom_id="btn_issue_comms")
    async def btn_comms(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(IssueModal("communications"))


class GithubProjectsCog(commands.GroupCog, group_name="onm-project", group_description="GitHub Project Management"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("GithubProjectsCog loaded.")

    @app_commands.command(name="my-issues", description="List open issues assigned to you across our repositories.")
    @app_commands.choices(repo=REPO_CHOICES)
    @require_clearance("volunteer_technical", guild_only=True)
    async def my_issues(self, interaction: discord.Interaction, repo: app_commands.Choice[str]):
        try:
            await interaction.response.defer(ephemeral=True)
            github_handle = get_github_handle_for_discord(interaction.user.name)

            if not github_handle:
                return await interaction.followup.send(
                    f"❌ I don't know your GitHub handle. Please ensure your Discord handle (`{interaction.user.name}`) and GitHub username are mapped in the entity glossary.")

            query = f"repo:open-neuromorphic/{repo.value} is:issue is:open assignee:{github_handle}"
            issues = await search_issues(query)

            if not issues:
                return await interaction.followup.send(
                    f"🎉 No open issues assigned to you (`@{github_handle}`) in `{repo.name}`!")

            embed = discord.Embed(title=f"Your Open Issues - {repo.name}",
                                  description=f"Assigned to **@{github_handle}**", color=discord.Color.blue())
            for issue in issues[:10]:
                embed.add_field(name=f"#{issue.number}: {issue.title}", value=f"[View Issue]({issue.html_url})",
                                inline=False)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await report_error(interaction, e, "Error fetching issues")

    @app_commands.command(name="list-issues", description="List recent open issues for a repository.")
    @app_commands.choices(repo=REPO_CHOICES)
    @require_clearance("volunteer_technical", guild_only=True)
    async def list_issues(self, interaction: discord.Interaction, repo: app_commands.Choice[str]):
        try:
            await interaction.response.defer(ephemeral=True)
            query = f"repo:open-neuromorphic/{repo.value} is:issue is:open"
            issues = await search_issues(query)

            if not issues:
                return await interaction.followup.send(f"No open issues found in `{repo.name}`!")

            embed = discord.Embed(title=f"Recent Open Issues - {repo.name}", color=discord.Color.orange())
            for issue in issues[:10]:
                author = issue.user.login if issue.user else 'Unknown'
                embed.add_field(name=f"#{issue.number}: {issue.title} (@{author})",
                                value=f"[View Issue]({issue.html_url})", inline=False)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await report_error(interaction, e, "Error fetching issues")

    @app_commands.command(name="create-issue", description="Opens a dialog to create a new issue in a repository.")
    @app_commands.choices(repo=REPO_CHOICES)
    @require_clearance("volunteer_technical", guild_only=True)
    async def create_issue(self, interaction: discord.Interaction, repo: app_commands.Choice[str] = None):
        if repo:
            # Bypass menu, go straight to form
            await interaction.response.send_modal(IssueModal(repo.value))
        else:
            # Show interactive button menu
            view = CreateIssueView()
            await interaction.response.send_message("Select a repository to create a ticket for:", view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GithubProjectsCog(bot))