import discord
from discord.ext import commands
from discord import app_commands
import uuid
import logging
from typing import List
from pydantic import BaseModel

from utils.checks import require_clearance
from utils.discord_utils import report_error
from utils.menu_framework import (
    MenuSession, session_store, ScreenSpec, ButtonSpec,
    render_screen, MenuButton, update_menu_message
)
from utils.menu_caching import fetch_with_cache
from models.onr import ArxivPaper, ONRState
from pipeline.onr.scraper import fetch_and_filter_new_papers
from pipeline.onr.orchestrator import onr_stats_store, onr_papers_store
import config

logger = logging.getLogger(__name__)


class CachedPaperList(BaseModel):
    papers: List[ArxivPaper]


async def _fetch_recent_papers() -> CachedPaperList:
    papers = await fetch_and_filter_new_papers(
        query=config.ARXIV_CURRENT_QUERY,
        max_results=30,
        skip_cached=False,
        save_to_cache=False
    )
    return CachedPaperList(papers=papers)


def _get_number_text(index: int) -> str:
    return f"[ {index + 1} ]"


FILTER_LABELS = {
    "ALL": "All",
    "PENDING_REVIEW": "Submitted",
    "PROPOSED": "Proposed",
    "ACTIVE_DISCUSSION": "Active",
    "COMPLETED": "Completed",
    "EXPIRED": "Expired",
    "REJECTED": "Rejected"
}


