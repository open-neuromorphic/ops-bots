#!/usr/bin/env python3
import asyncio
import sys
import os
import aiohttp

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config


async def audit_github_pages():
    token = config.GITHUB_TOKEN or config.GITHUB_TOKEN_BOT
    if not token:
        print("❌ ERROR: GITHUB_TOKEN is not set in the environment or .env file.")
        sys.exit(1)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ONM-Ops-Audit"
    }

    org = config.PROD_REPO_OWNER
    print(f"🔍 Scanning repositories for organization: '{org}'...\n")

    async with aiohttp.ClientSession(headers=headers) as session:
        repos = []
        page = 1
        while True:
            url = f"https://api.github.com/orgs/{org}/repos?per_page=100&page={page}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    print(f"❌ Failed to fetch repositories (HTTP {resp.status}): {err}")
                    sys.exit(1)
                data = await resp.json()
                if not data:
                    break
                repos.extend(data)
                page += 1

        print(f"📦 Found {len(repos)} repositories. Checking Pages configurations...")

        enabled_repos = []
        disabled_repos = []

        for repo in repos:
            repo_name = repo['name']
            pages_url = f"https://api.github.com/repos/{org}/{repo_name}/pages"

            async with session.get(pages_url) as resp:
                if resp.status == 200:
                    page_data = await resp.json()
                    enabled_repos.append((repo_name, page_data.get('html_url', 'Unknown URL')))
                elif resp.status == 404:
                    disabled_repos.append(repo_name)
                else:
                    print(f"⚠️ Warning: Unexpected HTTP {resp.status} when checking {repo_name}")

        print("\n==================================================")
        print("             GITHUB PAGES AUDIT REPORT            ")
        print("==================================================")
        print(f"Total Repositories Scanned: {len(repos)}")
        print(f"Pages Disabled:             {len(disabled_repos)}")
        print(f"Pages Enabled:              {len(enabled_repos)}\n")

        print("🌐 REPOSITORIES WITH PAGES ENABLED:")

        expected_repos = {config.PROD_REPO_NAME, config.STAGING_REPO_NAME, config.ONR_STAGING_REPO_NAME}

        if not enabled_repos:
            print("  (None found)")

        for repo_name, url in enabled_repos:
            if repo_name in expected_repos:
                print(f"  ✅ {repo_name} (Expected)")
                print(f"     URL: {url}\n")
            else:
                print(f"  🚨 {repo_name} (UNEXPECTED ALERTS!)")
                print(f"     URL: {url}")
                print(f"     Action: Disable Pages in repo settings -> Pages to prevent org domain pollution.\n")

        print("==================================================")


if __name__ == "__main__":
    asyncio.run(audit_github_pages())