import discord
from discord.ext import commands
from discord import app_commands
import uuid
import logging
from typing import List, Tuple
from pydantic import BaseModel

from utils.checks import require_clearance
from utils.discord_utils import report_error, text_to_file
from utils.menu_framework import (
    MenuSession, session_store, ScreenSpec, ButtonSpec,
    render_screen, MenuButton, update_menu_message
)
from utils.menu_caching import fetch_with_cache
from services.github import search_issues, get_issue_comments
from models.github import GitHubIssue
from services.cache import get as cache_get, list_keys
from pipeline.pr_automation.generate_content import ContentDraft
from pipeline.pr_automation.submit_pr import calculate_preview_path
import config

logger = logging.getLogger(__name__)

class CachedIssueList(BaseModel):
    issues: List[GitHubIssue]

def _get_number_text(index: int) -> str: return f"[ {index + 1} ]"

def _get_draft_for_issue(owner: str, repo: str, issue_num: int) -> Tuple[str | None, ContentDraft | None]:
    prefix = f"{owner}-{repo}-{issue_num}_"
    for key in list_keys(subdir="pr_drafts"):
        if key.startswith(prefix) and key.endswith(".json"):
            try:
                cached_path = cache_get(key, subdir="pr_drafts")
                draft = ContentDraft.model_validate_json(cached_path.read_text(encoding="utf-8"))
                return key[:-5], draft
            except: pass
    return None, None

async def _fetch_repo_issues(repo: str) -> CachedIssueList:
    issues = await search_issues(f"repo:open-neuromorphic/{repo} is:issue is:open")
    return CachedIssueList(issues=issues)

async def render_issue_list(interaction: discord.Interaction, session: MenuSession, force_refresh: bool = False, notification: str = None):
    repo = session.data_context.get("current_repo", "open-neuromorphic.github.io")
    data = await fetch_with_cache(f"issues_{repo}", lambda: _fetch_repo_issues(repo), CachedIssueList, 300, force_refresh)

    issues = data.issues
    ITEMS_PER_PAGE = 5
    max_page = max(0, (len(issues) - 1) // ITEMS_PER_PAGE)
    session.page = max(0, min(session.page, max_page))
    session.current_screen = "ISSUE_LIST"
    session_store.put(session.session_id, session)

    start_idx = session.page * ITEMS_PER_PAGE
    page_issues = issues[start_idx:start_idx + ITEMS_PER_PAGE]

    content = f"📂 **Content Ops Pipeline**\n*Active Tickets in `{repo}` (Page {session.page + 1}/{max_page + 1})*\n\n"
    if notification: content = f"🔔 **Note:** {notification}\n\n" + content

    if not issues: content += "*No open issues found.*"
    else:
        for idx, issue in enumerate(page_issues):
            draft_id, _ = _get_draft_for_issue("open-neuromorphic", repo, issue.number)
            state_tag = "🚀 **STAGED**" if draft_id else "📝 *UNPROCESSED*"
            content += f"**{_get_number_text(idx)}** **#{issue.number}: {issue.title}**\n"
            content += f"└ State: {state_tag} | 👤 @{issue.user.login if issue.user else '??'} | 💬 {issue.comments} comments\n\n"

    buttons = [
        ButtonSpec(label="◀ Projects", action="nav_projects", style=discord.ButtonStyle.secondary, row=0),
        ButtonSpec(label="🔄 Refresh", action="refresh_issues", style=discord.ButtonStyle.primary, row=0),
        ButtonSpec(label="📥 Export Bundle", action="export_issues", style=discord.ButtonStyle.success, row=0),
        ButtonSpec(label="◀ Prev", action="page_prev", style=discord.ButtonStyle.secondary, row=1, disabled=(session.page == 0)),
        ButtonSpec(label="Next ▶", action="page_next", style=discord.ButtonStyle.secondary, row=1, disabled=(session.page >= max_page))
    ]
    for idx, issue in enumerate(page_issues):
        buttons.append(ButtonSpec(label=f"View {_get_number_text(idx)}", action="view_issue", payload=str(issue.number), style=discord.ButtonStyle.success, row=2))

    await update_menu_message(interaction, ScreenSpec(content=content, buttons=buttons), render_screen(session, ScreenSpec(content=content, buttons=buttons)))

async def handle_main_screen(interaction: discord.Interaction, session: MenuSession, p: str = None):
    session.current_screen = "MAIN"
    session_store.put(session.session_id, session)
    spec = ScreenSpec(content="👋 **Content Ops Control Panel.**", buttons=[
        ButtonSpec(label="🌐 GitHub Projects", action="nav_projects", style=discord.ButtonStyle.primary),
        ButtonSpec(label="❌ Close", action="close_session", style=discord.ButtonStyle.danger)
    ])
    await update_menu_message(interaction, spec, render_screen(session, spec))

async def handle_nav_projects(interaction: discord.Interaction, session: MenuSession, p: str = None):
    session.current_screen = "PROJECTS"
    session_store.put(session.session_id, session)
    spec = ScreenSpec(content="📂 **GitHub Projects Module**", buttons=[
        ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0),
        ButtonSpec(label="📋 Communications", action="list_repo", payload="communications", style=discord.ButtonStyle.success, row=1),
        ButtonSpec(label="📋 Website", action="list_repo", payload="open-neuromorphic.github.io", style=discord.ButtonStyle.success, row=1)
    ])
    await update_menu_message(interaction, spec, render_screen(session, spec))

async def handle_list_repo(interaction: discord.Interaction, session: MenuSession, p: str = None):
    if p: session.data_context["current_repo"] = p
    session.page = 0
    await render_issue_list(interaction, session)

