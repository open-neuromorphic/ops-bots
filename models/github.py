from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class GitHubUser(BaseModel):
    login: str

class GitHubLabel(BaseModel):
    id: Optional[int] = None
    name: str
    color: Optional[str] = None
    description: Optional[str] = None

class GitHubIssue(BaseModel):
    number: int
    title: str
    state: str
    body: Optional[str] = None
    user: Optional[GitHubUser] = None
    labels: List[GitHubLabel] = []
    html_url: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    closed_at: Optional[str] = None
    comments: int = 0
    pull_request: Optional[Dict[str, Any]] = None

class GitHubComment(BaseModel):
    body: str
    user: GitHubUser
    created_at: Optional[str] = None