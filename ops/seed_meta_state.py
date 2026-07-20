#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

# Ensure the script can run standalone by adding project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config


def generate_bootstrap_guide(meta_dir: Path):
    """Generates a markdown file with instructions and an exact prompt for a frontier LLM."""
    guide_path = meta_dir / "AI_BOOTSTRAP_PROMPT.md"

    prompt_content = """# Meta State AI Bootstrapping Guide

To get the best results from this context engine, the AI needs to know who your key people are and what your ongoing strategic threads are. 
Instead of writing these by hand, you can use a frontier AI model (like Claude 3.5 Sonnet, Gemini 1.5 Pro, or GPT-4o) to generate them from your existing history.

## The Process

1. **Generate your historical archive:** In Discord, run `/onm-context build profile:full deliver:save-only` to generate a comprehensive XML dump of your organizational history to the host disk. (Check the `artifacts/bundles/` directory).
2. **Open a Frontier LLM:** Go to ChatGPT, Claude, or Google AI Studio.
3. **Upload the file:** Attach the `.xml` bundle generated in Step 1.
4. **Paste the prompt:** Copy and paste the prompt block below.
5. **Save the results:** Copy the two JSON code blocks the AI gives you, and save them as `entity_glossary.json` and `threads_ledger.json` in this folder (`~/Documents/onm-library/meta/`).

---
### Copy the text below into the AI:

I am setting up an AI context engine for my organization. Attached is a massive XML data dump of our recent meeting transcripts, chat logs, and documentation.

Please analyze this entire document and extract two JSON files for me. Be meticulous about names, aliases, and ongoing projects.

**FILE 1: entity_glossary.json**
Identify the most active people, leaders, and contributors. Also identify key organizations, projects, and concepts that are frequently misheard by transcription AIs. Return a valid JSON object where keys for people are a `snake_case` version of their name.
Schema:
```json
{
  "known_non_persons": {
    "Open Neuromorphic": {
      "acronyms": ["ONM"],
      "misheard_as": ["open your morphic", "O and M"]
    }
  },
  "john_doe": {
    "canonical_name": "John Doe",
    "discord_handles": ["jdoe", "johnny"],
    "fathom_names": ["John Doe", "John D."],
    "github_username": "jdoe_gh",
    "transcript_aliases": ["Jon Dough", "John Dough"],
    "role": "Their role or title inferred from context",
    "notes": "Brief context about what they do or care about.",
    "misheard_as": ["John Dough", "Jon Dough"]
  }
}
```

**FILE 2: threads_ledger.json**
Identify 3 to 5 major ongoing strategic, governance, or technical threads/projects discussed in these logs.
Schema:
```json
{
  "project-alpha": {
    "title": "Name of the project",
    "category": "engineering",
    "status": "active",
    "summary": "1 paragraph summary of the current state.",
    "history": [],
    "last_updated": "2024-01-01",
    "last_updated_by_run": "initial-seed",
    "related_entities": ["john_doe"],
    "confidentiality_note": null
  }
}
```

Please output ONLY the two JSON code blocks. Do not include introductory text.
"""
    guide_path.write_text(prompt_content, encoding="utf-8")
    return guide_path


def seed_meta():
    print("======================================================")
    print(">>> INITIALIZING META STATE (GLOSSARY & LEDGER) <<<")
    print("======================================================")

    meta_dir = Path(config.META_DIR)
    meta_dir.mkdir(parents=True, exist_ok=True)

    glossary_path = meta_dir / "entity_glossary.json"
    ledger_path = meta_dir / "threads_ledger.json"

    # 1. Generate the Bootstrapping Guide
    guide_p = generate_bootstrap_guide(meta_dir)
    print("\n💡 AI BOOTSTRAP GUIDE GENERATED!")
    print(f"We have generated an instruction file and LLM prompt at:\n{guide_p}")
    print("\nHighly Recommended: Follow that guide to have a frontier model automatically")
    print("generate your glossary and ledger from your historical XML data before continuing.")
    print("------------------------------------------------------\n")

    # 2. Seed generic fallback Glossary
    if not glossary_path.exists():
        print("Seeding fallback entity_glossary.json...")
        seed_glossary_data = {
            "known_non_persons": {
                "Example Organization": {
                    "acronyms": ["EO"],
                    "misheard_as": ["example org", "sample organization"]
                }
            },
            "alice_smith": {
                "canonical_name": "Alice Smith",
                "discord_handles": ["alice", "asmith"],
                "fathom_names": ["Alice Smith", "Alice"],
                "github_username": "alicesmith123",
                "transcript_aliases": ["Alis Smith"],
                "role": "Project Lead",
                "notes": "Example entry for the glossary. Replace this file via the bootstrap process.",
                "misheard_as": ["Alis", "Alex Smith"]
            }
        }
        with open(glossary_path, "w", encoding="utf-8") as f:
            json.dump(seed_glossary_data, f, indent=2)
    else:
        print("entity_glossary.json already exists. Skipping fallback seed.")

    # 3. Seed generic fallback Ledger
    if not ledger_path.exists():
        print("Seeding fallback threads_ledger.json...")
        seed_ledger_data = {
            "example-project-alpha": {
                "title": "Project Alpha Development",
                "category": "engineering",
                "status": "active",
                "summary": "Example thread tracking the development of Project Alpha.",
                "history": [],
                "last_updated": "2026-01-01",
                "last_updated_by_run": "seed",
                "related_entities": ["alice_smith"],
                "confidentiality_note": None
            }
        }
        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(seed_ledger_data, f, indent=2)
    else:
        print("threads_ledger.json already exists. Skipping fallback seed.")

    print("\n✅ Setup Complete.")
    print(f"Directory: {config.META_DIR}")


def main():
    seed_meta()


if __name__ == "__main__":
    main()