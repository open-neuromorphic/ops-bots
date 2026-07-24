import asyncio
import json
import os
import sys
from pathlib import Path
import aiohttp

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from services.http import get_session, close_session

OUTPUT_FILE = "tmp/onm_structural_audit.json"

async def fetch_endpoint(session: aiohttp.ClientSession, url: str, headers: dict, method: str = "GET", json_data: dict = None) -> tuple[int, any]:
    try:
        async with session.request(method, url, headers=headers, json=json_data) as resp:
            if resp.status == 204:
                return resp.status, {}
            try:
                data = await resp.json()
            except Exception:
                data = await resp.text()
            return resp.status, data
    except Exception as e:
        return 500, {"error": str(e)}

async def query_graphql(session: aiohttp.ClientSession, token: str, query: str, variables: dict = None) -> dict:
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "ONM-Ops-Audit"
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    async with session.post(url, headers=headers, json=payload) as resp:
        if resp.status != 200:
            text = await resp.text()
            return {"error": f"HTTP {resp.status}", "details": text}
        return await resp.json()

async def run_audit():
    token = config.GITHUB_TOKEN or config.GITHUB_TOKEN_BOT
    if not token:
        print("❌ GITHUB_TOKEN or GITHUB_TOKEN_BOT is missing. Please set it in secrets/.env.")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ONM-Ops-Audit"
    }

    org = "open-neuromorphic"
    repo = "communications"
    website_repo = "open-neuromorphic.github.io"
    session = await get_session()

    print(f"🔍 Initializing organizational audit for '{org}'...")
    results = {
        "generated_at": asyncio.get_event_loop().time(),
        "org_settings": {},
        "repo_settings": {},
        "branch_protection": {},
        "issue_templates": {},
        "project_v2_fields": {},
        "custom_properties": {},
        "repo_labels": {},
        "access_token_scopes": {}
    }

    # Token Scope check
    print("Checking token credentials...")
    status, rate_data = await fetch_endpoint(session, "https://api.github.com/rate_limit", headers)
    if status == 200:
        results["access_token_scopes"] = {
            "rate_limit": rate_data.get("resources", {}).get("core", {}),
        }

    # Org Settings
    status, org_data = await fetch_endpoint(session, f"https://api.github.com/orgs/{org}", headers)
    if status == 200:
        results["org_settings"] = {
            "name": org_data.get("name"),
            "id": org_data.get("id"),
            "default_repository_permission": org_data.get("default_repository_permission"),
            "members_can_create_repositories": org_data.get("members_can_create_repositories")
        }

    # Communications Repo Settings
    status, repo_data = await fetch_endpoint(session, f"https://api.github.com/repos/{org}/{repo}", headers)
    if status == 200:
        results["repo_settings"] = {
            "name": repo_data.get("name"),
            "has_issues": repo_data.get("has_issues"),
            "default_branch": repo_data.get("default_branch")
        }
        default_branch = repo_data.get("default_branch", "main")
        status, protect_data = await fetch_endpoint(session, f"https://api.github.com/repos/{org}/{repo}/branches/{default_branch}/protection", headers)
        results["branch_protection"] = {"status": status, "config": protect_data}

    # Issue Templates
    status, templates_data = await fetch_endpoint(session, f"https://api.github.com/repos/{org}/{repo}/contents/.github/ISSUE_TEMPLATE", headers)
    if status == 200 and isinstance(templates_data, list):
        results["issue_templates"] = {
            "status": status,
            "templates": [t.get("name") for t in templates_data if t.get("type") == "file"]
        }

    # Fetch standard issue labels for both communications and website repos
    print(f"Fetching standard issue labels for '{repo}' and '{website_repo}'...")
    results["repo_labels"] = {}
    for r in [repo, website_repo]:
        status, labels_data = await fetch_endpoint(session, f"https://api.github.com/repos/{org}/{r}/labels?per_page=100", headers)
        if status == 200:
            results["repo_labels"][r] = [
                {"name": l.get("name"), "color": l.get("color"), "description": l.get("description")}
                for l in labels_data
            ]
        else:
            results["repo_labels"][r] = {"error_status": status, "details": labels_data}

    # GraphQL for Projects v2
    project_query = """
    query($orgName: String!) {
      organization(login: $orgName) {
        projectsV2(first: 10) {
          nodes {
            id
            title
            number
            closed
            fields(first: 30) {
              nodes {
                __typename
                ... on ProjectV2Field {
                  id
                  name
                  dataType
                }
                ... on ProjectV2SingleSelectField {
                  id
                  name
                  dataType
                  options {
                    id
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    gql_res = await query_graphql(session, token, project_query, {"orgName": org})
    results["project_v2_fields"] = gql_res

    # Output writing
    output_path = Path(OUTPUT_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"✅ Structural configurations with Repository Labels written to: {OUTPUT_FILE}")

if __name__ == "__main__":
    try:
        asyncio.run(run_audit())
    finally:
        asyncio.run(close_session())