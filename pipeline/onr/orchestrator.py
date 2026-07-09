import discord
import logging
from datetime import datetime, timezone, timedelta

import config
from models.onr import ArxivPaper, ONRState
from services.state_store import TypedStateStore
from services.arxiv import format_license_uri
from pipeline.onr.scraper import fetch_and_filter_new_papers
from pipeline.onr.handoff import compile_handoff_bundle

logger = logging.getLogger(__name__)

# Core stores used across the ONR pipeline
onr_stats_store = TypedStateStore(ONRState, "researchbot/onr_stats")
onr_papers_store = TypedStateStore(ArxivPaper, "researchbot/onr_papers")

OPEN_ACCESS_POLICY_MSG = (
    "❌ **Proprietary Paper Rejected**\n"
    "This resource is not published under an approved open-access license. Proprietary or default arXiv-only licenses are not shared to the community channel or tracked for engagement.\n\n"
    "**Open Neuromorphic Open Definition:**\n"
    "> We prioritize permissive licenses like **CC BY**, **CC BY-SA**, **MIT**, and **Apache 2.0**.\n"
    "> While we still value and accept resources with Non-Commercial (NC) or No-Derivatives (ND) clauses, we strongly encourage full open access to allow the community to freely build upon your work.\n\n"
    "📖 [Read our full Open Definition Policy](https://open-neuromorphic.org/about/governance/open-definition/)"
)


