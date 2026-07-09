import math
import io


def score_activity(user_message_data: dict, min_effective_ratio: float, target_avg_length: int,
                   length_impact_factor: float, num_users: int) -> list[tuple]:
    """Applies ranking formula to user message data to surface high-quality contributors."""
    user_scores = {
        uid: (data['count'] * math.pow(
            max(min_effective_ratio, (data['total_length'] / max(1, data['count'])) / max(1, target_avg_length)),
            length_impact_factor
        ))
        for uid, data in user_message_data.items()
    }
    return sorted([item for item in user_scores.items() if item[1] > 0], key=lambda item: item[1], reverse=True)[
        :num_users]


def build_social_digest_report(guild_name: str, days_lookback: int, top_user_ids: list[tuple], user_message_data: dict,
                               max_messages_per_user: int, include_reply_context: bool, names_dict: dict) -> str:
    """Formats the raw user message data and scores into a markdown report."""
    report_io = io.StringIO()
    report_io.write(
        f"Activity Digest for Server: {guild_name}\nPeriod: Last {days_lookback} days\n============================================================\n\n")

    for user_id, score in top_user_ids:
        name = names_dict.get(user_id, f"User ID: {user_id}")
        data = user_message_data.get(user_id, {})
        report_io.write(f"--- User: {name} ---\nScore: {score:.2f} (Msgs: {data.get('count', 0)})\n\n")

        msgs = sorted(data.get('messages', []), key=lambda m: m["timestamp"])[:max_messages_per_user]
        for msg_data in msgs:
            reply_info = f"    Replying to: {msg_data['reply_to']}\n" if include_reply_context and msg_data.get(
                'reply_to') else ""
            report_io.write(
                f"[{msg_data['timestamp'].strftime('%Y-%m-%d %H:%M')}] in {msg_data['channel']}:\n{reply_info}> {msg_data['content']}\n\n")
        report_io.write("\n")

    return report_io.getvalue()