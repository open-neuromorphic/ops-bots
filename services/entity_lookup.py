import re
from pathlib import Path
import config
from models.meta import load_entity_glossary, EntityEntry


def _get_glossary():
    """Loads a fresh copy of the glossary to ensure immediate application of human updates."""
    return load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")


def normalize_entity(name: str) -> str:
    """Normalizes spacing, punctuation, and hyphens/underscores for robust matching."""
    if not name:
        return ""
    name = name.lower()
    name = name.strip(".,;:!?\"'()[]{}<> \t\n\r")
    name = name.replace("_", " ").replace("-", " ")
    # Collapse multiple spaces
    return re.sub(r'\s+', ' ', name)


def _resolve_any(raw_name: str) -> str:
    """Core resolution logic checking all glossary aliases and enforcing canonical substitution."""
    if not raw_name or raw_name.lower() in ("unknown", "ghost"):
        return "[UNMAPPED: ghost]"

    glossary = _get_glossary()
    norm_raw = normalize_entity(raw_name)

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            # Aggregate every known alias across platforms
            all_aliases = []
            if data.canonical_name: all_aliases.append(data.canonical_name)
            if data.github_username: all_aliases.append(data.github_username)
            all_aliases.extend(data.discord_handles)
            all_aliases.extend(data.fathom_names)
            all_aliases.extend(data.transcript_aliases)
            all_aliases.extend(data.misheard_as)
            all_aliases.append(key)  # Ensure the JSON key itself acts as an alias

            # Normalize aliases for comparison
            norm_aliases = [normalize_entity(a) for a in all_aliases if a]

            if norm_raw in norm_aliases:
                # Enforce Canonical Substitution
                if data.canonical_name:
                    return data.canonical_name
                # Fallback if the user forgot to set canonical_name: Title Case the key
                return key.replace("_", " ").title()

    return f"[UNMAPPED: {raw_name}]"


def get_github_handle_for_discord(discord_handle: str) -> str | None:
    """Looks up a user's GitHub username based on their known Discord handle."""
    glossary = _get_glossary()
    norm_handle = normalize_entity(discord_handle)

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            norm_handles = [normalize_entity(h) for h in data.discord_handles]
            if norm_handle in norm_handles:
                return data.github_username

    return None


def resolve_github_author(github_username: str) -> str:
    """Resolves a GitHub username to a canonical name, flagging unmapped entities."""
    return _resolve_any(github_username)


def resolve_discord_author(discord_handle: str) -> str:
    """Resolves a Discord handle to a canonical name, flagging unmapped entities."""
    return _resolve_any(discord_handle)


def resolve_git_author(name_or_email: str) -> str:
    """Resolves raw git commit authors (names or emails) against canonical properties."""
    return _resolve_any(name_or_email)