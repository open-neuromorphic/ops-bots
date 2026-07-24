import asyncio
import subprocess
import logging
import base64
from pathlib import Path
import config
from services.http import get_session
from models.github import GitHubIssue, GitHubComment
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class FileWrite(BaseModel):
    path: str
    content: bytes

def _get_headers():
    if not config.GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not configured.")
    return {
        "Authorization": f"token {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ONM-Discord-Bot"
    }

def _get_bot_headers():
    token = config.GITHUB_TOKEN_BOT or config.GITHUB_TOKEN
    if not token:
        raise ValueError("GITHUB_TOKEN_BOT is not configured.")
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ONM-Discord-Bot"
    }

async def search_issues(query: str) -> list[GitHubIssue]:
    url = "https://api.github.com/search/issues"
    headers = _get_headers()
    results = []
    page = 1
    session = await get_session()
    while True:
        params = {'q': query, 'per_page': 100, 'page': page}
        async with session.get(url, headers=headers, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
            items = data.get('items', [])
            for item in items:
                results.append(GitHubIssue.model_validate(item))
            if len(items) < 100: break
            page += 1
    return results

async def fetch_pr_diff(diff_url: str) -> str:
    headers = _get_headers()
    headers['Accept'] = 'application/vnd.github.v3.diff'
    session = await get_session()
    try:
        async with session.get(diff_url, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.text()
    except Exception as e:
        logger.warning(f"Error fetching diff from {diff_url}: {e}")
        return f"[Could not fetch diff content: {e}]"

async def get_recent_commits(owner: str, repo: str, since_iso: str) -> list[dict]:
    url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    headers = _get_headers()
    params = {"since": since_iso}
    session = await get_session()
    async with session.get(url, headers=headers, params=params) as resp:
        if resp.status == 200:
            return await resp.json()
        return []

async def get_issue(owner: str, repo: str, number: int) -> GitHubIssue:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    headers = _get_headers()
    session = await get_session()
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        return GitHubIssue.model_validate(await resp.json())

async def get_issue_comments(owner: str, repo: str, number: int) -> list[GitHubComment]:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments"
    headers = _get_headers()
    session = await get_session()
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return [GitHubComment.model_validate(c) for c in data]

async def get_pr_files(owner: str, repo: str, pull_number: int) -> list[dict]:
    """Fetches the list of files modified in a given Pull Request."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}/files"
    headers = _get_headers()
    session = await get_session()
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            return await resp.json()
        return []

async def create_github_issue(owner: str, repo: str, title: str, body: str) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = _get_bot_headers()
    payload = {"title": title, "body": body}
    session = await get_session()
    async with session.post(url, headers=headers, json=payload) as resp:
        resp.raise_for_status()
        return await resp.json()

async def create_file_in_repo(owner: str, repo: str, path: str, content: str, commit_msg: str, branch: str = "main") -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    headers = _get_bot_headers()
    encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    payload = {
        "message": commit_msg,
        "content": encoded_content,
        "branch": branch
    }
    session = await get_session()
    async with session.put(url, headers=headers, json=payload) as resp:
        resp.raise_for_status()
        return await resp.json()

async def ensure_repo_cache(owner: str, repo: str) -> Path:
    cache_path = Path(config.GITHUB_DATA_DIR) / "repos" / f"{owner}_{repo}"

    def _run_git():
        if cache_path.exists():
            subprocess.run(["git", "-C", str(cache_path), "fetch", "origin"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(cache_path), "checkout", "-B", "main", "origin/main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(cache_path), "reset", "--hard", "origin/main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(cache_path), "clean", "-fd"], check=True, capture_output=True)
        else:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            repo_url = f"https://github.com/{owner}/{repo}.git"
            subprocess.run(["git", "clone", repo_url, str(cache_path)], check=True, capture_output=True)

    await asyncio.to_thread(_run_git)
    return cache_path

async def push_draft_via_git(branch_name: str, files: list[FileWrite], commit_msg: str,
                             prod_owner: str, prod_repo: str, staging_owner: str, staging_repo: str) -> None:
    repo_path = Path(config.GITHUB_DATA_DIR) / "repos" / f"{prod_owner}_{prod_repo}"

    def _execute():
        if not repo_path.exists():
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", f"https://github.com/{prod_owner}/{prod_repo}.git", str(repo_path)], check=True)

        def _run(*args, hide_output=False):
            stderr = subprocess.DEVNULL if hide_output else None
            stdout = subprocess.DEVNULL if hide_output else None
            subprocess.run(list(args), cwd=str(repo_path), check=True, stderr=stderr, stdout=stdout)

        push_token = config.GITHUB_TOKEN_BOT or config.GITHUB_TOKEN
        staging_url = f"https://x-access-token:{push_token}@github.com/{staging_owner}/{staging_repo}.git"

        try:
            _run("git", "remote", "add", "staging", staging_url, hide_output=True)
        except subprocess.CalledProcessError:
            _run("git", "remote", "set-url", "staging", staging_url, hide_output=True)

        _run("git", "fetch", "origin")
        _run("git", "checkout", "main")
        _run("git", "reset", "--hard", "origin/main")
        _run("git", "checkout", "-B", branch_name)

        for f in files:
            file_path = repo_path / f.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(f.content)
            _run("git", "add", f.path)

        status = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo_path), capture_output=True, text=True)

        if status.stdout.strip():
            _run("git", "-c", "user.name=ONM Bot", "-c", "user.email=bot@open-neuromorphic.org", "commit", "-m", commit_msg)
            push_process = subprocess.run(["git", "push", "-f", "staging", branch_name], cwd=str(repo_path), capture_output=True, text=True)
            if push_process.returncode != 0:
                err_msg = push_process.stderr
                if push_token: err_msg = err_msg.replace(push_token, "[REDACTED_TOKEN]")
                if config.GITHUB_TOKEN: err_msg = err_msg.replace(config.GITHUB_TOKEN, "[REDACTED_TOKEN]")
                raise RuntimeError(f"Git push failed (code {push_process.returncode}):\n{err_msg}")

    await asyncio.to_thread(_execute)

async def create_pr(owner: str, repo: str, title: str, body: str, head: str, base: str = "main") -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = _get_bot_headers()
    payload = {"title": title, "body": body, "head": head, "base": base}
    session = await get_session()
    async with session.post(url, headers=headers, json=payload) as resp:
        resp.raise_for_status()
        return await resp.json()

async def get_pr_by_branch(owner: str, repo: str, head: str) -> dict | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = _get_headers()
    params = {"head": head, "state": "open"}
    session = await get_session()
    async with session.get(url, headers=headers, params=params) as resp:
        resp.raise_for_status()
        data = await resp.json()
        return data[0] if data else None

async def update_pr(owner: str, repo: str, pr_number: int, title: str, body: str) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = _get_bot_headers()
    payload = {"title": title, "body": body}
    session = await get_session()
    async with session.patch(url, headers=headers, json=payload) as resp:
        resp.raise_for_status()
        return await resp.json()

async def get_repo_labels(owner: str, repo: str) -> list[dict]:
    """Fetches the complete schema/list of labels defined in a GitHub repository."""
    url = f"https://api.github.com/repos/{owner}/{repo}/labels"
    headers = _get_headers()
    session = await get_session()
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            return await resp.json()
        return []