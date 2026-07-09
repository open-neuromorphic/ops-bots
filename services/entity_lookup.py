from pathlib import Path
import config
from models.meta import load_entity_glossary, EntityEntry


def get_github_handle_for_discord(discord_handle: str) -> str | None:
    """Looks up a user's GitHub username based on their known Discord handle."""
    glossary = load_entity_glossary(Path(config.META_DIR) / "entity_glossary.json")
    discord_handle_lower = discord_handle.lower()

    for key, data in glossary.items():
        if isinstance(data, EntityEntry):
            known_handles = [h.lower() for h in data.discord_handles]
            if discord_handle_lower in known_handles:
                return data.github_username

    return None