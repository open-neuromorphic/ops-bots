from pydantic import BaseModel, field_validator
from typing import List, Optional, Literal, Dict

class ArxivPaper(BaseModel):
    arxiv_id: str
    title: str
    summary: str
    authors: List[str]
    published_date: str
    url: str
    pdf_url: Optional[str] = None
    license: str
    is_open_license: bool
    submitted_by: str = "auto"

class ONRState(BaseModel):
    arxiv_id: str
    status: Literal["submitted", "proposed", "active", "completed", "expired", "rejected"] = "proposed"
    message_id: int
    thread_id: Optional[int] = None
    proposed_at: str
    thread_created_at: Optional[str] = None
    thumbs_up: int = 0
    thread_messages: int = 0
    participants: List[str] = []

    @field_validator('status', mode='before')
    @classmethod
    def _map_legacy_status(cls, v):
        if v == "pending_review": return "submitted"
        if v == "active_discussion": return "active"
        return v

class ONRDiscussionMessage(BaseModel):
    author: str
    timestamp: str
    content: str

class ParticipantIdentity(BaseModel):
    discord_handle: str
    canonical_name: str
    social_links: Dict[str, str]

class ONRMetrics(BaseModel):
    flame_count: int
    comment_count: int
    onr_tier: Literal["Gold", "Silver", "Unknown"]
    participants_discord_handles: List[str]
    participant_identities: List[ParticipantIdentity] = []

class ONRHandoffBundle(BaseModel):
    paper_metadata: dict
    metrics: ONRMetrics
    discussion_log: List[ONRDiscussionMessage]