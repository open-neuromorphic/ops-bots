import discord
import logging
import asyncio
from datetime import datetime, timezone, timedelta

import config
from models.onr import ArxivPaper, ONRState
from services.state_store import TypedStateStore
from services.arxiv import format_license_uri
from pipeline.onr.scraper import fetch_and_filter_new_papers
from pipeline.onr.handoff import compile_handoff_bundle, render_discussion_markdown
from utils.discord_utils import text_to_file

logger = logging.getLogger(__name__)

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

    if posted_papers:
        embed = discord.Embed(
            title="📡 New neuromorphic research",
            description=(
                f"Click the **\"Jump to Abstract & Vote\"** links below to view details and react with 🔥 to open a {config.ONR_DISCUSSION_HOURS}-hour community discussion thread!\n\n"
            ),
            color=discord.Color.teal()
        )

        for paper, msg in posted_papers:
            authors_str = ", ".join(paper.authors)
            pdf_part = f" | 📄 [Read PDF](<{paper.pdf_url}>)" if paper.pdf_url else ""

            chunk = (
                f"**{paper.title}**\n"
                f"👥 *{authors_str}*\n"
                f"🔗 [Jump to Abstract & Vote](<{msg.jump_url}>){pdf_part}\n\n"
            )

            if len(embed.description) + len(chunk) > 4000:
                embed.description += "**...and more! (Scroll up to view all papers)**\n"
                break

            embed.description += chunk

        for chan_name in config.ONR_DIGEST_CHANNELS:
            digest_chan = discord.utils.get(guild.text_channels, name=chan_name)
            if digest_chan:
                try:
                    await digest_chan.send(embed=embed)
                    logger.info(f"Successfully sent daily digest to #{chan_name}")
                except Exception as e:
                    logger.error(f"Failed to send digest to #{chan_name}: {e}")
            else:
                logger.warning(
                    f"Digest channel '#{chan_name}' not found. Does the bot have 'View Channel' permission for it?")

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
    await onr_stats_store.put_async(paper.arxiv_id, state)
    return msg


