from pydantic import BaseModel
from typing import Optional, Literal, Dict, Any

class ContextBuildRequest(BaseModel):
    profile: Literal["full", "compact", "hybrid"]
    discord: str = "all"
    transcripts: str = "all"
    github: str = "all"
    github_mode: str = "docs"
    since: Optional[str] = None
    dry_run: bool = False
    out: Optional[str] = None

class ConversationMessage(BaseModel):
    role: str
    content: str

class LLMRequest(BaseModel):
    task_type: Literal["strong", "fast"]
    prompt: str
    system: Optional[str] = None
    tools: Optional[list[Dict[str, Any]]] = None
    conversation: Optional[list[ConversationMessage]] = None
    multimodal_data: Optional[list[Dict[str, str]]] = None  # Expected format: [{"mime_type": "image/jpeg", "data": "<base64_string>"}]
    max_tokens: int = 8000
    response_schema: Optional[Dict[str, Any]] = None
    thinking_level: Literal["minimal", "low", "medium", "high"] = "high"