async def handle_page_next(i: discord.Interaction, s: MenuSession, p: str = None):
    s.page += 1
    await render_issue_list(i, s)

async def handle_page_prev(i: discord.Interaction, s: MenuSession, p: str = None):
    s.page -= 1
    await render_issue_list(i, s)

async def handle_refresh_issues(i: discord.Interaction, s: MenuSession, p: str = None):
    await render_issue_list(i, s, force_refresh=True)

async def _bg_export(interaction: discord.Interaction, repo: str):
    try:
        issues = await search_issues(f"repo:open-neuromorphic/{repo} is:issue is:open")
        md = [f"# Open Issues Export for `{repo}`\n"]
        for issue in issues:
            md.append(f"## #{issue.number}: {issue.title}\nAuthor: @{issue.user.login}\n### Description\n{issue.body or '...'}")
            if issue.comments > 0:
                comments = await get_issue_comments("open-neuromorphic", repo, issue.number)
                md.append(f"### Comments ({len(comments)})")
                for c in comments: md.append(f"**@{c.user.login}:** {c.body}")
            md.append("---\n")
        await interaction.user.send(f"📂 Open issues for `{repo}`:", file=text_to_file("\n".join(md), f"{repo}_issues.md"))
    except Exception as e:
        logger.error(f"Export failed: {e}")

async def handle_export_issues(interaction: discord.Interaction, session: MenuSession, p: str = None):
    repo = session.data_context.get("current_repo")
    interaction.client.loop.create_task(_bg_export(interaction, repo))
    await render_issue_list(interaction, session, notification="⚙️ Exporting issues to your DMs...")

async def handle_view_issue(interaction: discord.Interaction, session: MenuSession, p: str = None):
    repo = session.data_context.get("current_repo")
    path = cache_get(f"issues_{repo}.json", subdir="menu_data")
    if not path: return await interaction.response.send_message("❌ Cache expired.", ephemeral=True)
    data = CachedIssueList.model_validate_json(path.read_text(encoding="utf-8"))
    issue = next((i for i in data.issues if str(i.number) == p), None)
    if not issue: return await interaction.response.send_message("❌ Issue not found.", ephemeral=True)

    draft_id, draft = _get_draft_for_issue("open-neuromorphic", repo, issue.number)
    state = "STAGED" if draft else "UNPROCESSED"
    body = (issue.body or 'No desc')[:800]
    content = f"🛠️ **Workstation: #{issue.number}** (`{repo}`)\n**Title:** {issue.title}\n**State:** `{state}`\n\n**Desc:**\n```text\n{body}\n```"

    buttons = [
        ButtonSpec(label="◀ Back", action="list_repo", style=discord.ButtonStyle.secondary, row=0),
        ButtonSpec(label="🔗 GitHub", action="noop", url=issue.html_url, row=0)
    ]
    if state == "UNPROCESSED":
        buttons.append(ButtonSpec(label="✨ Generate PR", action="generate_draft", payload=str(issue.number), style=discord.ButtonStyle.success, row=1))
    else:
        short_id = draft_id.split('/')[-1] if '/' in draft_id else draft_id
        buttons.append(ButtonSpec(label="✅ Publish PR", action="approve_draft", payload=short_id, style=discord.ButtonStyle.success, row=1))
        buttons.append(ButtonSpec(label="🔄 Regenerate", action="generate_draft", payload=str(issue.number), style=discord.ButtonStyle.danger, row=1))

    session.current_screen = "ISSUE_DETAIL"
    session_store.put(session.session_id, session)
    await update_menu_message(interaction, ScreenSpec(content=content, buttons=buttons), render_screen(session, ScreenSpec(content=content, buttons=buttons)))

async def handle_generate_draft(interaction: discord.Interaction, session: MenuSession, p: str = None):
    await interaction.response.send_message(f"⚙️ Generating PR for #{p}...", ephemeral=True)
    pr_cog = interaction.client.get_cog("PRAutomationCog")
    if pr_cog: interaction.client.loop.create_task(pr_cog._background_preview(interaction, "open-neuromorphic", session.data_context["current_repo"], int(p)))

async def handle_approve_draft(interaction: discord.Interaction, session: MenuSession, p: str = None):
    await interaction.response.send_message(f"🚀 Promoting `{p}` to Prod...", ephemeral=True)
    pr_cog = interaction.client.get_cog("PRAutomationCog")
    if pr_cog: interaction.client.loop.create_task(pr_cog._background_approve(interaction, p))

class ContentOpsMenuCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_dynamic_items(MenuButton)
        if not hasattr(self.bot, "menu_registry"): self.bot.menu_registry = {}
        self.bot.menu_registry.update({
            "nav_main": handle_main_screen, "nav_projects": handle_nav_projects, "list_repo": handle_list_repo,
            "page_next": handle_page_next, "page_prev": handle_page_prev, "refresh_issues": handle_refresh_issues,
            "export_issues": handle_export_issues, "view_issue": handle_view_issue,
            "generate_draft": handle_generate_draft, "approve_draft": handle_approve_draft
        })

    @app_commands.command(name="onm-content-ops", description="Content Ops Control Panel.")
    @require_clearance("volunteer_technical", guild_only=True)
    async def ops_menu(self, interaction: discord.Interaction):
        session = MenuSession(session_id=str(uuid.uuid4())[:8], bot_id="onm-content-ops", owner_id=interaction.user.id)
        session_store.put(session.session_id, session)
        if not interaction.response.is_done(): await interaction.response.defer(ephemeral=True)
        await handle_main_screen(interaction, session)

async def setup(bot: commands.Bot): await bot.add_cog(ContentOpsMenuCog(bot))