async def handle_main_screen(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    session.current_screen = "MAIN"
    session_store.put(session.session_id, session)

    spec = ScreenSpec(
        content="🔍 **Open Research Explorer**\n\nSelect a module below to begin.\n\u200b",
        buttons=[
            ButtonSpec(label="📊 Community Research Review Pipeline", action="set_mode", payload="active",
                       style=discord.ButtonStyle.primary, row=0),
            ButtonSpec(label="🌐 arXiv Discovery", action="set_mode", payload="discovery",
                       style=discord.ButtonStyle.secondary, row=0),
            ButtonSpec(label="❌ Close", action="close_session", style=discord.ButtonStyle.danger, row=1)
        ]
    )
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_set_mode(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    session.data_context["mode"] = payload
    session.page = 0
    session.filter_mode = "ALL"
    await render_paper_list(interaction, session)


async def render_paper_list(interaction: discord.Interaction, session: MenuSession, force_refresh: bool = False):
    mode = session.data_context.get("mode", "discovery")
    ITEMS_PER_PAGE = 5

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    if mode == "discovery":
        cache_key = "recent_papers"

        async def fetcher():
            return await _fetch_recent_papers()

        data = await fetch_with_cache(
            cache_key=cache_key, fetch_coro=fetcher, model_cls=CachedPaperList,
            ttl_seconds=3600, force_refresh=force_refresh
        )
        papers = data.papers
        max_page = max(0, (len(papers) - 1) // ITEMS_PER_PAGE)
        session.page = max(0, min(session.page, max_page))

        start_idx = session.page * ITEMS_PER_PAGE
        page_papers = papers[start_idx:start_idx + ITEMS_PER_PAGE]

        content = f"🌐 **arXiv Discovery**\n*Recent Open-Source Papers (Page {session.page + 1}/{max_page + 1})*\n\n"
        if not papers:
            content += "*No recent open-source papers found matching query.*\n\u200b"
        else:
            for idx, paper in enumerate(page_papers):
                authors = ", ".join(paper.authors[:2]) + (" et al." if len(paper.authors) > 2 else "")
                content += f"**{_get_number_text(idx)}** **{paper.title}**\n"
                content += f"└ 👤 {authors} | 📅 {paper.published_date.split('T')[0]} | 🔗 [arXiv](<{paper.url}>)\n\n"
            content += "\u200b"

        buttons = [
            ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0),
            ButtonSpec(label="🔄 Refresh", action="refresh_papers", style=discord.ButtonStyle.primary, row=0),
            ButtonSpec(label="◀ Prev", action="paper_page_prev", style=discord.ButtonStyle.secondary, row=1,
                       disabled=(session.page == 0)),
            ButtonSpec(label="Next ▶", action="paper_page_next", style=discord.ButtonStyle.secondary, row=1,
                       disabled=(session.page >= max_page))
        ]

        for idx, paper in enumerate(page_papers):
            buttons.append(ButtonSpec(
                label=f"View {_get_number_text(idx)}", action="view_paper", payload=paper.arxiv_id,
                style=discord.ButtonStyle.success, row=2
            ))

    else:
        all_states = onr_stats_store.list_all()
        valid_states = [s for s in all_states if s.arxiv_id != "latest_paper"]

        state_counts = {k: 0 for k in FILTER_LABELS.keys()}
        for s in valid_states:
            st = s.status.upper()
            if st in state_counts:
                state_counts[st] += 1
            state_counts["ALL"] += 1

        if session.filter_mode != "ALL":
            active_states = [s for s in valid_states if s.status.upper() == session.filter_mode]
        else:
            active_states = valid_states

        active_states.sort(key=lambda s: s.proposed_at, reverse=True)
        max_page = max(0, (len(active_states) - 1) // ITEMS_PER_PAGE)
        session.page = max(0, min(session.page, max_page))

        start_idx = session.page * ITEMS_PER_PAGE
        page_states = active_states[start_idx:start_idx + ITEMS_PER_PAGE]

        current_filter_label = FILTER_LABELS.get(session.filter_mode, session.filter_mode)
        content = f"📊 **Community Research Review Pipeline**\n*Filter: {current_filter_label} ({state_counts[session.filter_mode]}) (Page {session.page + 1}/{max_page + 1})*\n\n"

        if not active_states:
            content += "*No papers found for this filter.*\n\u200b"
        else:
            guild_id = interaction.guild_id
            research_chan = discord.utils.get(interaction.guild.text_channels,
                                              name=config.ONR_RESEARCH_CHANNEL) if interaction.guild else None
            qa_chan = discord.utils.get(interaction.guild.text_channels,
                                        name=config.ONR_REVIEWERS_CHANNEL) if interaction.guild else None
            research_id = research_chan.id if research_chan else 0
            qa_id = qa_chan.id if qa_chan else 0

            for idx, state in enumerate(page_states):
                paper = onr_papers_store.get(state.arxiv_id)
                title = paper.title if paper else f"Unknown Paper ({state.arxiv_id})"
                state_label = FILTER_LABELS.get(state.status.upper(), state.status.upper())

                if state.thread_id:
                    link = f"https://discord.com/channels/{guild_id}/{state.thread_id}"
                    link_text = "🔗 Thread"
                elif state.status in ["pending_review", "rejected"]:
                    link = f"https://discord.com/channels/{guild_id}/{qa_id}/{state.message_id}"
                    link_text = "🔗 QA Post"
                else:
                    link = f"https://discord.com/channels/{guild_id}/{research_id}/{state.message_id}"
                    link_text = "🔗 Feed Post"

                content += f"**{_get_number_text(idx)}** **{title}**\n"
                content += f"└ State: `{state_label}` | 💬 {state.thread_messages} | 👥 {len(state.participants)} | 🔥 {state.thumbs_up} | [{link_text}](<{link}>)\n\n"
            content += "\u200b"

        buttons = [
            ButtonSpec(label="◀ Back", action="nav_main", style=discord.ButtonStyle.secondary, row=0),
            ButtonSpec(label="🔄 Refresh", action="refresh_papers", style=discord.ButtonStyle.primary, row=0),
            ButtonSpec(label="◀ Prev", action="paper_page_prev", style=discord.ButtonStyle.secondary, row=0,
                       disabled=(session.page == 0)),
            ButtonSpec(label="Next ▶", action="paper_page_next", style=discord.ButtonStyle.secondary, row=0,
                       disabled=(session.page >= max_page))
        ]

        filters_row_1 = ["ALL", "PENDING_REVIEW", "PROPOSED", "ACTIVE_DISCUSSION"]
        for f in filters_row_1:
            style = discord.ButtonStyle.primary if session.filter_mode == f else discord.ButtonStyle.secondary
            label_with_count = f"{FILTER_LABELS[f]} ({state_counts[f]})"
            buttons.append(ButtonSpec(label=label_with_count, action="apply_filter", payload=f, style=style, row=1))

        filters_row_2 = ["COMPLETED", "EXPIRED", "REJECTED"]
        for f in filters_row_2:
            style = discord.ButtonStyle.primary if session.filter_mode == f else discord.ButtonStyle.secondary
            label_with_count = f"{FILTER_LABELS[f]} ({state_counts[f]})"
            buttons.append(ButtonSpec(label=label_with_count, action="apply_filter", payload=f, style=style, row=2))

        for idx, state in enumerate(page_states):
            buttons.append(ButtonSpec(
                label=f"View {_get_number_text(idx)}", action="view_paper", payload=state.arxiv_id,
                style=discord.ButtonStyle.success, row=3
            ))

    session.current_screen = "PAPER_LIST"
    session_store.put(session.session_id, session)
    spec = ScreenSpec(content=content, buttons=buttons)
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_paper_page_next(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    session.page += 1
    await render_paper_list(interaction, session)


async def handle_paper_page_prev(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    session.page -= 1
    await render_paper_list(interaction, session)


async def handle_refresh_papers(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    await render_paper_list(interaction, session, force_refresh=True)


async def handle_apply_filter(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    if payload:
        session.filter_mode = payload
        session.page = 0
    await render_paper_list(interaction, session)


async def handle_view_paper(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    if not payload: return
    mode = session.data_context.get("mode", "discovery")

    paper = None
    state = None

    if mode == "discovery":
        cached_path = fetch_with_cache.__globals__["cache_get"]("recent_papers.json", subdir="menu_data")
        if cached_path:
            data = CachedPaperList.model_validate_json(cached_path.read_text(encoding="utf-8"))
            paper = next((p for p in data.papers if p.arxiv_id == payload), None)
    else:
        paper = onr_papers_store.get(payload)
        state = onr_stats_store.get(payload)

    if not paper:
        return await interaction.response.send_message("❌ Paper data not found. Cache may have expired.",
                                                       ephemeral=True)

    authors = ", ".join(paper.authors)
    content = f"📄 **{paper.title}**\n"
    content += f"**ArXiv ID:** {paper.arxiv_id} | **Published:** {paper.published_date.split('T')[0]}\n"
    content += f"**Authors:** {authors}\n"

    if state:
        state_label = FILTER_LABELS.get(state.status.upper(), state.status.upper())
        content += f"**Status:** `{state_label}`\n"
        content += f"**Metrics:** 🔥 {state.thumbs_up} | 💬 {state.thread_messages} | 👥 {len(state.participants)}\n"

    content += f"\n**Abstract:**\n```text\n{paper.summary[:1500]}{'...' if len(paper.summary) > 1500 else ''}\n```\n\u200b"

    buttons = [
        ButtonSpec(label="◀ Back to List", action="nav_list", style=discord.ButtonStyle.secondary, row=0),
        ButtonSpec(label="🔗 View on arXiv", action="noop", url=paper.url, row=0)
    ]

    if paper.pdf_url:
        buttons.append(ButtonSpec(label="📄 PDF", action="noop", url=paper.pdf_url, row=0))

    if mode == "discovery":
        buttons.append(ButtonSpec(
            label="✨ Submit to QA Pipeline", action="submit_paper", payload=paper.arxiv_id,
            style=discord.ButtonStyle.primary, row=1
        ))

    session.current_screen = "PAPER_DETAIL"
    session_store.put(session.session_id, session)
    spec = ScreenSpec(content=content, buttons=buttons)
    await update_menu_message(interaction, spec, render_screen(session, spec))


async def handle_nav_list(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    await render_paper_list(interaction, session)


async def handle_submit_paper(interaction: discord.Interaction, session: MenuSession, payload: str | None = None):
    if not payload: return
    await interaction.response.send_message(f"⚙️ Submitting paper {payload} to ONR QA pipeline...", ephemeral=True)
    onr_cog = interaction.client.get_cog("ONRResearchCog")
    if onr_cog:
        arxiv_url = f"https://arxiv.org/abs/{payload}"
        interaction.client.loop.create_task(onr_cog.submit.callback(onr_cog, interaction, arxiv_url))


class ResearchMenuCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("ResearchMenuCog loaded.")
        self.bot.add_dynamic_items(MenuButton)

        if not hasattr(self.bot, "menu_registry"):
            self.bot.menu_registry = {}

        self.bot.menu_registry.update({
            "nav_main": handle_main_screen,
            "nav_list": handle_nav_list,
            "set_mode": handle_set_mode,
            "paper_page_next": handle_paper_page_next,
            "paper_page_prev": handle_paper_page_prev,
            "refresh_papers": handle_refresh_papers,
            "apply_filter": handle_apply_filter,
            "view_paper": handle_view_paper,
            "submit_paper": handle_submit_paper,
        })

    @app_commands.command(name="onm-research",
                          description="Interactive ONR Research Explorer (List/Detail Paradigm).")
    @require_clearance("volunteer_technical", guild_only=True)
    async def research_menu(self, interaction: discord.Interaction):
        try:
            session = MenuSession(
                session_id=str(uuid.uuid4())[:8],
                bot_id="onm-research",
                owner_id=interaction.user.id
            )
            session_store.put(session.session_id, session)

            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await handle_main_screen(interaction, session)
        except Exception as e:
            await report_error(interaction, e, "Failed to launch research menu")


async def setup(bot: commands.Bot):
    await bot.add_cog(ResearchMenuCog(bot))