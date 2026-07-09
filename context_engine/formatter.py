import re
from datetime import datetime, timezone

# Common token patterns (S-2)
SECRET_PATTERNS = [
    (r"ghp_[a-zA-Z0-9]{36}", "[REDACTED GITHUB PAT]"),
    (r"github_pat_[a-zA-Z0-9_]{82}", "[REDACTED GITHUB FINE-GRAINED PAT]"),
    (r"[M|N|O][a-zA-Z0-9_-]{23,27}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27,38}", "[REDACTED DISCORD TOKEN]"),
    (r"(?i)(api[_-]?key|secret|token)[\s:=]+['\"]?[a-zA-Z0-9_\-]{20,}['\"]?", "[REDACTED GENERIC SECRET]")
]


def scan_and_redact(content: str) -> tuple[str, int]:
    """Scans content for secrets, redacts them, and returns (redacted_content, total_redactions)."""
    total_redactions = 0
    for pattern, replacement in SECRET_PATTERNS:
        content, count = re.subn(pattern, replacement, content)
        total_redactions += count
    return content, total_redactions


def render_code_file(relative_path: str, content: str) -> str:
    """Renders a structured/code file inside a fenced markdown block."""
    ext = relative_path.split('.')[-1] if '.' in relative_path else 'text'
    language_map = {'py': 'python', 'js': 'javascript', 'json': 'json', 'md': 'markdown', 'yml': 'yaml'}
    lang = language_map.get(ext, ext)

    return f"## Source: {relative_path}\n\n```{lang}\n# {relative_path}\n{content}\n```\n---"


def render_text_entry(title: str, metadata: str, content: str) -> str:
    """Renders prose (transcripts, discord logs) as plain markdown."""
    return f"## {title}\n{metadata}\n\n{content}\n\n---"