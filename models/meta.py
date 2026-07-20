import json
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from pathlib import Path
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class ThreadHistoryNote(BaseModel):
    date: str
    note: str
    source_entry: str

class ThreadEntry(BaseModel):
    title: str
    category: Literal["engineering", "governance", "communications", "other"] = "other"
    status: Literal["active", "resolved", "archived", "paused"] = "active"
    summary: str = ""
    history: List[ThreadHistoryNote] = []
    last_updated: str
    last_updated_by_run: str
    related_entities: List[str] = []
    confidentiality_note: Optional[str] = None

class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PENDING_CHALLENGE = "pending_challenge"
    VERIFIED = "verified"

class EntityEntry(BaseModel):
    canonical_name: str = ""
    discord_handles: List[str] = []
    fathom_names: List[str] = []
    github_username: Optional[str] = None
    transcript_aliases: List[str] = []  # Added for SCO v1.6 Semantic normalizations
    role: Optional[str] = None
    notes: Optional[str] = None
    misheard_as: List[str] = []
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_token: Optional[str] = None
    social_links: Dict[str, str] = Field(default_factory=dict)

def load_threads_ledger(path: Path) -> Dict[str, ThreadEntry]:
    """Safely loads and validates the threads ledger."""
    if not path.exists():
        return {}
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        return {k: ThreadEntry.model_validate(v) for k, v in raw_data.items()}
    except Exception as e:
        logger.error(f"Error loading threads ledger from {path}: {e}")
        return {}

def load_entity_glossary(path: Path) -> Dict[str, Any]:
    """Safely loads the entity glossary. Values may be EntityEntry or dict."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        res = {}
        for k, v in raw.items():
            if k == "known_non_persons" or not isinstance(v, dict):
                res[k] = v
            else:
                res[k] = EntityEntry.model_validate(v)
        return res
    except Exception as e:
        logger.error(f"Error loading entity glossary from {path}: {e}")
        return {}