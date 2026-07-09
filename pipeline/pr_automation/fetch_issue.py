from pydantic import BaseModel
from typing import List
from services.github import get_issue, get_issue_comments
from models.github import GitHubComment

class IssueContext(BaseModel):
    owner: str
    repo: str
    number: int
    title: str
    body: str
    author: str
    labels: List[str]
    comments: List[GitHubComment]

    def to_prompt_string(self) -> str:
        s = f"Issue #{self.number}: {self.title}\n"
        s += f"Author: @{self.author}\n"
        s += f"Labels: {', '.join(self.labels)}\n\n"
        s += f"--- ISSUE BODY ---\n{self.body}\n\n"
        if self.comments:
            s += "--- COMMENTS ---\n"
            for c in self.comments:
                s += f"@{c.user.login}: {c.body}\n\n"
        return s

async def fetch_issue_context(owner: str, repo: str, number: int) -> IssueContext:
    issue_data = await get_issue(owner, repo, number)
    comments_data = []
    if issue_data.comments > 0:
        comments_data = await get_issue_comments(owner, repo, number)

    return IssueContext(
        owner=owner,
        repo=repo,
        number=number,
        title=issue_data.title,
        body=issue_data.body or '',
        author=issue_data.user.login if issue_data.user else '',
        labels=[label.name for label in issue_data.labels],
        comments=comments_data
    )