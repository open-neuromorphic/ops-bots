from pydantic import BaseModel
from typing import Optional, Literal

class LibraryEntry(BaseModel):
    id: str
    title: str
    date: str
    source_type: str
    category_tag: str
    tagged_by: str = "system"
    excluded: bool = False
    exclusion_reason: Optional[str] = None
    source_path: Optional[str] = None
    content_hash: Optional[str] = None
    token_count: Optional[int] = None
    summary_path: Optional[str] = None
    summary_date: Optional[str] = None
    summary_model: Optional[str] = None
    audience_tier: Literal["public", "volunteer", "ec"] = "ec"
    confidentiality_note: Optional[str] = None