def format_date_with_days_ago(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        days_ago = (datetime.now(timezone.utc) - dt).days
        date_only = date_str.split("T")[0]
        if days_ago == 0:
            return f"{date_only} (Today)"
        elif days_ago == 1:
            return f"{date_only} (1 day ago)"
        else:
            return f"{date_only} ({days_ago} days ago)"
    except Exception:
        return date_str.split("T")[0]


def get_license_display(license_uri: str, is_open: bool) -> str:
    formatted = format_license_uri(license_uri)
    if is_open:
        if license_uri and ("-nc" in license_uri.lower() or "-nd" in license_uri.lower()):
            return f"⚠️ Restricted (**{formatted}**)"
        return f"✅ Open (**{formatted}**)"
    return f"❌ Closed (**{formatted}**)"


async def run_sync_pipeline(bot: discord.Client) -> tuple[int, int]:
    guild = bot.get_guild(config.DISCORD_GUILD_ID)
    if not guild: return 0, 0
    channel = discord.utils.get(guild.text_channels, name=config.ONR_RESEARCH_CHANNEL)
    if not channel:
        logger.warning(f"Target ONR channel '{config.ONR_RESEARCH_CHANNEL}' not found.")
        return 0, 0

    posted_papers = []
    try:
        new_papers = await fetch_and_filter_new_papers(query=config.ARXIV_CURRENT_QUERY, max_results=50,
                                                       skip_cached=True)
        for paper in new_papers:
            msg = await post_paper_to_channel(channel, paper)
            posted_papers.append((paper, msg))
    except Exception as e:
        logger.error(f"Error fetching new arXiv papers: {e}")

    # Emit an aggregated digest index when a batch of papers is newly posted
    if posted_papers:
        digest_lines = [
            "📚 **New arXiv Publications Discovered!** 📚",
            "",
            "A fresh batch of open-source papers matching our definition has been posted below.",
            f"React with 🔥 on the original posts if you would like to open a {config.ONR_DISCUSSION_HOURS}-hour community discussion thread!",
            ""
        ]
        for paper, msg in posted_papers:
            authors_str = ", ".join(paper.authors[:2]) + (" et al." if len(paper.authors) > 2 else "")
            digest_lines.append(f"- **[{paper.title}](<{msg.jump_url}>)** by *{authors_str}*")

        digest_msg = "\n".join(digest_lines)

        # Post summary index to main research channel
        try:
            await channel.send(digest_msg)
        except Exception as e:
            logger.error(f"Failed to send digest to research channel: {e}")

        # Post copy to moderator channel for validation
        rev_channel = discord.utils.get(guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
        if rev_channel:
            try:
                await rev_channel.send(
                    f"📢 **arXiv Discovery Batch Digest (Moderator Copy)**\n\n{digest_msg}"
                )
            except Exception as e:
                logger.error(f"Failed to send digest to reviewers channel: {e}")

    updated_count = 0
    try:
        updated_count = await process_state_machine(channel)
    except Exception as e:
        logger.error(f"Error executing state machine: {e}")

    return len(posted_papers), updated_count


async def post_paper_to_channel(channel: discord.TextChannel, paper: ArxivPaper) -> discord.Message:
    embed = discord.Embed(
        title=paper.title, url=paper.url,
        description=f"**Abstract:**\n{paper.summary[:2000]}\n\n*React with {config.ONR_THRESHOLD_UPVOTES} 🔥 to open a {config.ONR_DISCUSSION_HOURS}-hour community discussion thread!*",
        color=discord.Color.teal()
    )
    embed.add_field(name="Authors", value=", ".join(paper.authors[:5]), inline=False)
    embed.add_field(name="Published", value=format_date_with_days_ago(paper.published_date), inline=True)
    embed.add_field(name="License", value=get_license_display(paper.license, paper.is_open_license), inline=True)
    if paper.pdf_url: embed.add_field(name="PDF", value=f"[View PDF]({paper.pdf_url})", inline=True)
    embed.set_footer(text=f"ArXiv ID: {paper.arxiv_id}")

    msg = await channel.send(embed=embed)
    await msg.add_reaction("🔥")

    state = ONRState(
        arxiv_id=paper.arxiv_id, status="proposed",
        message_id=msg.id, proposed_at=datetime.now(timezone.utc).isoformat()
    )
    onr_stats_store.put(paper.arxiv_id, state)
    return msg


async def open_active_thread(state: ONRState, msg: discord.Message, paper: ArxivPaper, fires: int):
    thread_name = f"Discussion: {paper.title[:50]}"
    thread = await msg.create_thread(name=thread_name, auto_archive_duration=10080)
    await thread.send(
        f"💬 **Discussion opened!** You have exactly {config.ONR_DISCUSSION_HOURS} hours to review and discuss this paper. After {config.ONR_DISCUSSION_HOURS} hours, this thread will be locked, logged, and sent to the QA team for website publication.")

    state.status = "active_discussion"
    state.thread_id = thread.id
    state.thread_created_at = datetime.now(timezone.utc).isoformat()
    state.thumbs_up = fires
    onr_stats_store.put(state.arxiv_id, state)

    # Announce thread activation to the moderation channel
    rev_channel = discord.utils.get(msg.guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
    if rev_channel:
        try:
            await rev_channel.send(
                f"📢 **A new research discussion thread has opened!**\n"
                f"**Paper:** *{paper.title}*\n"
                f"**Discussion Thread:** {thread.mention}\n"
                f"Come join the conversation and share your thoughts!"
            )
        except Exception as e:
            logger.error(f"Failed to send thread announcement to reviewers channel: {e}")


async def process_state_machine(channel: discord.TextChannel) -> int:
    processed_count = 0
    now = datetime.now(timezone.utc)
    all_states = onr_stats_store.list_all()

    for state in all_states:
        if state.arxiv_id == "latest_paper": continue
        if state.status in ["completed", "expired", "pending_review", "rejected"]: continue

        try:
            msg = await channel.fetch_message(state.message_id)
        except discord.NotFound:
            continue

        fires = next((r.count - 1 for r in msg.reactions if str(r.emoji) == "🔥"), 0)
        state.thumbs_up = max(0, fires)
        paper = onr_papers_store.get(state.arxiv_id)
        if not paper: continue

        if state.status == "proposed":
            proposed_dt = datetime.fromisoformat(state.proposed_at.replace('Z', '+00:00'))
            if state.thumbs_up >= config.ONR_THRESHOLD_UPVOTES:
                await open_active_thread(state, msg, paper, fires)
            elif now > proposed_dt + timedelta(days=config.ONR_PROPOSAL_DAYS):
                state.status = "expired"
                onr_stats_store.put(state.arxiv_id, state)
                try:
                    kwargs = {
                        "content": "⌛ **Voting window closed.** This paper did not reach the engagement threshold to open a thread."}
                    if msg.embeds:
                        embed = msg.embeds[0]
                        embed.color = discord.Color.dark_grey()
                        embed.set_footer(text="Voting window closed (Expired).")
                        kwargs["embed"] = embed
                    await msg.edit(**kwargs)
                    await msg.clear_reactions()
                except Exception as e:
                    logger.warning(f"Could not update expired message UI for {state.arxiv_id}: {e}")

        elif state.status == "active_discussion" and state.thread_created_at:
            created_dt = datetime.fromisoformat(state.thread_created_at.replace('Z', '+00:00'))
            if now >= created_dt + timedelta(hours=config.ONR_DISCUSSION_HOURS):
                try:
                    thread = await channel.guild.fetch_channel(state.thread_id)
                    await thread.send("⏰ **Time is up!** Logging this discussion for the Research Registry...")
                    await thread.edit(archived=True, locked=True)

                    msgs = [m async for m in thread.history(limit=None, oldest_first=True)]
                    user_msgs = [m for m in msgs if not m.author.bot]

                    state.participants = list(set([m.author.name for m in user_msgs]))
                    state.thread_messages = len(user_msgs)

                    handoff_path, metrics = compile_handoff_bundle(paper, state, user_msgs)

                    rev_channel = discord.utils.get(channel.guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
                    if rev_channel:
                        await rev_channel.send(
                            f"🚨 **New ONR Handoff Ready!**\n"
                            f"**Paper:** {paper.title}\n"
                            f"**Engagement:** {state.thumbs_up} 🔥 | {state.thread_messages} 💬\n"
                            f"**Projected Tier:** {'🥇' if metrics.onr_tier == 'Gold' else '🥈'} {metrics.onr_tier}\n\n"
                            f"The {config.ONR_DISCUSSION_HOURS}-hour discussion window has closed. The thread data has been compiled and saved to disk.\n"
                            f"*(Awaiting LLM synthesis / PR generation pipeline...)*"
                        )
                    state.status = "completed"
                except discord.NotFound:
                    logger.warning(f"Thread {state.thread_id} missing, marking expired.")
                    state.status = "expired"

                onr_stats_store.put(state.arxiv_id, state)

        processed_count += 1

    return processed_count