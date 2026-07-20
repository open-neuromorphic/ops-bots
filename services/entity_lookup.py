from pathlib import Path
import config
from models.meta import load_entity_glossary, EntityEntry


def _get_glossary():
    """Loads a fresh copy of the glossary to ensure immediate application of human updates."""
    return load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")


def get_github_handle_for_discord(discord_handle: str) -> str | None:
    """Looks up a user's GitHub username based on their known Discord handle."""
    glossary = _get_glossary()
    discord_handle_lower = discord_handle.lower()

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            known_handles = [h.lower() for h in data.discord_handles]
            if discord_handle_lower in known_handles:
                return data.github_username

    return None


def resolve_github_author(github_username: str) -> str:
    """Resolves a GitHub username to a canonical name, flagging unmapped entities."""
    if not github_username or github_username.lower() == "unknown":
        return "Unknown"

    glossary = _get_glossary()
    gh_lower = github_username.lower()

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            if data.github_username and data.github_username.lower() == gh_lower:
                return data.canonical_name or key

    return f"[UNMAPPED: {github_username}]"


def resolve_discord_author(discord_handle: str) -> str:
    """Resolves a Discord handle to a canonical name, flagging unmapped entities."""
    if not discord_handle:
        return "Unknown"

    glossary = _get_glossary()
    handle_lower = discord_handle.lower()

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            known_handles = [h.lower() for h in data.discord_handles]
            if handle_lower in known_handles:
                return data.canonical_name or key

    return f"[UNMAPPED: {discord_handle}]"


def resolve_git_author(name_or_email: str) -> str:
    """Resolves raw git commit authors (names or emails) against canonical properties."""
    if not name_or_email:
        return "Unknown"

    glossary = _get_glossary()
    query = name_or_email.lower()

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            if data.canonical_name and data.canonical_name.lower() == query:
                return data.canonical_name
            if data.github_username and data.github_username.lower() == query:
                return data.canonical_name or key

    return f"[UNMAPPED: {name_or_email}]"