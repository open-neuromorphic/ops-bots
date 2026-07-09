import asyncio
import json
import os
import sys
from pathlib import Path

# Fix ModuleNotFoundError by injecting project root into sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from pipeline.pr_automation.fetch_issue import fetch_issue_context
from pipeline.pr_automation.fetch_images import extract_image_candidates
from pipeline.pr_automation.build_context import build_prompt_context
from pipeline.pr_automation.generate_content import generate_draft
from pipeline.pr_automation.submit_pr import push_draft_to_staging, open_production_pr
from pipeline.pr_automation.generate_content import ContentDraft
from pipeline.pr_automation.override_images import apply_image_override
from services.http import close_session
from services.cache import put as cache_put


async def test_pipeline():
    try:
        print("==================================================")
        print("      ONM PR AUTOMATION - STEPWISE TESTER         ")
        print("==================================================")

        print("1. Run full pipeline (Fetch -> Gen -> Push to Staging -> PR)")
        print("2. Resume from a cached draft (Override Images or Push)")
        choice = input("Select an option (1/2): ").strip()

        if choice == "2":
            cache_dir = Path(config.CACHE_DIR) / "pr_drafts"
            drafts = [d for d in cache_dir.glob("*.json")]
            if not drafts:
                print("No cached drafts found.")
                return

            print("\nAvailable drafts:")
            for i, d in enumerate(drafts):
                print(f"{i + 1}. {d.name}")

            d_idx = input(f"Select a draft to load (1-{len(drafts)}): ")
            if not d_idx.isdigit() or not (1 <= int(d_idx) <= len(drafts)):
                print("Invalid choice.")
                return

            draft_file = drafts[int(d_idx) - 1]
            with open(draft_file, 'r', encoding="utf-8") as f:
                data = json.load(f)

            draft = ContentDraft.model_validate(data)
            draft_id = draft_file.stem

            print(f"\nLoaded draft: {draft.branch_name}")
            print(f"Target Path: {draft.target_path}")
            print(f"Image Assets Cached: {len(draft.image_assets)}")
            if draft.discovered_candidates:
                print(f"Discovered Candidates: {', '.join(c.candidate_id for c in draft.discovered_candidates)}")

            do_override = input("\nDo you want to test manual image override? (y/N): ")
            if do_override.lower() == 'y':
                c_ids = input("Enter comma-separated candidate IDs (e.g. img_1,img_2) or 'clear': ")
                candidate_ids = [c.strip() for c in c_ids.split(",") if c.strip()]

                print("\n--- APPLYING OVERRIDE ---")
                draft = await apply_image_override(draft_id, candidate_ids)
                print("✅ Override Complete!")
                for asset in draft.image_assets:
                    print(f"  - {asset.role} -> {asset.target_path}")
                for w in draft.image_warnings:
                    print(f"  ⚠️ {w}")

            proceed = input("\nProceed to Git Push to Staging? (y/N): ")
            if proceed.lower() == 'y':
                print("\n--- STEP 4: Git Push to Staging ---")
                try:
                    preview, actions = await push_draft_to_staging(draft)
                    print(f"✅ Staged! View live preview here: {preview}")

                    proceed_pr = input(f"\nProceed to Step 5? Open PR to Production? (y/N): ")
                    if proceed_pr.lower() == 'y':
                        status = await open_production_pr(draft)
                        print("\n" + status)
                except Exception as e:
                    print(f"\n❌ Pipeline failed:\n{e}")
            return

        issue_num = input("\nEnter a valid GitHub Issue Number from the Website Repo to test (e.g. 169): ")
        if not issue_num.isdigit():
            print("Invalid issue number.")
            return

        issue_num = int(issue_num)
        owner = config.PROD_REPO_OWNER
        repo = config.PROD_REPO_NAME

        print(f"\n--- STEP 1: Fetching Issue #{issue_num} ---")
        issue_context = await fetch_issue_context(owner, repo, issue_num)
        print(f"Title: {issue_context.title}")
        print(f"Author: {issue_context.author}")
        print(f"Body snippet: {issue_context.body[:100]}...")
        print(f"Comments found: {len(issue_context.comments)}")

        candidates = extract_image_candidates(issue_context)
        print(f"Images found: {len(candidates)}")
        for c in candidates:
            print(f"  - [{c.candidate_id}] {c.url}")

        input("\nPress Enter to proceed to Step 2 (Clone repo & Build Context)...")

        print("\n--- STEP 2: Building Prompt Context ---")
        print("Cloning/pulling repository (check ~/Documents/onm-library/github_data/repos/ after this)...")
        prompt = await build_prompt_context(issue_context, candidates)
        print(f"Prompt built successfully. Size: {len(prompt)} characters.")

        input("Press Enter to proceed to Step 3 (Call LLM to generate JSON & Download images)...")

        print("\n--- STEP 3: LLM Generation & Media Download ---")
        print("Calling LLM... (this may take 10-30 seconds)")
        draft = await generate_draft(issue_context)

        draft_id = f"{draft.issue_ref}_{draft.generated_at}"
        cache_put(f"{draft_id}.json", draft.model_dump_json(indent=2), subdir="pr_drafts")
        cache_put(f"{draft_id}.md", draft.content, subdir="pr_drafts")

        print(f"\n✅ DRAFT GENERATED & CACHED ({draft_id})!")
        print(f"Target Path: {draft.target_path}")
        print(f"Branch Name: {draft.branch_name}")
        print(f"PR Title: {draft.pr_title}")
        print(f"Image Assets Accepted: {len(draft.image_assets)}")
        for asset in draft.image_assets:
            print(f"  ✅ {asset.role} -> {asset.target_path} ({asset.size_bytes} bytes)")
        for warning in draft.image_warnings:
            print(f"  ⚠️ WARNING: {warning}")

        proceed = input(f"\nProceed to Step 4? Commit and push to STAGING! (y/N): ")
        if proceed.lower() == 'y':
            print("\n--- STEP 4: Git Push to Staging ---")
            try:
                preview, actions = await push_draft_to_staging(draft)
                print(f"✅ Staged! View live preview here: {preview}")

                proceed_pr = input(f"\nProceed to Step 5? Open PR to Production? (y/N): ")
                if proceed_pr.lower() == 'y':
                    status = await open_production_pr(draft)
                    print("\n" + status)
            except Exception as e:
                print(f"\n❌ Pipeline failed:\n{e}")
        else:
            print(
                "\nPipeline test aborted before Git push. You can inspect the generated files in the cache directory.")

    finally:
        await close_session()


if __name__ == "__main__":
    asyncio.run(test_pipeline())