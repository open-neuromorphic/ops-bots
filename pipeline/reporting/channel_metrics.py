from collections import defaultdict
from datetime import datetime, timezone, timedelta
from utils.template import render_template


def build_channel_topics_report(channels_data: list[dict], guild_name: str, scanned_channels: int,
                                skipped_channels: int) -> str:
    """Groups channel data and renders the final markdown report."""
    grouped_with_topics = defaultdict(list)
    grouped_without_topics = defaultdict(list)
    with_topics_count, without_topics_count = 0, 0

    for chan in channels_data:
        cat = chan['category']
        if chan['topic']:
            grouped_with_topics[cat].append({"name": chan['name'], "topic": chan['topic']})
            with_topics_count += 1
        else:
            grouped_without_topics[cat].append({"name": chan['name']})
            without_topics_count += 1

    return render_template(
        "reports/channel_topics.j2",
        guild_name=guild_name,
        generated_at=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z'),
        channels_without_topics=dict(sorted(grouped_without_topics.items())),
        channels_with_topics=dict(sorted(grouped_with_topics.items())),
        scanned_channels=scanned_channels,
        with_topics_count=with_topics_count,
        without_topics_count=without_topics_count,
        skipped_channels=skipped_channels
    )


def build_inactive_channels_report(channel_data: list[dict], days_inactive: int) -> tuple[str, int]:
    """Filters channels by inactivity cutoff, groups them, and formats the text report."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_inactive)
    grouped = defaultdict(list)
    count = 0

    for c in channel_data:
        dt = c["last_active_dt"]
        if not dt or dt < cutoff_date:
            grouped[c["category"]].append({
                "name": c["name"],
                "last_active": dt.strftime("%Y-%m-%d") if dt else "Never"
            })
            count += 1

    report_str = f"Inactive Channels Report (> {days_inactive} days)\n" + "=" * 50 + "\n"
    for cat, chans in sorted(grouped.items()):
        report_str += f"\n--- {cat} ---\n"
        for c in chans:
            report_str += f"#{c['name']} (Last active: {c['last_active']})\n"
    return report_str, count