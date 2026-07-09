import io
from datetime import datetime, timezone


def build_leadership_digest(messages_data: list[dict], guild_name: str, period_description: str) -> str:
    """Transforms raw message dictionaries into a formatted printable digest string."""
    report_content = io.StringIO()
    report_content.write(
        f"Leadership Channel Digest for: {guild_name}\n"
        f"Report Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"Messages from: {period_description}\n"
        "============================================================\n\n"
    )

    for msg in messages_data:
        content = msg['content']
        if msg['attachments']:
            content += f" [Attached: {', '.join(msg['attachments'])}]"
        report_content.write(f"[{msg['timestamp']}] {msg['author']}:\n{content}\n\n")

    report_content.write(f"--- End of Digest | {len(messages_data)} messages found ---\n")
    return report_content.getvalue()