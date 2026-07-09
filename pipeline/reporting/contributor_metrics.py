from collections import Counter
from datetime import datetime
import io

def process_contributor_counts(all_relevant_messages: list[tuple[int, datetime]], threshold_7_days: datetime, threshold_30_days: datetime) -> tuple[dict, dict, dict]:
    """Buckets raw message timestamps into time-period metrics."""
    counts_7_days, counts_30_days, counts_365_days = Counter(), Counter(), Counter()
    for author_id, msg_timestamp in all_relevant_messages:
        counts_365_days[author_id] += 1
        if msg_timestamp >= threshold_30_days: counts_30_days[author_id] += 1
        if msg_timestamp >= threshold_7_days: counts_7_days[author_id] += 1
    return dict(counts_7_days), dict(counts_30_days), dict(counts_365_days)

def build_contributor_report(guild_name: str, now_utc_for_report: datetime, using_cache: bool, cache_age_minutes: int, counts_7_days: dict, counts_30_days: dict, counts_365_days: dict, processed_items_count: int, skipped_items_count: int, limit: int, names_dict: dict) -> str:
    """Formats the raw bucketed counts into a text report."""
    report_content = io.StringIO()
    report_content.write(f"Top Message Contributors Report for Server: {guild_name}\nReport Generated: {now_utc_for_report.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
    report_content.write(f"(Data from cache, age: {cache_age_minutes} minutes)\n" if using_cache else f"(Data based on a fresh scan completed at {now_utc_for_report.strftime('%Y-%m-%d %H:%M:%S %Z')})\n")
    report_content.write("============================================================\n\n")

    def _add_period(period_title: str, counts_dict: dict):
        report_content.write(f"--- {period_title} (Top {limit}) ---\n")
        sorted_contributors = Counter(counts_dict).most_common(limit)
        if not sorted_contributors:
            report_content.write("No activity found for this period.\n\n")
            return
        for i, (user_id, count) in enumerate(sorted_contributors):
            name = names_dict.get(int(user_id), f"Unknown User (ID: {user_id})")
            report_content.write(f"{i + 1}. {name} - {count} messages\n")
        report_content.write("\n")

    _add_period("Activity - Last 7 Days", counts_7_days)
    _add_period("Activity - Last 30 Days", counts_30_days)
    _add_period("Activity - Last 365 Days", counts_365_days)

    report_content.write(f"--- Scan Summary ---\nProcessed {processed_items_count} items.\nSkipped {skipped_items_count} items.\n--- End of Report ---\n")
    return report_content.getvalue()