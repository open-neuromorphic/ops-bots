import logging
from pathlib import Path
import config
from models.onr import ArxivPaper, ONRState, ONRHandoffBundle, ONRMetrics, ONRDiscussionMessage, ParticipantIdentity
from models.meta import load_entity_glossary, EntityEntry, VerificationStatus

logger = logging.getLogger(__name__)


def determine_tier(license_uri: str) -> str:
    if not license_uri: return "Unknown"
    uri_lower = license_uri.lower()
    if "-nc" in uri_lower or "-nd" in uri_lower or "nonexclusive" in uri_lower:
        return "Silver"
    if "creativecommons.org" in uri_lower or "publicdomain" in uri_lower or "mit" in uri_lower or "apache" in uri_lower:
        return "Gold"
    return "Unknown"


def compile_handoff_bundle(paper: ArxivPaper, state: ONRState, messages: list) -> tuple[
    Path, ONRMetrics, list[ONRDiscussionMessage]]:
    tier = determine_tier(paper.license)

    glossary = load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")
    participant_identities = []

    for handle in state.participants:
        handle_lower = handle.lower()
        identity = ParticipantIdentity(
            discord_handle=handle,
            canonical_name=handle,
            social_links={}
        )

        for key, data in glossary.items():
            if isinstance(data, EntityEntry):
                known_handles = [h.lower() for h in data.discord_handles]
                if handle_lower in known_handles:
                    if data.verification_status == VerificationStatus.VERIFIED:
                        identity.canonical_name = data.canonical_name or handle
                        identity.social_links = data.social_links
                    break

        participant_identities.append(identity)

    metrics = ONRMetrics(
        flame_count=state.thumbs_up,
        comment_count=len(messages),
        onr_tier=tier,
        participants_discord_handles=state.participants,
        participant_identities=participant_identities
    )

    discussion_log = []
    for m in messages:
        discussion_log.append(ONRDiscussionMessage(
            author=m.author.name,
            timestamp=m.created_at.isoformat(),
            content=m.clean_content
        ))

    bundle = ONRHandoffBundle(
        paper_metadata=paper.model_dump(),
        metrics=metrics,
        discussion_log=discussion_log
    )

    out_dir = Path(config.ONR_HANDOFF_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{paper.arxiv_id}.json"

    out_file.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return out_file, metrics, discussion_log


def render_discussion_markdown(paper: ArxivPaper, state: ONRState, metrics: ONRMetrics,
                               discussion_log: list[ONRDiscussionMessage]) -> str:
    lines = [
        f"# {paper.title}\n",
        f"**arXiv:** [{paper.arxiv_id}]({paper.url}) · **Published:** {paper.published_date.split('T')[0]}",
        f"**Authors:** {', '.join(paper.authors)}",
        f"**License:** {paper.license} ({metrics.onr_tier} tier)",
        f"**Discussion window:** {state.thread_created_at or 'Unknown'} ({config.ONR_DISCUSSION_HOURS}h)\n",
        "## Engagement",
        f"- 🔥 {metrics.flame_count}   💬 {metrics.comment_count}   👥 {len(state.participants)} participants\n",
        "## Abstract",
        f"{paper.summary}\n",
        "## Discussion Log\n"
    ]

    for msg in discussion_log:
        lines.append(f"**{msg.author}** — {msg.timestamp}")
        lines.append(f"{msg.content}\n")

    return "\n".join(lines)


def generate_engagement_report(active_states: list[ONRState], papers: dict[str, ArxivPaper], days: int) -> str:
    sorted_stats = sorted(active_states, key=lambda s: s.thumbs_up + s.thread_messages, reverse=True)

    lines = [
        f"# ONR Alpha Engagement Report (Last {days} Days)",
        f"Thresholds: 👍 {config.ONR_THRESHOLD_UPVOTES} (Triggers 24h timer)\n"
    ]

    if not sorted_stats:
        lines.append("*No active papers tracked in this timeframe.*")
        return "\n".join(lines)

    for stat in sorted_stats:
        paper = papers.get(stat.arxiv_id)
        title = paper.title if paper else "Unknown Title"
        lines.append(f"### {title[:80]}...")
        lines.append(f"**ID:** {stat.arxiv_id} | **Status:** {stat.status.upper()}")
        lines.append(f"**Engagement:** 👍 {stat.thumbs_up} | 💬 {stat.thread_messages}")
        lines.append(f"**License:** {paper.license if paper else 'Unknown'}")
        lines.append("---")

    return "\n".join(lines)