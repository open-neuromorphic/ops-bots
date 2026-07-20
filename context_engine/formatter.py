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