async def open_active_thread(state: ONRState, msg: discord.Message, paper: ArxivPaper, fires: int):
    thread_name = f"Discussion: {paper.title[:50]}"
    thread = await msg.create_thread(name=thread_name, auto_archive_duration=10080)
    await thread.send(
        f"💬 **Discussion opened!** You have exactly {config.ONR_DISCUSSION_HOURS} hours to review and discuss this paper. After {config.ONR_DISCUSSION_HOURS} hours, this thread will be locked, logged, and sent to the moderation team for review.")

    state.status = "active"
    state.thread_id = thread.id
    state.thread_created_at = datetime.now(timezone.utc).isoformat()
    state.thumbs_up = fires
    await onr_stats_store.put_async(state.arxiv_id, state)

    announce_embed = discord.Embed(
        title="📡 New Research Discussion Opened!",
        description=(
            f"**Paper:** *{paper.title}*\n\n"
            f"**Discussion Thread:** {thread.mention}\n\n"
            f"Come join the conversation and share your thoughts!\n"
            f"*(This discussion will be closed and logged after {config.ONR_DISCUSSION_HOURS} hours)*"
        ),
        color=discord.Color.teal()
    )

    rev_channel = discord.utils.get(msg.guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
    if rev_channel:
        try:
            await rev_channel.send(embed=announce_embed)
        except Exception as e:
            logger.error(f"Failed to send thread announcement to reviewers channel: {e}")

    for chan_name in config.ONR_DIGEST_CHANNELS:
        if chan_name in [config.ONR_RESEARCH_CHANNEL, config.ONR_REVIEWERS_CHANNEL]:
            continue

        cta_chan = discord.utils.get(msg.guild.text_channels, name=chan_name)
        if cta_chan:
            try:
                await cta_chan.send(embed=announce_embed)
            except Exception as e:
                logger.error(f"Failed to send thread announcement to {chan_name}: {e}")

    try:
        for reaction in msg.reactions:
            if str(reaction.emoji) == "🔥":
                async for user in reaction.users():
                    if not user.bot:
                        try:
                            dm_msg = (
                                f"🔥 **Discussion Opened!**\n"
                                f"A paper you voted for, **{paper.title}**, has reached the engagement threshold!\n"
                                f"The community discussion thread is now open for the next {config.ONR_DISCUSSION_HOURS} hours.\n\n"
                                f"Your input is highly welcomed: {thread.jump_url}"
                            )
                            await user.send(dm_msg)
                        except discord.Forbidden:
                            logger.debug(f"Could not DM {user.name}, DMs disabled.")
    except Exception as e:
        logger.error(f"Error sending DMs to voters for {paper.arxiv_id}: {e}")


async def process_state_machine(channel: discord.TextChannel) -> int:
    processed_count = 0
    now = datetime.now(timezone.utc)
    all_states = await onr_stats_store.list_all_async()

    for state in all_states:
        if state.arxiv_id == "latest_paper": continue
        if state.status in ["completed", "expired", "submitted", "rejected"]: continue

        try:
            msg = await channel.fetch_message(state.message_id)
        except discord.NotFound:
            continue

        fires = next((r.count - 1 for r in msg.reactions if str(r.emoji) == "🔥"), 0)
        state.thumbs_up = max(0, fires)
        paper = await onr_papers_store.get_async(state.arxiv_id)
        if not paper: continue

        if state.status == "proposed":
            proposed_dt = datetime.fromisoformat(state.proposed_at.replace('Z', '+00:00'))
            if state.thumbs_up >= config.ONR_THRESHOLD_UPVOTES:
                await open_active_thread(state, msg, paper, fires)
            elif now > proposed_dt + timedelta(days=config.ONR_PROPOSAL_DAYS):
                state.status = "expired"
                await onr_stats_store.put_async(state.arxiv_id, state)
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

        elif state.status == "active" and state.thread_created_at:
            created_dt = datetime.fromisoformat(state.thread_created_at.replace('Z', '+00:00'))
            if now >= created_dt + timedelta(hours=config.ONR_DISCUSSION_HOURS):
                try:
                    thread = await channel.guild.fetch_channel(state.thread_id)

                    msgs = [m async for m in thread.history(limit=None, oldest_first=True)]
                    user_msgs = [m for m in msgs if not m.author.bot]

                    state.participants = list(set([m.author.name for m in user_msgs]))
                    state.thread_messages = len(user_msgs)

                    if not user_msgs:
                        await thread.send("⏰ **Time is up!** No community discussion occurred in this thread. Archiving without review.")
                        await thread.edit(archived=True, locked=True)
                        state.status = "expired"
                    else:
                        await thread.send("⏰ **Time is up!** Logging this discussion for the Research Registry...")
                        await thread.edit(archived=True, locked=True)

                        handoff_path, metrics, discussion_log = compile_handoff_bundle(paper, state, user_msgs)

                        rev_channel = discord.utils.get(channel.guild.text_channels, name=config.ONR_REVIEWERS_CHANNEL)
                        if rev_channel:
                            md_text = render_discussion_markdown(paper, state, metrics, discussion_log)
                            md_file = text_to_file(md_text, f"{paper.arxiv_id}_discussion.md")

                            await rev_channel.send(
                                content=(
                                    f"🚨 **New ONR Handoff Ready!**\n"
                                    f"**Paper:** {paper.title}\n"
                                    f"**Engagement:** {state.thumbs_up} 🔥 | {state.thread_messages} 💬\n"
                                    f"**Projected Tier:** {'🥇' if metrics.onr_tier == 'Gold' else '🥈'} {metrics.onr_tier}\n\n"
                                    f"The {config.ONR_DISCUSSION_HOURS}-hour discussion window has closed. The thread data has been compiled and saved to disk.\n"
                                    f"*(Awaiting moderation review...)*"
                                ),
                                file=md_file
                            )
                        state.status = "completed"
                except discord.NotFound:
                    logger.warning(f"Thread {state.thread_id} missing, marking expired.")
                    state.status = "expired"

                await onr_stats_store.put_async(state.arxiv_id, state)

        processed_count += 1

        # Yield to event loop to prevent heartbeat blocking on large cache sizes
        await asyncio.sleep(0)

    return processed_count