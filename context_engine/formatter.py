import re

SECRET_PATTERNS = [
    (r"ghp_[a-zA-Z0-9]{36}", "[REDACTED GITHUB PAT]"),
    (r"github_pat_[a-zA-Z0-9_]{82}", "[REDACTED GITHUB FINE-GRAINED PAT]"),
    (r"[M|N|O][a-zA-Z0-9_-]{23,27}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27,38}", "[REDACTED DISCORD TOKEN]"),
    (r"(?i)(api[_-]?key|secret|token)[\s:=]+['\"]?[a-zA-Z0-9_\-]{20,}['\"]?", "[REDACTED GENERIC SECRET]")
]

def scan_and_redact(content: str) -> tuple[str, int]:
    total_redactions = 0
    for pattern, replacement in SECRET_PATTERNS:
        content, count = re.subn(pattern, replacement, content)
        total_redactions += count
    return content, total_redactions

def normalize_crlf(content: str) -> str:
    """Normalizes CRLF to LF to prevent hidden token bloat."""
    return content.replace("\r\n", "\n")

def escape_xml(text: str) -> str:
    """Escapes strings for placement within standard XML attribute definitions."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def cdata_wrap(text: str) -> str:
    """Safely encapsulates raw blocks inside an XML CDATA node."""
    if not text: return "<![CDATA[]]>"
    return f"<![CDATA[\n{text.replace(']]>', ']]&gt;')}\n]]>"

def strip_empty_templates(content: str, path: str) -> str:
    """Substitutes largely empty structural template files with a token-efficient empty XML tag reference."""
    if "template" in path.lower() and len(content.strip()) < 500:
        return f'<template_reference path="{escape_xml(path)}" status="empty" />'
    return content

def strip_boilerplate(text: str) -> str:
    """Aggressively removes PR templates, HTML comments, and automated bot injections to save tokens."""
    if not text: return ""
    # Strip HTML comments entirely (removes hidden copilot prompts)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    # Strip the standard PR template intro
    text = re.sub(r'# 📝 Pull Request Template.*?(?=## 📌)', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Strip repetitive checklist and empty screenshot sections
    text = re.sub(r'## ✅ Checklist.*?(?=## |\Z)', '', text, flags=re.DOTALL)
    text = re.sub(r'## 📸 Screenshots / Attachments \(if applicable\).*?(?=## |\Z)', '', text, flags=re.DOTALL)
    # Strip Copilot / Bot automated suffixes
    text = re.sub(r'<!-- START COPILOT CODING AGENT SUFFIX -->.*', '', text, flags=re.DOTALL)
    return text.strip()